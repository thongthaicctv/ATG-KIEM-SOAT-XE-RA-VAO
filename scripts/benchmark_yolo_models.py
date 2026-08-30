"""scripts/benchmark_yolo_models.py

Benchmark hieu nang INFERENCE-ONLY cho mot model YOLO (.pt) tren mot thiet bi cu the
(vi du NVIDIA T600 4GB). Cong cu nay DOC LAP voi app production: khong import
app.services.detector, app.database, app.services.camera_manager/camera_worker/
rtsp_capture, khong dung toi data/parking.db, khong mo RTSP.

KHONG do accuracy/mAP o Phase nay - chi do performance/resource:
model load time, warm-up, inference latency (avg/median/p95), throughput FPS,
VRAM (allocated/reserved/peak), CPU RSS (best-effort), va mot uoc luong tho
"bao nhieu camera co the xu ly" (INFERENCE_ONLY_ESTIMATE - KHONG phai capacity
production chinh thuc, khong tinh preview/RTSP/tracker overhead).

Model KHONG bao gio duoc Ultralytics tu tai: neu file model chua ton tai tren dia,
tool fail ngay voi "MODEL_NOT_FOUND: <path>" TRUOC KHI `ultralytics` duoc import.

Vi du (PowerShell, Windows, tu project root):

    .\\.venv\\Scripts\\python.exe .\\scripts\\benchmark_yolo_models.py `
        --model .\\models\\yolo11n.pt `
        --device cuda:0 `
        --imgsz 640 `
        --half `
        --warmup 20 `
        --iterations 200 `
        --json-output reports\\benchmark\\yolo11n_640_fp16.json

Tool nay CHI report du lieu do duoc. No KHONG tu chon "model nao tot hon" - quyet
dinh model production duoc dua ra rieng, sau khi xem xet ca performance lan cac
yeu to khac (VRAM margin, do on dinh, accuracy thuc dia...).

Exit code:
    0  STATUS=PASS
    1  MODEL_NOT_FOUND (model .pt khong ton tai tren dia)
    2  CUDA duoc yeu cau (--device cuda:*) nhung khong kha dung - khong fallback CPU am tham
    4  STATUS=OOM (CUDA het VRAM; da bat duoc, khong crash)
    5  STATUS=ERROR khac (vi du input anh khong doc duoc)
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]

# Sample anh co san trong repo, KHONG chua RTSP/credential (anh training "hard negative").
# Uu tien dung sample nay khi nguoi dung khong truyen --input, truoc khi roi sang synthetic.
DEFAULT_SAMPLE_IMAGE = ROOT_DIR / "data" / "hard_negatives" / "CAMERA-1" / "fan" / "fan-session-000058.jpg"

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp")


class ModelNotFoundError(RuntimeError):
    """File model .pt khong ton tai tren dia. Khong bao gio de Ultralytics tu tai:
    ham validate_model_path() luon duoc goi TRUOC khi `ultralytics` co co hoi import."""


class CudaUnavailableError(RuntimeError):
    """--device cuda:* duoc yeu cau nhung CUDA khong kha dung. Khong fallback CPU am tham."""


class InputImageError(RuntimeError):
    """Khong doc duoc anh input (file/thu muc khong hop le)."""


# ---------------------------------------------------------------------------
# Cac ham thuan (pure) - khong dung torch/ultralytics/CUDA - de unit test nhanh,
# khong can GPU, khong can pytest chay lau.
# ---------------------------------------------------------------------------

def validate_model_path(model_path: str | Path) -> Path:
    """Fail-fast neu model .pt chua ton tai. KHONG duoc goi sau khi da import ultralytics."""
    path = Path(model_path)
    if not path.is_file():
        raise ModelNotFoundError(f"MODEL_NOT_FOUND: {path}")
    return path


def validate_device(device: str, cuda_available: bool) -> None:
    """Khong fallback CPU am tham: neu --device cuda:* ma CUDA khong san sang, raise ro."""
    if device.startswith("cuda") and not cuda_available:
        raise CudaUnavailableError(
            f"DETECTOR_CUDA_UNAVAILABLE: da chon --device {device} nhung CUDA khong kha dung "
            "tren may nay. Hay chon --device cpu, hoac kiem tra lai cai dat PyTorch CUDA."
        )


def percentiles(samples_ms: list[float]) -> dict[str, float]:
    """avg/median/p95 (ms) tu danh sach latency SAU warm-up. p95 kieu 'nearest-rank' - don
    gian, on dinh, du dung cho benchmark performance (khong phai thong ke khoa hoc chinh xac)."""
    if not samples_ms:
        raise ValueError("EMPTY_SAMPLES: can it nhat 1 sample sau warm-up")
    ordered = sorted(samples_ms)
    avg = sum(ordered) / len(ordered)
    median = statistics.median(ordered)
    index = max(0, min(len(ordered) - 1, round(0.95 * (len(ordered) - 1))))
    p95 = ordered[index]
    return {"avg_ms": avg, "median_ms": median, "p95_ms": p95}


def fps_from_avg_ms(avg_ms: float, batch: int = 1) -> float:
    """FPS tuong duong tren tung frame rieng le (nhan voi batch de ra throughput theo frame,
    vi production xu ly moi camera 1 frame/tick, khong batch nhieu camera lai voi nhau)."""
    if avg_ms <= 0:
        return 0.0
    return (1000.0 / avg_ms) * max(1, batch)


def estimate_cameras(inference_fps: float, processing_fps: float) -> int:
    """UOC LUONG THO: chia deu throughput inference cho processing_fps/camera.
    KHONG tinh preview/RTSP/tracker overhead - xem INFERENCE_ONLY_ESTIMATE. KHONG phai
    capacity production chinh thuc, chi mot con so tham khao ban dau."""
    if processing_fps <= 0:
        raise ValueError("processing_fps phai > 0")
    return math.floor(inference_fps / processing_fps)


def parse_size(spec: str) -> tuple[int, int]:
    """'1920x1080' -> (1920, 1080). Dung cho synthetic frame khi khong co anh that."""
    try:
        width_str, height_str = spec.lower().split("x", 1)
        width, height = int(width_str), int(height_str)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"INVALID_SIZE: '{spec}' phai co dang WIDTHxHEIGHT, vi du 1920x1080") from exc
    if width <= 0 or height <= 0:
        raise ValueError(f"INVALID_SIZE: '{spec}' phai co width/height > 0")
    return width, height


def process_rss_mb() -> float | None:
    """CPU RAM (working set) cua process hien tai, MB. Best-effort, KHONG them dependency
    moi (khong dung psutil). Tra ve None neu khong do duoc tren nen tang hien tai - day la
    metric phu, khong lam benchmark fail vi ly do nay."""
    try:
        import resource  # POSIX only

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux: ru_maxrss don vi KB. (macOS dung bytes - khong phai muc tieu cua tool nay.)
        return usage / 1024.0
    except ImportError:
        pass
    try:  # pragma: no cover - chi chay tren Windows, khong test duoc trong sandbox Linux
        import ctypes
        import ctypes.wintypes as wintypes

        class _ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(_ProcessMemoryCounters)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
        if ok:
            return counters.WorkingSetSize / 1024.0 / 1024.0
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Cau truc du lieu
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkCase:
    model: str
    device: str
    imgsz: int
    half: bool
    batch: int
    warmup: int
    iterations: int


@dataclass
class BenchmarkResult:
    model: str
    device: str
    imgsz: int
    half: bool
    batch: int
    status: str = "ERROR"  # PASS | OOM | ERROR
    precision_api: str = "quantize=none(fp32)"  # kwarg/gia tri THUC da truyen vao
    # Ultralytics predict() - xem resolve_precision_kwargs() de biet ly do khong con
    # dung 'half=True' (da bi deprecate, xem ghi chu o do).
    input_source: str | None = None
    load_ms: float | None = None
    avg_ms: float | None = None
    median_ms: float | None = None
    p95_ms: float | None = None
    fps: float | None = None
    vram_allocated_mb: float | None = None
    vram_reserved_mb: float | None = None
    vram_peak_allocated_mb: float | None = None
    cpu_rss_mb: float | None = None
    cuda_device_name: str | None = None
    est_cameras_4fps: int | None = None
    est_cameras_5fps: int | None = None
    warmup: int = 0
    iterations: int = 0
    error: str | None = None

    def to_json_dict(self) -> dict:
        d = asdict(self)
        d["inference_only_estimate"] = True
        return d


# ---------------------------------------------------------------------------
# Input frame
# ---------------------------------------------------------------------------

def load_frame(input_path: Path | None, synthetic_size: str):
    """Tra ve (frame_ndarray_BGR, source_label). Uu tien: --input (file hoac thu muc anh
    dau tien) > sample co san trong repo (khong credential) > synthetic frame ngau nhien
    (seed co dinh de benchmark lap lai duoc)."""
    import numpy as np
    import cv2

    candidate: Path | None = None
    if input_path is not None:
        if input_path.is_dir():
            images = sorted(p for p in input_path.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
            if not images:
                raise InputImageError(f"INPUT_DIR_EMPTY: khong tim thay anh trong {input_path}")
            candidate = images[0]
        elif input_path.is_file():
            candidate = input_path
        else:
            raise InputImageError(f"INPUT_NOT_FOUND: {input_path}")
    elif DEFAULT_SAMPLE_IMAGE.is_file():
        candidate = DEFAULT_SAMPLE_IMAGE

    if candidate is not None:
        frame = cv2.imread(str(candidate))
        if frame is None:
            raise InputImageError(f"INPUT_UNREADABLE: {candidate}")
        return frame, f"file:{candidate}"

    width, height = parse_size(synthetic_size)
    rng = np.random.default_rng(1234)
    frame = rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)
    return frame, f"synthetic:{width}x{height}"


# ---------------------------------------------------------------------------
# Benchmark that (can torch/ultralytics) - co seam de unit test bang fake/monkeypatch.
# ---------------------------------------------------------------------------

def _default_model_loader(model_path: str):
    from ultralytics import YOLO

    return YOLO(model_path)


def resolve_precision_kwargs(half: bool) -> dict:
    """Tra ve kwargs precision de merge vao predict_kwargs truoc khi goi model.predict().

    KHONG dung 'half=True': tren Ultralytics 8.4.121 (pin hien tai: requirements-ai.txt
    'ultralytics>=8.4.102,<8.5', xac nhan bang cach doc truc tiep .venv/Lib/site-packages/
    ultralytics/cfg/__init__.py), 'half'/'int8' la alias DA DEPRECATE cua 'quantize'
    (xem _handle_deprecation() trong file do). Model.predict() TAI SU DUNG predictor da
    tao (ultralytics/engine/model.py: 'self.predictor.args = get_cfg(self.predictor.args,
    args)') nen get_cfg()/check_dict_alignment()/_handle_deprecation() chay lai o MOI
    LAN goi predict(), khong chi lan dau. Neu con truyen 'half=True', dieu do co nghia
    la LOGGER.warning(...) - tuc la console I/O - se chay ben TRONG vung do thoi gian cua
    benchmark o MOI iteration, lam sai lech ket qua AVG_MS/FPS (day chinh la nguyen nhan
    goc cua ket qua bat thuong 'FP16 cham gan gap doi FP32' quan sat duoc tren Windows).

    'quantize=16' la API HIEN HANH, khong deprecate, tuong duong ve mat hieu ung (van la
    FP16: xem QUANTIZE_ALIASES['16'] == 16 va AutoBackend(fp16=self.args.quantize==16)
    trong ultralytics/engine/predictor.py) nhung KHONG di qua nhanh _handle_deprecation,
    nen khong con warning/console-I-O lot vao vung do. Khong truyen 'quantize' <=> FP32
    mac dinh, hanh vi giu nguyen nhu truoc khi sua.
    """
    return {"quantize": 16} if half else {}


def run_benchmark_case(
    case: BenchmarkCase,
    frame,
    conf: float = 0.40,
    model_loader=None,
    torch_module=None,
) -> BenchmarkResult:
    """Chay dung 1 benchmark case (1 model x 1 device x 1 imgsz x 1 half x 1 batch).
    Bat CUDA OOM va tra ve STATUS=OOM thay vi de crash. `model_loader`/`torch_module` chi
    dung de unit test (fake), mac dinh la None -> dung ultralytics/torch that."""
    torch = torch_module if torch_module is not None else __import__("torch")
    loader = model_loader if model_loader is not None else _default_model_loader
    is_cuda = case.device.startswith("cuda")

    result = BenchmarkResult(
        model=case.model, device=case.device, imgsz=case.imgsz, half=case.half,
        batch=case.batch, warmup=case.warmup, iterations=case.iterations,
    )

    if is_cuda:
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

    try:
        t_load0 = time.perf_counter()
        model = loader(case.model)
        if is_cuda:
            torch.cuda.synchronize()
        result.load_ms = (time.perf_counter() - t_load0) * 1000

        sources = [frame] * max(1, case.batch)
        predict_kwargs = {"imgsz": case.imgsz, "device": case.device, "verbose": False, "conf": conf}
        # KHONG dung predict_kwargs["half"]=True (deprecated, gay warning moi iteration).
        # Xem docstring resolve_precision_kwargs() de biet root cause day du.
        predict_kwargs.update(resolve_precision_kwargs(case.half))
        result.precision_api = "quantize=16(fp16)" if case.half else "quantize=none(fp32)"

        for _ in range(case.warmup):
            model.predict(sources, **predict_kwargs)
        if is_cuda:
            torch.cuda.synchronize()
            # Reset peak SAU warm-up de tach load/warm-up khoi steady-state (chi do peak
            # VRAM cua vung inference lap lai, khong tinh spike luc nap model/warm-up).
            torch.cuda.reset_peak_memory_stats()

        samples_ms: list[float] = []
        for _ in range(case.iterations):
            if is_cuda:
                torch.cuda.synchronize()
            t0 = time.perf_counter()
            model.predict(sources, **predict_kwargs)
            if is_cuda:
                torch.cuda.synchronize()
            samples_ms.append((time.perf_counter() - t0) * 1000)

        stats = percentiles(samples_ms)
        result.avg_ms = stats["avg_ms"]
        result.median_ms = stats["median_ms"]
        result.p95_ms = stats["p95_ms"]
        result.fps = fps_from_avg_ms(stats["avg_ms"], case.batch)

        if is_cuda:
            result.vram_allocated_mb = torch.cuda.memory_allocated(0) / 1048576
            result.vram_reserved_mb = torch.cuda.memory_reserved(0) / 1048576
            result.vram_peak_allocated_mb = torch.cuda.max_memory_allocated(0) / 1048576
            result.cuda_device_name = torch.cuda.get_device_name(0)

        result.cpu_rss_mb = process_rss_mb()
        result.est_cameras_4fps = estimate_cameras(result.fps, 4.0)
        result.est_cameras_5fps = estimate_cameras(result.fps, 5.0)
        result.status = "PASS"
    except Exception as exc:  # noqa: BLE001 - benchmark tool: khong duoc de crash mo ho
        oom_type = getattr(getattr(torch, "cuda", None), "OutOfMemoryError", None)
        is_oom = (oom_type is not None and isinstance(exc, oom_type)) or "out of memory" in str(exc).lower()
        if is_cuda and is_oom:
            result.status = "OOM"
            result.error = (
                f"OOM: model={case.model} imgsz={case.imgsz} half={case.half} "
                f"batch={case.batch} device={case.device}: {exc}"
            )
            try:
                torch.cuda.empty_cache()
            except Exception:  # noqa: BLE001 - don dep best-effort, khong duoc raise them
                pass
        else:
            result.status = "ERROR"
            result.error = str(exc)
    return result


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def format_result(result: BenchmarkResult) -> str:
    def fmt(value, digits=1):
        return "-" if value is None else f"{value:.{digits}f}"

    lines = [
        f"MODEL: {Path(result.model).name}",
        f"DEVICE: {result.device}",
        f"IMG: {result.imgsz}",
        f"HALF: {'true' if result.half else 'false'}",
        f"PRECISION_API: {result.precision_api}",
        f"BATCH: {result.batch}",
        f"INPUT: {result.input_source or '-'}",
        f"WARMUP: {result.warmup}",
        f"ITERATIONS: {result.iterations}",
        f"LOAD_MS: {fmt(result.load_ms)}",
        f"AVG_MS: {fmt(result.avg_ms, 3)}",
        f"MEDIAN_MS: {fmt(result.median_ms, 3)}",
        f"P95_MS: {fmt(result.p95_ms, 3)}",
        f"FPS: {fmt(result.fps, 2)}",
        f"VRAM_ALLOCATED_MB: {fmt(result.vram_allocated_mb)}",
        f"VRAM_RESERVED_MB: {fmt(result.vram_reserved_mb)}",
        f"PEAK_VRAM_MB: {fmt(result.vram_peak_allocated_mb)}",
        f"CPU_RSS_MB: {fmt(result.cpu_rss_mb)}",
        f"CUDA_DEVICE: {result.cuda_device_name or '-'}",
        f"STATUS: {result.status}",
        f"EST_CAMERAS_4FPS: {result.est_cameras_4fps if result.est_cameras_4fps is not None else '-'}",
        f"EST_CAMERAS_5FPS: {result.est_cameras_5fps if result.est_cameras_5fps is not None else '-'}",
    ]
    if result.error:
        lines.append(f"ERROR: {result.error}")
    lines.append(
        "NOTE: EST_CAMERAS_* la INFERENCE_ONLY_ESTIMATE (khong tinh preview/RTSP/tracker "
        "overhead) - KHONG phai capacity production chinh thuc."
    )
    header = f"{'MODEL':<14}{'DEVICE':<9}{'IMG':<6}{'HALF':<7}{'BATCH':<7}{'STATUS':<8}{'AVG_MS':<10}{'FPS':<8}{'PEAK_VRAM_MB':<14}"
    row = (
        f"{Path(result.model).name:<14}{result.device:<9}{result.imgsz:<6}"
        f"{('true' if result.half else 'false'):<7}{result.batch:<7}{result.status:<8}"
        f"{fmt(result.avg_ms, 2):<10}{fmt(result.fps, 2):<8}{fmt(result.vram_peak_allocated_mb):<14}"
    )
    lines.append("")
    lines.append("SUMMARY TABLE")
    lines.append(header)
    lines.append(row)
    return "\n".join(lines)


def serializable_args(args: argparse.Namespace, model_path: Path) -> dict:
    """Chuyen argparse.Namespace ve dict JSON-safe (str/int/float/bool/None) mot cach
    TUONG MINH cho tung truong - khong dung default=str mu quang cho toan bo payload.

    ROOT CAUSE cua 'TypeError: Object of type WindowsPath is not JSON serializable':
    '--input' va '--json-output' duoc khai bao 'type=Path' trong build_parser(), nen
    vars(args) tra ve pathlib.Path (WindowsPath tren Windows) cho 2 truong nay - truoc
    day main() truyen thang 'vars(args) | {"model": ...}' vao write_json_output(), quen
    khong xu ly 'input'/'json_output'. Ham nay liet ke ro tung truong Path can chuyen doi,
    de neu sau nay them CLI arg kieu Path moi ma quen xu ly thi test
    test_serializable_args_has_no_path_objects se bat loi ngay, thay vi im lang loi ra
    JSON that bai luc benchmark that tren Windows.
    """
    d = dict(vars(args))
    d["model"] = str(model_path)
    d["input"] = str(args.input) if args.input is not None else None
    d["json_output"] = str(args.json_output) if args.json_output is not None else None
    return d


def write_json_output(results: list[BenchmarkResult], path: Path, args_dict: dict | None = None) -> None:
    """Ghi JSON co cau truc de so sanh giua cac lan chay sau. Khong ghi RTSP/credential -
    tool nay khong bao gio doc rtsp_url/database, nen khong co gi de lo. args_dict PHAI da
    la kieu JSON-safe truoc khi goi ham nay (xem serializable_args()) - ham nay co chu y
    KHONG dung json.dumps(..., default=str) de bao che loi kieu du lieu mot cach mu quang.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "tool": "benchmark_yolo_models",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "args": args_dict or {},
        "results": [r.to_json_dict() for r in results],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Benchmark inference-only performance cua 1 model YOLO (.pt) tren 1 thiet bi. "
            "KHONG do accuracy/mAP. KHONG tu tai model. Doc lap voi app production."
        )
    )
    p.add_argument("--model", required=True, help="Duong dan model .pt, vi du models/yolo11n.pt. Phai ton tai san tren dia.")
    p.add_argument("--device", choices=("cpu", "cuda:0"), default="cuda:0")
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--half", action="store_true", help="FP16 - chi co hieu luc voi --device cuda:*, bi bo qua tren cpu.")
    p.add_argument("--batch", type=int, default=1)
    p.add_argument("--warmup", type=int, default=20)
    p.add_argument("--iterations", type=int, default=200)
    p.add_argument("--conf", type=float, default=0.40, help="Nguong confidence dua vao predict() cho giong production; khong anh huong nhieu toi latency.")
    p.add_argument("--input", type=Path, default=None, help="File anh hoac thu muc anh. Mac dinh: sample co san trong repo (khong credential); neu khong co se dung synthetic frame.")
    p.add_argument("--synthetic-size", default="1920x1080", help="WxH cho synthetic frame khi khong co --input/sample, vi du 1920x1080.")
    p.add_argument("--json-output", type=Path, default=None, help="Ghi ket qua structured JSON ra file nay (vi du reports/benchmark/yolo11n_640_fp16.json).")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        model_path = validate_model_path(args.model)
    except ModelNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    import torch  # sau khi model path da duoc xac nhan ton tai

    try:
        validate_device(args.device, torch.cuda.is_available())
    except CudaUnavailableError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        frame, source_label = load_frame(args.input, args.synthetic_size)
    except InputImageError as exc:
        print(str(exc), file=sys.stderr)
        return 5

    effective_half = bool(args.half and args.device.startswith("cuda"))
    if args.half and not effective_half:
        print(f"WARNING: --half bi bo qua vi --device={args.device} khong phai CUDA", file=sys.stderr)

    case = BenchmarkCase(
        model=str(model_path), device=args.device, imgsz=args.imgsz, half=effective_half,
        batch=args.batch, warmup=args.warmup, iterations=args.iterations,
    )
    result = run_benchmark_case(case, frame, conf=args.conf)
    result.input_source = source_label

    print(format_result(result))

    if args.json_output:
        write_json_output([result], args.json_output, args_dict=serializable_args(args, model_path))
        print(f"\nJSON_OUTPUT: {args.json_output}")

    if result.status == "PASS":
        return 0
    if result.status == "OOM":
        return 4
    return 5


if __name__ == "__main__":
    raise SystemExit(main())
