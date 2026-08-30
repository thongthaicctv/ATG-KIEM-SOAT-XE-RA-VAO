# RTSP A/B Test Report — Phase 4 / Phase 4.1

Điền thủ công sau mỗi lần chạy `scripts/run_rtsp_ab_test.ps1`. Một hàng cho mỗi case
(A/B/C). Không tự động ghi bằng script — dữ liệu vận hành (log/console output) do script
in ra khi chạy; đánh giá nghiệp vụ (xe bị bỏ sót, session ảo, ...) do người vận hành quan
sát thủ công trong quá trình chạy.

**Phase 4.1**: mỗi case A/B/C chạy trên MỘT database RIÊNG (không còn dùng chung 1 file
như Phase 4 ban đầu — đó là lỗi đã sửa vì Case A chạy trước có thể để lại session/track
state làm B/C không còn xuất phát điểm giống nhau). Cả 3 database đều được tạo từ CÙNG 1
pristine snapshot (đọc production đúng 1 lần) nên dữ liệu camera/polygon/config ban đầu
giống hệt nhau, nhưng là 3 file SQLite vật lý tách biệt hoàn toàn.

## Thông tin chung

- Ngày chạy:
- Người vận hành:
- Pristine snapshot dùng chung làm nguồn cho cả 3 case: `data\runtime_ab\<timestamp>\base\pristine.db`
- Database RIÊNG của từng case (KHÔNG dùng chung):
  - Case A: `data\runtime_ab\<timestamp>\A\ab_test_A.db`
  - Case B: `data\runtime_ab\<timestamp>\B\ab_test_B.db`
  - Case C: `data\runtime_ab\<timestamp>\C\ab_test_C.db`
- 3 camera dùng cho cả 3 case (phải giống nhau tuyệt đối):

## Bảng kết quả kỹ thuật (lấy từ console output của script)

| Trường | Case A (yolo11n/640/FP32) | Case B (yolo11n/960/FP32) | Case C (yolo11s/640/FP32) |
|---|---|---|---|
| START_TIME | | | |
| END_TIME | | | |
| DURATION_SECONDS | | | |
| MODEL | yolo11n.pt | yolo11n.pt | yolo11s.pt |
| IMGSZ | 640 | 960 | 640 |
| PRECISION | FP32 | FP32 | FP32 |
| CAMERA_COUNT | 3 | 3 | 3 |
| DEVICE | cuda:0 | cuda:0 | cuda:0 |
| CUDA_DEVICE | | | |
| PROCESS_STATUS | | | |
| DB_TEST_PATH | | | |
| LOG_DIR | | | |

## Metrics tùy chọn (nếu thu thập được read-only từ log hiện có — không sửa RTSP pipeline để lấy thêm)

| Trường | Case A | Case B | Case C |
|---|---|---|---|
| Processing FPS thực tế | | | |
| Preview FPS thực tế | | | |
| Số lần reconnect DDNS | | | |
| Số lần camera offline | | | |
| Frame delay (ms) | | | |
| GPU memory (MB) | | | |
| GPU utilization (%) | | | |

## Đánh giá nghiệp vụ (quan sát thủ công — tool không tự kết luận)

| Tiêu chí | Case A | Case B | Case C |
|---|---|---|---|
| Xe thật phát hiện đúng | | | |
| Xe bị bỏ sót | | | |
| Đồ vật bị nhận nhầm thành xe | | | |
| Xe ngoài polygon bị tính | | | |
| Độ ổn định track (mất/giữ track) | | | |
| Session ảo (phiên đỗ không có xe thật) | | | |
| Ổn định khi reconnect DDNS | | | |

## Ghi chú tự do

(Bất kỳ quan sát nào khác — không giới hạn các mục trên.)

## Kết luận

**Không tự động kết luận model/imgsz nào "tốt hơn" chỉ từ bảng số liệu trên.** Quyết định
cuối cùng (YOLO11n 640 / YOLO11n 960 / YOLO11s 640) do người vận hành đưa ra, cân nhắc cả
hiệu năng (bảng trên) lẫn độ chính xác thực địa (bảng đánh giá nghiệp vụ) lẫn mức độ an
toàn VRAM margin trên NVIDIA T600 4GB.
