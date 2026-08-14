# BAKA Data Center

BAKA Data Center là ứng dụng nội bộ local-first để nhập, chuẩn hóa, kiểm tra và phân tích dữ liệu đơn hàng từ TikTok, Shopee, Facebook, Zalo và các nguồn khác. Ứng dụng là một Django monolith, render giao diện bằng Django Templates, dùng PostgreSQL làm dữ liệu chuẩn và giữ nguyên mọi RAW row để truy vết. Tabler UI, Tabler Icons, HTMX và Chart.js đã được vendored nên giao diện không phụ thuộc CDN khi chạy local.

## 1. Cài đặt

Yêu cầu khuyến nghị:

- Docker Desktop có Docker Compose v2.
- Cổng `8000` chưa bị ứng dụng khác sử dụng.
- Ít nhất 2 GB RAM trống.

Tạo file môi trường:

```powershell
Copy-Item .env.example .env
```

Thay `DJANGO_SECRET_KEY` và `POSTGRES_PASSWORD` trong `.env`. Không commit `.env`.

## 2. Docker setup

Build và khởi động:

```powershell
docker compose up -d --build
docker compose ps
```

Docker Compose tạo hai service:

- `web`: Python 3.13, Django 6 và Gunicorn tại `http://localhost:8000`.
- `db`: PostgreSQL 17 trong mạng Docker nội bộ; không publish cổng PostgreSQL ra máy host.

Hai named volume giữ PostgreSQL và file upload qua các lần restart. Thư mục `backups/` được mount riêng để backup có thể lấy trực tiếp từ host.

## 3. Environment variables

| Biến | Bắt buộc | Ý nghĩa |
|---|---:|---|
| `DJANGO_SECRET_KEY` | Có | Secret dài, ngẫu nhiên |
| `DJANGO_DEBUG` | Có | Đặt `false` khi vận hành |
| `DJANGO_ALLOWED_HOSTS` | Có | Mặc định `localhost,127.0.0.1` |
| `CSRF_TRUSTED_ORIGINS` | Có | Mặc định `http://localhost:8000` |
| `POSTGRES_DB` | Có | Tên database |
| `POSTGRES_USER` | Có | User PostgreSQL |
| `POSTGRES_PASSWORD` | Có | Mật khẩu PostgreSQL |
| `AI_ENABLED` | Không | `true` để bật AI |
| `OPENAI_API_KEY` | Không | Chỉ lưu trong `.env`, không lưu database |
| `OPENAI_MODEL` | Không | Model dùng cho structured suggestion |

`USE_SQLITE=1` chỉ dành cho test nhanh trong môi trường phát triển không có Docker; runtime chính luôn dùng PostgreSQL.

## 4. Khởi động hệ thống

Entrypoint tự chạy migration, seed 5 platform/roles và collect static. Xem log:

```powershell
docker compose logs -f web
```

Nếu cần chạy lệnh thủ công:

```powershell
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_platforms
```

Sau đó mở `http://localhost:8000`.

## 5. Tạo admin

```powershell
docker compose exec web python manage.py createsuperuser
```

Superuser có quyền giao diện nghiệp vụ và Django Admin. Hai group được seed sẵn:

- `ADMIN`: xem và thay đổi dữ liệu nghiệp vụ.
- `VIEWER`: chỉ xem.

Gán group tại `/admin/` nếu tạo user không phải superuser.

## 6. Nhập dữ liệu

Vào **Nhập dữ liệu** và thực hiện 5 bước:

1. Chọn một trong 5 platform.
2. Tải CSV/XLSX tối đa 25 MB và 100.000 dòng.
3. Ánh xạ cột nguồn sang canonical fields.
4. Xem preview, lỗi, cảnh báo và duplicate.
5. Chọn `SKIP` (mặc định) hoặc `UPDATE`, rồi xác nhận.

Hệ thống tính SHA256, lưu file nguồn và từng dòng vào `RawOrderRecord`. Preview không tạo `Order`; chỉ bước xác nhận mới commit. Dòng lỗi không được commit.

## 7. Column mapping

Ở bước 3 có thể lưu mapping thành profile mặc định theo platform. Profile có version; mỗi lần lưu cùng tên sẽ tạo version mới. Gợi ý AI hoặc local chỉ điền form, không tự xác nhận.

Các trường bắt buộc là mã đơn, ngày tạo, tên sản phẩm, số lượng và doanh thu gộp.

## 8. Product mapping

Tạo sản phẩm chuẩn tại **Sản phẩm**, sau đó vào **Mapping sản phẩm** để nối external SKU/tên ngoài với internal SKU. Một Product có thể có nhiều alias theo platform. SKU chưa map được đánh dấu `UNMAPPED`; hệ thống không tự tạo Product Master.

## 9. Backup

Backup PostgreSQL dạng custom dump:

```powershell
.\scripts.ps1 -Action backup
```

File được tạo trong `backups/`. Có thể dùng lệnh tương đương:

```powershell
docker compose exec -T db pg_dump -U baka -d baka -Fc -f /backups/baka-manual.dump
```

Nếu đã đổi user/database trong `.env`, thay `baka` trong lệnh hoặc điều chỉnh script tương ứng.

## 10. Restore

Đặt file dump trong `backups/`, rồi chạy:

```powershell
.\scripts.ps1 -Action restore -File .\backups\baka-YYYYMMDD-HHMMSS.dump
```

Restore dùng `--clean --if-exists` và có thể ghi đè database hiện tại. Luôn backup database hiện tại trước khi restore.

## 11. Cấu hình AI

AI là tùy chọn. Để bật, sửa `.env`:

```dotenv
AI_ENABLED=true
OPENAI_API_KEY=your-key
OPENAI_MODEL=gpt-5-mini
```

Sau đó:

```powershell
docker compose up -d --force-recreate web
```

AI chỉ nhận payload đã loại PII và trả structured JSON cho column mapping, product mapping, giải thích anomaly và tóm tắt batch. Mọi kết quả chỉ là đề xuất. Khi AI tắt, thiếu key, timeout hoặc lỗi API, ứng dụng dùng xử lý cục bộ và toàn bộ chức năng import vẫn hoạt động.

## 12. Demo data và kiểm thử

Thư mục `sample_data/` có 5 CSV với tổng 30 đơn chuẩn hóa và các ca multi-item, affiliate, refund, duplicate, thiếu SKU và dòng lỗi. Seed idempotent:

```powershell
docker compose exec web python manage.py seed_demo
docker compose exec web python manage.py test
```

Chạy bằng `.venv` trên Windows khi chưa có Docker:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:USE_SQLITE='1'
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py runserver
```

## Troubleshooting

- **`db` chưa healthy:** chạy `docker compose logs db`, kiểm tra `POSTGRES_PASSWORD` trong `.env`.
- **Không đăng nhập được:** tạo superuser bằng command ở mục 5.
- **File CSV lỗi encoding:** lưu CSV UTF-8/UTF-8 BOM; XLSX là lựa chọn ổn định hơn.
- **Static file chưa cập nhật:** chạy `docker compose exec web python manage.py collectstatic --noinput` rồi restart `web`.
- **Port 8000 bận:** đổi mapping port thành `8001:8000` và truy cập `http://localhost:8001`.
- **AI không hoạt động:** kiểm tra đủ `AI_ENABLED=true`, `OPENAI_API_KEY` và restart container. Import vẫn hoạt động nhờ fallback.

## Cấu trúc dự án

```text
baka/                    Django settings, URLs, WSGI
core/                    Models, views, forms, admin, tests
core/services/           Import pipeline, financial formulas, AI abstraction
core/management/commands Seed platforms/roles và demo data
templates/               Giao diện server-rendered
static/                  CSS và JavaScript dashboard
sample_data/             5 file CSV demo
data/                    Persistent uploads khi phát triển
backups/                 PostgreSQL dumps
Dockerfile
docker-compose.yml
```
