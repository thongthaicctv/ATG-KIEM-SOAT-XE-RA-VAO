# Parking Monitoring System - Phase 1

Ứng dụng Windows desktop bằng Python 3.10.11 để quản lý một vị trí đỗ cho mỗi camera RTSP. Phase 1 bao gồm cấu hình camera và polygon, phát hiện/tracking phương tiện, máy trạng thái vị trí, phiên đỗ, ảnh sự kiện, lịch sử và phục hồi sau khi khởi động lại.

## Phạm vi và nguyên tắc

- Mỗi camera có đúng một mã vị trí và tối đa một polygon chuẩn hóa 0-1.
- Xe phải ổn định trong polygon đủ `parking_confirm_seconds` mới tạo phiên.
- `session_code` độc lập với `track_id`; một phiên có thể liên kết nhiều track.
- Mất track ngắn hạn không đóng phiên. Camera offline giữ nguyên phiên đang hoạt động.
- Chỉ đóng phiên khi vị trí trống liên tục đủ `exit_confirm_seconds`.
- Không ghi video liên tục; chỉ lưu `enter.jpg`, `parked.jpg`, `exit.jpg`.
- Phase 1 không có OCR, danh sách xe đăng ký, phát hiện đỗ sai quy cách hoặc xuất Excel.

## Kiến trúc

```text
app/
  core/       cấu hình, đường dẫn, hằng số, logging
  database/   SQLAlchemy models, session, repository, migration
  services/   camera worker/manager, detector, tracker, polygon, state, session, snapshot
  ui/         cửa sổ chính, form camera, polygon editor, monitor, event log
  utils/      geometry, ảnh, thời gian, sinh mã
tests/        unit test logic độc lập camera/model thật
data/         SQLite database
logs/         log xoay vòng
snapshots/    ảnh sự kiện
config/       cấu hình triển khai bổ sung
```

Mỗi camera chạy trên một `QThread`. Worker đọc RTSP, bỏ qua frame theo FPS xử lý và không tích lũy queue. Detector và tracker tuân theo interface riêng để có thể thay model hoặc ByteTrack mà không đổi máy trạng thái.

## Cài đặt trên Windows

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Detector YOLO mặc định dùng `models/yolo11n.pt`. Để cài AI hoặc thay model:

```powershell
python -m pip install -r requirements-ai.txt
$env:PARKING_DETECTOR_MODEL = "D:\models\custom.pt"
```

Nếu file model mặc định không tồn tại và chưa đặt `PARKING_DETECTOR_MODEL`, ứng dụng dùng `NullDetector`; UI, camera, polygon và logic vẫn chạy nhưng không sinh detection. Model phải nhận các lớp COCO `car`, `truck`, `bus`; xe máy chỉ bật bằng cấu hình mã nguồn `enable_motorcycles` trong Phase 1.

## Chạy ứng dụng và test

```powershell
python run_app.py
python -m pytest -q
```

## Sử dụng

1. Mở trang **Camera**, chọn **Thêm** và nhập mã camera, tên, mã vị trí, RTSP URL cùng các ngưỡng.
2. Chọn camera và **Kiểm tra RTSP**.
3. Chọn **Vẽ polygon**, click để thêm điểm, kéo điểm để sửa, sau đó lưu. Polygon cần ít nhất ba điểm, có diện tích và không tự cắt.
4. Trang **Giám sát** hiển thị `CAMERA_OFFLINE`, `UNKNOWN`, `EMPTY`, `VEHICLE_CANDIDATE`, `OCCUPIED` hoặc `LEAVING`.
5. Trang **Lịch sử phiên đỗ** hiển thị thời gian vào, xác nhận đỗ, rời và thời lượng.

Trang Giám sát có ảnh thu nhỏ cập nhật khoảng 2 FPS. Nút **Mở preview** trên trang Camera hoặc trên thẻ camera mở luồng lớn có polygon, bounding box và track ID. Ứng dụng ưu tiên FFmpeg/TCP để đọc ổn định camera HEVC; máy chạy cần có `ffmpeg` trong `PATH`.

RTSP URL có mật khẩu được che trên bảng và không được ghi đầy đủ vào log.

## Máy trạng thái

```text
CAMERA_OFFLINE -> UNKNOWN -> EMPTY -> VEHICLE_CANDIDATE -> OCCUPIED -> LEAVING -> EMPTY
                         \                         ^          |
                          \------------------------|----------/
```

- Reconnect luôn vào `UNKNOWN` và chờ frame ổn định.
- Phiên ACTIVE từ lần chạy trước được giữ. Khi thấy xe, track mới được ghép vào phiên cũ và ghi `SYSTEM_RECOVERY`.
- Nếu xe quay lại trong lúc `LEAVING`, trạng thái trở về `OCCUPIED`.

## Dữ liệu vận hành

- Database: `data/parking.db`
- Log: `logs/parking_monitor.log` (5 MB/file, giữ 5 bản)
- Snapshot: `snapshots/YYYY-MM-DD/CAMERA_CODE/SESSION_CODE/{enter,parked,exit}.jpg`

Có thể đổi database bằng biến môi trường `PARKING_DATABASE_URL` và thư mục ảnh bằng `PARKING_SNAPSHOT_DIR`. Repository tách khỏi UI/nghiệp vụ để thuận lợi chuyển sang MariaDB ở phase sau.

## Kiểm thử Phase 1

Test hiện có bao phủ: điểm trong/ngoài polygon, polygon lỗi/tự cắt, tỷ lệ giao bbox, tọa độ chuẩn hóa, chọn xe chính, xe đi qua nhanh, xác nhận đỗ, mất track ngắn, quay lại trước timeout, rời đủ timeout, camera offline, phục hồi, liên kết track mới, duy nhất một phiên ACTIVE, mã phiên và che mật khẩu RTSP.

## Phase 1.1 - Chẩn đoán chuỗi AI

- Mặc định chấp nhận `car`, `motorcycle`, `bus`, `truck`; class name lấy trực tiếp từ `model.names`, không hard-code class ID.
- Camera có cấu hình riêng cho confidence, bật xe máy, ngưỡng overlap và AI debug overlay.
- Debug overlay hiển thị bbox, class, confidence, track ID, bottom-center anchor, overlap, inside polygon, primary vehicle, state và timer candidate/leaving.
- Card giám sát hiển thị raw detections, vehicle detections, số xe trong polygon, inference milliseconds, FPS AI thực tế và tracker status.
- Detector lỗi hiển thị `LỖI DETECTOR`; không giả vờ AI vẫn hoạt động.
- Xe có sẵn khi khởi động tạo session với `event_source=SYSTEM_RECOVERY` sau thời gian xác nhận.
- Preview 5 FPS tách khỏi inference nên vẫn mượt khi YOLO chạy CPU chậm.

Thiết lập kiểm tra khuyến nghị: confidence `0.30`, overlap `0.20`, xác nhận đỗ `5 giây`, xác nhận rời `2 giây`, giữ track mất `3 giây`.

## Phase 1.2 - Ổn định Track ID

- Mỗi `CameraWorker` tạo đúng một tracker và giữ tracker qua các inference cycle/reconnect RTSP.
- Tracker ghép detection theo class, IoU và khoảng cách tương đối với kích thước bbox thay vì chỉ dùng khoảng cách pixel cố định.
- Track buffer tự tính theo FPS cấu hình và thời gian giữ track, giới hạn 8-15 inference frames.
- Detection rỗng vẫn gọi `tracker.update([])` để tăng `time_since_update`; track chỉ bị xóa sau khi vượt buffer.
- Overlay hiển thị `track age` và `time_since_update`; log telemetry tracker được ghi mỗi 10 inference frame.
- Nếu tracker buộc phải cấp ID mới nhưng vị trí vẫn `OCCUPIED`, ID mới được thêm vào `vehicle_track_links`; session hiện tại được giữ và không phát sinh `PARK_START` mới.

## Phase 1.2.1 - Timezone, duration và session stability

- Database lưu UTC; datetime cũ không có timezone được xem là UTC.
- UI chuyển thời gian sang `Asia/Ho_Chi_Minh` qua helper tập trung, không cộng cứng 7 giờ.
- Session code dùng ngày địa phương Việt Nam, kể cả thời điểm UTC gần nửa đêm.
- Mọi nhánh kết thúc sử dụng `complete_session()`, tính duration từ `parked_at` tới `left_at` trước khi commit `COMPLETED`.
- `scripts/repair_session_durations.py` sửa các bản ghi cũ có duration bằng 0/null.
- Track buffer dùng `ceil(processing_fps × track_lost_grace_seconds)`; cấu hình 8 FPS × 3 giây cho buffer 24 frame.
- Telemetry detector/tracker mặc định ghi mỗi 30 giây, chỉ khi debug overlay bật, và không xuất hiện trong log sự kiện trên UI.

## Frame pipeline và độ trễ

```text
FFmpeg RTSP reader
  ├─ latest-frame queue (maxsize=1) → AI worker → detector → tracker → state/session
  └─ latest-preview mailbox          → UI QTimer 5 FPS → QImage/QPixmap
```

- AI nhận frame capture gốc, không đọc ảnh từ widget hoặc QPixmap.
- Cả queue AI và mailbox preview đều ghi đè dữ liệu cũ; không có hàng đợi frame tích lũy.
- Nếu UI bận, QTimer bị trễ nhưng mailbox vẫn chỉ giữ preview mới nhất; AI worker tiếp tục độc lập.
- Telemetry gồm capture/inference/display timestamp, AI/display age, số frame capture/preview bị bỏ và queue size.
- Overlay báo `FRAME_DELAY` nếu AI frame age vượt 1500 ms.
- Parking state sử dụng monotonic clock cho candidate, track-lost và leaving timer; thay đổi đồng hồ hệ thống không làm sai session.

## Detection miss grace và presence filter

- `detection_miss_grace_seconds` mặc định 5 giây: một inference `raw=0` không hủy Candidate.
- Candidate gắn với vị trí/loại xe, không gắn tuyệt đối với Track ID. Track mới cùng loại trong polygon tiếp tục candidate timer cũ.
- Presence filter giữ lịch sử inference 5 giây và yêu cầu tỷ lệ hiện diện tối thiểu 0.40 trước khi chuyển OCCUPIED.
- OCCUPIED giữ session qua detection miss ngắn hạn; chỉ chuyển LEAVING sau grace, rồi áp dụng `exit_confirm_seconds` độc lập.
- Detector hỗ trợ `detector_image_size` theo camera. Camera `hik` dùng confidence 0.20 và `imgsz=960`.
- Tùy chọn crop ROI lấy bounding rectangle polygon, mở rộng 10%; bbox detection được cộng offset về frame gốc trước tracker/polygon/snapshot.

## Giới hạn kỹ thuật

- Tracker mặc định là centroid tracker gọn nhẹ; triển khai thực tế nên thay bằng ByteTrack cho cảnh đông xe/che khuất dài.
- Ảnh `enter.jpg` trong bản Phase 1 dùng frame xác nhận đỗ nếu chưa có bộ đệm frame ứng viên.
- Kiểm thử tích hợp cần RTSP/model thật và soak test nhiều camera trên máy triển khai.
- SQLite phù hợp Phase 1 một máy; MariaDB, backup/restore và chính sách xóa ảnh thuộc phase ổn định sau.

## Các phase chưa triển khai

OCR/biển số (Phase 2), danh sách xe đăng ký (Phase 3), phát hiện sai quy cách (Phase 4), báo cáo Excel nâng cao (Phase 5), vận hành 24-72 giờ/backup (Phase 6), đóng gói EXE và tài liệu triển khai (Phase 7).
