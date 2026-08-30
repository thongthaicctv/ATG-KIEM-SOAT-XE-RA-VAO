"""tests/test_benchmark_yolo_models.py

Unit test cho scripts/benchmark_yolo_models.py. Cac test o day CHI kiem tra logic
thuan (percentile, capacity estimate, validate_model_path/validate_device, JSON
schema) va hanh vi OOM/khong-tu-tai-model bang fake/monkeypatch - KHONG chay GPU
benchmark that (khong warmup/iterations lon, khong doi hoi torch/ultralytics/CUDA
that su duoc cai). Muc tieu: nhanh, doc lap moi truong, an toan chay trong CI/sandbox.
"""
import json
from pathlib import Path

import pytest

from scripts.benchmark_yolo_models import (
    BenchmarkCase,
    BenchmarkResult,
    CudaUnavailableError,
    ModelNotFoundError,
    build_parser,
    estimate_cameras,
    main,
    percentiles,
    resolve_precision_kwargs,
    run_benchmark_case,
    serializable_args,
    validate_device,
    validate_model_path,
    write_json_output,
)


# N.1 - model .pt khong ton tai -> MODEL_NOT_FOUND -----------------------------

def test_missing_model_raises_model_not_found(tmp_path):
    missing = tmp_path / "does_not_exist.pt"
    with pytest.raises(ModelNotFoundError) as exc_info:
        validate_model_path(missing)
    assert "MODEL_NOT_FOUND" in str(exc_info.value)


def test_existing_model_path_is_accepted(tmp_path):
    model_file = tmp_path / "yolo11n.pt"
    model_file.write_bytes(b"fake-weights")
    assert validate_model_path(model_file) == model_file


# N.2 - xu ly device khong hop le / CUDA khong kha dung ------------------------

def test_validate_device_cuda_requested_but_unavailable_raises():
    with pytest.raises(CudaUnavailableError):
        validate_device("cuda:0", cuda_available=False)


def test_validate_device_cpu_never_raises_regardless_of_cuda():
    validate_device("cpu", cuda_available=False)
    validate_device("cpu", cuda_available=True)


def test_validate_device_cuda_available_does_not_raise():
    validate_device("cuda:0", cuda_available=True)


# N.3 - tinh percentile (avg/median/p95) ---------------------------------------

def test_percentiles_known_values():
    samples = [10.0, 20.0, 30.0, 40.0, 50.0]
    stats = percentiles(samples)
    assert stats["avg_ms"] == pytest.approx(30.0)
    assert stats["median_ms"] == pytest.approx(30.0)
    # nearest-rank: index = round(0.95 * (5-1)) = round(3.8) = 4 -> ordered[4] = 50.0
    assert stats["p95_ms"] == pytest.approx(50.0)


def test_percentiles_empty_samples_raises():
    with pytest.raises(ValueError):
        percentiles([])


# N.4 - cong thuc uoc luong so camera (INFERENCE_ONLY_ESTIMATE) ----------------

def test_estimate_cameras_floor_division():
    assert estimate_cameras(inference_fps=42.0, processing_fps=4.0) == 10
    assert estimate_cameras(inference_fps=19.9, processing_fps=5.0) == 3
    assert estimate_cameras(inference_fps=0.0, processing_fps=4.0) == 0


def test_estimate_cameras_invalid_processing_fps_raises():
    with pytest.raises(ValueError):
        estimate_cameras(inference_fps=30.0, processing_fps=0)


# N.5 - JSON output schema ------------------------------------------------------

def test_benchmark_result_to_json_dict_schema():
    result = BenchmarkResult(
        model="models/yolo11n.pt", device="cuda:0", imgsz=640, half=True, batch=1,
        status="PASS", avg_ms=10.0, fps=100.0,
    )
    payload = result.to_json_dict()
    assert payload["inference_only_estimate"] is True
    for key in ("model", "device", "imgsz", "half", "batch", "status", "avg_ms", "fps"):
        assert key in payload


def test_write_json_output_round_trip(tmp_path):
    result = BenchmarkResult(
        model="models/yolo11n.pt", device="cpu", imgsz=640, half=False, batch=1, status="PASS",
    )
    out_path = tmp_path / "reports" / "benchmark" / "result.json"
    write_json_output([result], out_path, args_dict={"model": "models/yolo11n.pt"})
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["tool"] == "benchmark_yolo_models"
    assert "generated_at_utc" in payload
    assert payload["results"][0]["model"] == "models/yolo11n.pt"


# N.6 - khong bao gio tu dong tai model (ultralytics khong duoc import khi thieu model)

def test_missing_model_does_not_import_ultralytics(tmp_path, monkeypatch):
    missing = tmp_path / "yolo11n.pt"
    real_import = __import__

    def _guarded_import(name, *args, **kwargs):
        if name == "ultralytics" or name.startswith("ultralytics."):
            raise AssertionError("ultralytics khong duoc phep import khi model file chua ton tai")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _guarded_import)
    exit_code = main(["--model", str(missing)])
    assert exit_code == 1


# N.7 - duong dan CUDA-only phai co guard ro rang -------------------------------

def test_cuda_only_path_has_explicit_guard_no_silent_cpu_fallback():
    with pytest.raises(CudaUnavailableError):
        validate_device("cuda:0", cuda_available=False)


# N.8 - dinh dang ket qua khi OOM (mo phong bang monkeypatch, khong can GPU that)

class _FakeOutOfMemoryError(RuntimeError):
    pass


class _FakeCuda:
    def __init__(self):
        self.OutOfMemoryError = _FakeOutOfMemoryError
        self.empty_cache_calls = 0
        self.reset_peak_calls = 0

    def empty_cache(self):
        self.empty_cache_calls += 1

    def reset_peak_memory_stats(self):
        self.reset_peak_calls += 1

    def synchronize(self):
        pass

    def memory_allocated(self, device=0):
        return 0

    def memory_reserved(self, device=0):
        return 0

    def max_memory_allocated(self, device=0):
        return 0

    def get_device_name(self, device=0):
        return "FakeGPU"


class _FakeTorchModule:
    def __init__(self):
        self.cuda = _FakeCuda()


class _FakeModelOOM:
    def predict(self, sources, **kwargs):
        raise _FakeOutOfMemoryError("CUDA out of memory.")


class _FakeModelOK:
    def predict(self, sources, **kwargs):
        return None


def test_run_benchmark_case_oom_is_caught_and_reported_not_crashed():
    fake_torch = _FakeTorchModule()
    case = BenchmarkCase(
        model="models/yolo11n.pt", device="cuda:0", imgsz=640, half=True, batch=1, warmup=1, iterations=1,
    )
    result = run_benchmark_case(
        case, frame=object(), model_loader=lambda _path: _FakeModelOOM(), torch_module=fake_torch,
    )
    assert result.status == "OOM"
    assert result.error is not None and "OOM" in result.error
    assert "yolo11n.pt" in result.error
    # phai giai phong CUDA cache sau OOM, khong duoc de tien trinh crash
    assert fake_torch.cuda.empty_cache_calls >= 1


def test_run_benchmark_case_pass_with_fake_model_and_cuda():
    fake_torch = _FakeTorchModule()
    case = BenchmarkCase(
        model="models/yolo11n.pt", device="cuda:0", imgsz=640, half=True, batch=1, warmup=2, iterations=3,
    )
    result = run_benchmark_case(
        case, frame=object(), model_loader=lambda _path: _FakeModelOK(), torch_module=fake_torch,
    )
    assert result.status == "PASS"
    assert result.avg_ms is not None
    assert result.fps is not None
    assert result.est_cameras_4fps is not None
    assert result.est_cameras_5fps is not None
    assert result.cuda_device_name == "FakeGPU"


def test_run_benchmark_case_cpu_path_skips_cuda_calls():
    # device="cpu" khong bao gio cham vao torch.cuda.*; truyen mot object() "tro"
    # lam torch_module de test nay khong phu thuoc torch that duoc cai trong moi truong.
    case = BenchmarkCase(
        model="models/yolo11n.pt", device="cpu", imgsz=640, half=False, batch=1, warmup=1, iterations=2,
    )
    result = run_benchmark_case(
        case, frame=object(), model_loader=lambda _path: _FakeModelOK(), torch_module=object(),
    )
    assert result.status == "PASS"
    assert result.vram_allocated_mb is None
    assert result.vram_peak_allocated_mb is None


# ===========================================================================
# PHASE 3.1 - regression test cho 2 bug phat hien khi chay that tren Windows:
# (1) TypeError: Object of type WindowsPath is not JSON serializable
# (2) --half dung API 'half=' da deprecate (Ultralytics 8.4.121), gay warning +
#     console I/O lot vao vung do thoi gian moi iteration -> lam AVG_MS/FPS sai lech.
# ===========================================================================

# --- (2) precision API: quantize= thay vi half= (khong deprecate) -------------

def test_resolve_precision_kwargs_fp16_uses_quantize_not_half():
    # FP16 phai dung 'quantize=16' - KHONG dung 'half=True' (da bi Ultralytics 8.4.121
    # deprecate: xem _handle_deprecation() trong .venv/Lib/site-packages/ultralytics/
    # cfg/__init__.py - moi lan predict() tai su dung predictor deu chay lai
    # get_cfg()/_handle_deprecation(), nen 'half=True' se log warning MOI ITERATION,
    # rot vao vung do thoi gian cua benchmark).
    kwargs = resolve_precision_kwargs(True)
    assert kwargs == {"quantize": 16}
    assert "half" not in kwargs


def test_resolve_precision_kwargs_fp32_adds_no_precision_override():
    kwargs = resolve_precision_kwargs(False)
    assert kwargs == {}
    assert "half" not in kwargs
    assert "quantize" not in kwargs


def test_run_benchmark_case_records_precision_api_field():
    fake_torch = _FakeTorchModule()
    case_half = BenchmarkCase(
        model="models/yolo11n.pt", device="cuda:0", imgsz=640, half=True, batch=1, warmup=1, iterations=1,
    )
    result_half = run_benchmark_case(
        case_half, frame=object(), model_loader=lambda _p: _FakeModelOK(), torch_module=fake_torch,
    )
    assert result_half.precision_api == "quantize=16(fp16)"

    case_fp32 = BenchmarkCase(
        model="models/yolo11n.pt", device="cpu", imgsz=640, half=False, batch=1, warmup=1, iterations=1,
    )
    result_fp32 = run_benchmark_case(
        case_fp32, frame=object(), model_loader=lambda _p: _FakeModelOK(), torch_module=object(),
    )
    assert result_fp32.precision_api == "quantize=none(fp32)"


# --- (1) WindowsPath JSON serialization bug -----------------------------------

def test_serializable_args_converts_path_fields_to_str(tmp_path):
    model_file = tmp_path / "yolo11n.pt"
    model_file.write_bytes(b"fake-weights")
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    json_out = tmp_path / "out" / "result.json"

    args = build_parser().parse_args(
        ["--model", str(model_file), "--input", str(input_dir), "--json-output", str(json_out)]
    )
    # args.input / args.json_output la pathlib.Path (WindowsPath tren Windows) - day chinh
    # la nguon goc bug "Object of type WindowsPath is not JSON serializable" khi truoc day
    # main() truyen thang vars(args) vao write_json_output() ma khong xu ly 2 truong nay.
    assert isinstance(args.input, Path)
    assert isinstance(args.json_output, Path)

    safe = serializable_args(args, model_file)
    for key in ("model", "input", "json_output"):
        assert not isinstance(safe[key], Path), f"{key} van con la Path object sau serializable_args()"
    assert safe["input"] == str(input_dir)
    assert safe["json_output"] == str(json_out)
    assert safe["model"] == str(model_file)
    json.dumps(safe)  # phai khong nem TypeError


def test_serializable_args_missing_input_and_json_output_stay_none(tmp_path):
    model_file = tmp_path / "yolo11n.pt"
    model_file.write_bytes(b"fake-weights")
    args = build_parser().parse_args(["--model", str(model_file)])
    safe = serializable_args(args, model_file)
    assert safe["input"] is None
    assert safe["json_output"] is None
    json.dumps(safe)


def test_write_json_output_full_round_trip_with_real_parsed_args(tmp_path):
    model_file = tmp_path / "yolo11n.pt"
    model_file.write_bytes(b"fake-weights")
    out_path = tmp_path / "reports" / "benchmark" / "yolo11n_640_fp16.json"

    args = build_parser().parse_args(
        ["--model", str(model_file), "--half", "--json-output", str(out_path)]
    )
    result = BenchmarkResult(
        model=str(model_file), device="cuda:0", imgsz=640, half=True, batch=1,
        status="PASS", precision_api="quantize=16(fp16)", avg_ms=15.0, fps=66.0,
    )
    # day la duong ma truoc day nem TypeError tren Windows khi args_dict con chua Path.
    write_json_output([result], out_path, args_dict=serializable_args(args, model_file))

    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded["results"][0]["precision_api"] == "quantize=16(fp16)"
    assert isinstance(loaded["args"]["model"], str)
    assert isinstance(loaded["args"]["json_output"], str)


# --- schema: ket qua chi chua JSON primitive (khong Path/numpy/torch type) ----

def _assert_only_json_primitives(value, path="root"):
    if value is None or isinstance(value, (str, int, float, bool)):
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            _assert_only_json_primitives(item, f"{path}[{i}]")
        return
    if isinstance(value, dict):
        for k, v in value.items():
            assert isinstance(k, str), f"{path}: JSON key {k!r} khong phai str"
            _assert_only_json_primitives(v, f"{path}.{k}")
        return
    raise AssertionError(f"{path}: gia tri {value!r} (type={type(value).__name__}) khong phai JSON primitive")


def test_benchmark_result_schema_is_all_json_primitives_recursive():
    result = BenchmarkResult(
        model="models/yolo11n.pt", device="cuda:0", imgsz=640, half=True, batch=1,
        status="PASS", precision_api="quantize=16(fp16)", input_source="file:x.jpg",
        load_ms=100.0, avg_ms=15.0, median_ms=14.0, p95_ms=20.0, fps=66.0,
        vram_allocated_mb=50.0, vram_reserved_mb=60.0, vram_peak_allocated_mb=62.0,
        cpu_rss_mb=200.0, cuda_device_name="NVIDIA T600", est_cameras_4fps=16,
        est_cameras_5fps=13, warmup=20, iterations=200, error=None,
    )
    payload = result.to_json_dict()
    _assert_only_json_primitives(payload)
    json.dumps(payload)  # phai khong nem exception
