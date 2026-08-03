# Cấu hình máy và lộ trình triển khai

## Trạng thái các phase

- Phase 1, 1.1, 1.2 và 1.2.1: đã có mã nguồn và unit test cho camera, polygon, detector/tracker, state machine, session, timezone và frame pipeline.
- Phase 2: chưa triển khai OCR biển số.
- Phase 3: chưa triển khai danh sách xe đăng ký.
- Phase 4: chưa triển khai phát hiện đỗ sai quy cách.
- Phase 5: chưa triển khai báo cáo Excel nâng cao.
- Phase 6: mới có reconnect, worker độc lập, latest-frame queue, recovery và log xoay vòng; còn thiếu watchdog, backup/restore, retention và soak test 24–72 giờ.
- Phase 7: mới có cấu hình qua môi trường; còn thiếu đóng gói EXE, bộ cài và tài liệu nghiệm thu.

Không nên triển khai Phase 2–5 trước khi profile 10 camera vượt qua soak test Phase 6. Mọi chức năng OCR và vi phạm đều làm tăng tải AI đáng kể.

## Profile `debug_1cam`

Mục tiêu: máy phát triển hiện tại (i5-10400F, RAM 32 GB, NVIDIA T600 4 GB), một camera.

- Model: `models/yolo11n.pt`.
- AI: 4 FPS, `imgsz=640`, full precision, device tự chọn.
- Preview: 5 FPS; bật debug overlay.
- Giữ crop ROI polygon để giảm vùng suy luận.
- Chạy: `powershell -ExecutionPolicy Bypass -File config/debug-1cam.ps1`.

Profile giới hạn một camera đang chạy để kết quả debug không bị sai lệch bởi thiếu tài nguyên.

## Profile `production_10cam`

Mục tiêu: khoảng 10 camera trên máy triển khai riêng.

- Khuyến nghị tối thiểu: CPU 12–16 core, RAM 32–64 GB, NVIDIA RTX 4070 12 GB hoặc GPU tương đương, SSD NVMe tối thiểu 1 TB.
- Model mặc định: `models/yolo11s.pt`. Nếu dữ liệu thực tế chưa được kiểm chứng, chạy A/B với `yolo11n.pt`; chỉ nâng model khi độ chính xác tăng có ý nghĩa.
- AI: 5 FPS/camera, `imgsz=960`, CUDA FP16; preview 2 FPS; tắt debug overlay.
- Chạy: `powershell -ExecutionPolicy Bypass -File config/production-10cam.ps1`.

YOLO được dùng chung giữa các camera và có khóa suy luận để tránh gọi đồng thời không an toàn. Trước nghiệm thu cần đo FPS thực tế; nếu tổng tải không đạt 50 inference/giây, giảm FPS/image size hoặc chuyển sang TensorRT/batch inference.

## Điều kiện nghiệm thu máy mới

1. Chạy `python scripts/check_runtime.py` và không còn lỗi model/CUDA/profile.
2. Test lần lượt 1, 4 rồi 10 camera bằng RTSP thật.
3. Chạy liên tục 24 giờ trước, sau đó 72 giờ; ghi CPU, RAM, VRAM, inference latency, frame age và reconnect.
4. Không tăng RAM liên tục; không có `FRAME_DELAY` kéo dài; một camera lỗi không ảnh hưởng camera khác.
5. Đối chiếu thủ công các ca xe đi ngang, dừng ngắn, che khuất, reconnect và khởi động lại.
6. Chỉ sau khi đạt các mục trên mới khóa cấu hình production và triển khai Phase 2.
