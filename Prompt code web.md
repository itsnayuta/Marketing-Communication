Bạn là Senior Software Architect + Senior Django Developer.

Hãy xây dựng cho tôi một ứng dụng nội bộ LOCAL-FIRST tên:

BAKA DATA CENTER

Mục tiêu của hệ thống:
Xây dựng Trung tâm dữ liệu đơn hàng cho một startup, chạy hoàn toàn local trên máy tính bằng Docker Compose.

KHÔNG xây dựng microservices.
KHÔNG xây SPA React riêng.
Ưu tiên đơn giản, dễ maintain, dữ liệu chính xác và dễ chuyển lên VPS sau này.

====================================================
1. TECHNOLOGY STACK
====================================================

Backend:
- Python 3.13
- Django 6.x
- Django ORM

Database:
- PostgreSQL

Frontend:
- Django Templates
- HTMX
- Bootstrap
- Chart.js

Data processing:
- Pandas
- OpenPyXL

Database driver:
- Psycopg 3

AI:
- OpenAI API
- API key thông qua environment variable
- Tuyệt đối không hard-code API key.

Runtime:
- Docker Compose

Các service tối thiểu:
- web
- db

Có thể thêm worker nếu cần xử lý import background.

====================================================
2. SYSTEM PRINCIPLES
====================================================

Thiết kế theo pipeline:

RAW DATA
→ MAPPING
→ VALIDATION
→ NORMALIZATION
→ DEDUPLICATION
→ PRODUCT MATCHING
→ FINANCIAL CALCULATION
→ COMMIT
→ DASHBOARD.

Không bao giờ sửa dữ liệu RAW.

Mọi dữ liệu sau chuẩn hóa phải có khả năng truy ngược về:
- import batch
- raw row.

AI chỉ được đề xuất.
AI không được tự động thay đổi canonical data nếu user chưa xác nhận.

====================================================
3. DATA SOURCES
====================================================

Hệ thống hỗ trợ đúng 5 platform:

TIKTOK
SHOPEE
FACEBOOK
ZALO
OTHER

Tạo bảng platforms và seed 5 platform này.

====================================================
4. DATABASE DESIGN
====================================================

Tạo tối thiểu các model:

Platform

ImportBatch
- platform
- original_filename
- file_path
- file_hash
- total_rows
- success_rows
- warning_rows
- error_rows
- duplicate_rows
- status
- started_at
- completed_at
- created_at

RawOrderRecord
- import_batch
- row_number
- raw_data JSONField
- processing_status
- error_messages JSONField
- warning_messages JSONField
- created_at

MappingProfile
- platform
- name
- version
- is_default

MappingRule
- profile
- source_column
- target_field
- transform_rule
- required
- default_value

Product
- internal_sku
- product_name
- variant_name
- default_cost
- is_active
- created_at
- updated_at

ProductAlias
- platform
- external_sku
- external_product_name
- product
- confidence
- mapping_source
- created_at

PlatformCustomer
- platform
- platform_user_id
- internal_customer_id
- first_order_at
- last_order_at
- total_orders
- total_quantity
- total_revenue

Order
- UUID primary key
- platform
- external_order_id
- platform_user_id
- shipping_id
- order_created_at
- paid_at
- completed_at
- order_status
- payment_status
- currency
- customer
- source_type
- import_batch
- data_quality_status
- created_at
- updated_at

Đặt UNIQUE constraint:
(platform, external_order_id)

OrderItem
- order
- external_item_id
- product
- external_sku
- product_name_snapshot
- variant_name_snapshot
- quantity
- unit_price
- original_unit_price
- seller_discount
- platform_discount
- gross_item_revenue
- unit_cost_snapshot
- total_cost

OrderFinancial
- OneToOne Order
- gross_revenue
- seller_discount
- platform_discount
- refund_amount
- net_revenue
- platform_fee
- affiliate_commission
- cost_of_goods
- shipping_cost_seller
- other_variable_cost
- allocated_ad_cost
- contribution_profit

DataQualityIssue
- import_batch
- raw_record
- order
- issue_type
- severity
- field_name
- current_value
- message
- status
- created_at
- resolved_at

Thiết kế thêm index hợp lý cho:
- platform + external_order_id
- order_created_at
- completed_at
- order_status
- product SKU
- platform_user_id
- shipping_id
- import_batch.

====================================================
5. FINANCIAL FORMULAS
====================================================

Net Revenue =
Gross Revenue - Refund Amount

Contribution Profit =
Net Revenue
- Platform Fee
- Affiliate Commission
- Cost Of Goods
- Shipping Cost Seller
- Allocated Ad Cost
- Other Variable Cost

Không dùng FLOAT cho tiền.

Sử dụng DecimalField.

Currency mặc định:
VND.

====================================================
6. IMPORT SYSTEM
====================================================

Xây Import Wizard gồm 5 bước.

STEP 1:
Chọn platform.

STEP 2:
Upload file CSV/XLSX.

STEP 3:
Column Mapping.

STEP 4:
Preview + Validation.

STEP 5:
Confirm Import.

Khi upload:

1. Validate file.
2. Calculate SHA256 file hash.
3. Create ImportBatch.
4. Save raw file.
5. Parse Excel/CSV.
6. Save every row into RawOrderRecord.
7. Apply mapping.
8. Validate data.
9. Normalize.
10. Detect duplicate.
11. Match products.
12. Calculate financial values.
13. Return preview.
14. User confirms.
15. Commit normalized records.

Không commit canonical Order trước khi preview hoàn thành.

====================================================
7. DUPLICATE HANDLING
====================================================

Order key:

platform + external_order_id

Order item key ưu tiên:

order + external_item_id

Nếu external_item_id không tồn tại:

order + external_sku + line_number.

Nếu duplicate:
- không tạo order mới;
- hiển thị duplicate;
- cho phép SKIP hoặc UPDATE;
- mặc định SKIP.

====================================================
8. DATA QUALITY
====================================================

ERROR nếu:
- platform missing
- order_id missing
- product missing
- quantity <= 0
- invalid revenue
- invalid date

WARNING nếu:
- shipping_id missing
- platform_user_id missing
- SKU not mapped
- cost = 0
- affiliate data missing.

Tạo màn hình Data Quality Center.

Cho phép filter:
- severity
- platform
- batch
- field
- resolved/unresolved.

====================================================
9. PRODUCT MAPPING
====================================================

Xây Product Master.

Một Product có thể có nhiều ProductAlias.

Ví dụ:

TikTok:
"BAKA Resistant Starch 500g"

Shopee:
"Tinh bột kháng BAKA..."

có thể cùng map về:

BAKA-01.

Nếu không match:
mark:
UNMAPPED.

Không tự tạo Product Master từ tên bên ngoài.

====================================================
10. AI MODULE
====================================================

AI phải optional.

Environment variables:

AI_ENABLED
OPENAI_API_KEY
OPENAI_MODEL

Không lưu OPENAI_API_KEY plaintext trong database.

Xây AI service abstraction.

AI use case 1:
Suggest column mapping.

Input:
- platform
- header names
- tối đa một số sample values đã loại bỏ PII.

Output bắt buộc structured JSON:
{
  "mappings": [
    {
      "source_column": "",
      "target_field": "",
      "confidence": 0.0,
      "reason": ""
    }
  ]
}

AI use case 2:
Suggest product mapping.

AI use case 3:
Explain data-quality anomalies.

AI use case 4:
Summarize import batch.

Không gửi cho AI nếu không cần:
- user id
- shipping id
- phone
- address
- customer name.

AI không được:
- delete order
- update financial data
- commit mapping
- run arbitrary SQL.

User phải confirm mapping suggestion.

====================================================
11. UI DESIGN
====================================================

Giao diện phải chuyên nghiệp như internal SaaS dashboard.

Không sử dụng giao diện Django Admin làm giao diện chính.

Django Admin chỉ dùng cho technical administration.

Thiết kế:
- responsive desktop-first
- clean
- modern
- light theme
- sidebar trái
- top navigation
- cards
- data tables
- whitespace tốt
- consistent typography
- CSS variables để sau này đổi brand color.

Sidebar:

BAKA DATA CENTER

TỔNG QUAN
- Dashboard

TRUNG TÂM DỮ LIỆU
- Đơn hàng
- Nhập dữ liệu
- Lịch sử nhập
- Chất lượng dữ liệu

DANH MỤC
- Sản phẩm
- Mapping sản phẩm
- Mapping cột

AI
- Trợ lý dữ liệu

HỆ THỐNG
- Cấu hình

====================================================
12. DASHBOARD
====================================================

Filter:
- date from
- date to
- platform

KPI cards:
- Orders
- Quantity
- Gross Revenue
- Net Revenue
- Platform Fee
- Affiliate Commission
- COGS
- Contribution Profit
- Data Quality Issues.

Chart:
- Revenue by day
- Quantity by day
- Revenue by platform
- Contribution profit by platform.

====================================================
13. ORDERS TABLE
====================================================

Columns:

Platform
Order ID
Date
User ID
Shipping ID
SKU
Product
Quantity
Gross Revenue
Net Revenue
Platform Fee
COGS
Affiliate Commission
Contribution Profit
Order Status
Data Quality Status

Features:
- global search
- filter platform
- filter date
- filter order status
- filter SKU
- filter data quality
- sorting
- server-side pagination
- rows per page
- sticky header
- export CSV
- export XLSX
- order detail page.

Use VND number formatting.

====================================================
14. ORDER DETAIL
====================================================

Page sections:

Order Header
Customer
Shipping
Products
Revenue
Costs
Profit
Data Quality
Source Import
Raw Data.

Never hide raw source information from admin.

====================================================
15. IMPORT HISTORY
====================================================

Table:

Date
Platform
Filename
Rows
Success
Warning
Error
Duplicate
Status
Processing Time

Click row opens batch detail.

Batch detail must display:
- summary
- failed rows
- warnings
- duplicate rows
- raw preview.

====================================================
16. SECURITY
====================================================

Use Django Authentication.

Require login.

Create basic roles:
ADMIN
VIEWER

CSRF enabled.

Do not expose PostgreSQL port publicly.

Do not hard-code secrets.

Use .env.

Create .env.example without secrets.

====================================================
17. LOCAL DEPLOYMENT
====================================================

Create Dockerfile.

Create docker-compose.yml.

Services:
web
db

Persistent PostgreSQL volume.

Persistent data/uploads volume.

Persistent backups directory.

System must run with:

docker compose up -d

Then:

http://localhost:8000

Provide commands:
- migrations
- createsuperuser
- seed platforms
- backup
- restore.

====================================================
18. TESTING
====================================================

Write tests for:

- order duplicate
- multi-item order
- mapping
- financial formulas
- invalid quantity
- invalid revenue
- product alias
- import duplicate
- order update
- AI disabled
- AI failure fallback.

Never make system operation depend on AI availability.

====================================================
19. DEMO DATA
====================================================

Create sample files for:

TikTok
Shopee
Facebook
Zalo
Other.

Generate at least 30 fake orders.

Include:
- normal order
- multiple item order
- affiliate order
- refunded order
- duplicate order
- missing SKU
- invalid row.

====================================================
20. README
====================================================

README must explain:

1. Installation
2. Docker setup
3. Environment variables
4. Start system
5. Create admin
6. Import data
7. Mapping
8. Product mapping
9. Backup
10. Restore
11. AI configuration
12. Troubleshooting.

====================================================
21. DEVELOPMENT ORDER
====================================================

Do not attempt everything simultaneously.

Build in this sequence:

PHASE 1
Project scaffold
Docker
PostgreSQL
Authentication

PHASE 2
Database models
Migrations
Admin

PHASE 3
Products
Platforms
Mapping

PHASE 4
Raw import
Import batches

PHASE 5
Normalization
Validation
Deduplication

PHASE 6
Orders UI
Order detail

PHASE 7
Dashboard

PHASE 8
AI assistance

PHASE 9
Testing
Demo data
README.

After every phase:
- run migrations
- run tests
- fix all errors before moving forward.

====================================================
22. DEFINITION OF DONE
====================================================

System is finished only when I can:

1. Run docker compose up -d.

2. Login at localhost.

3. Upload a TikTok/Shopee/Facebook/Zalo/Other XLSX or CSV.

4. Map source columns to canonical fields.

5. Preview data.

6. See warnings/errors/duplicates.

7. Confirm import.

8. View normalized orders.

9. View multi-item orders correctly.

10. See revenue, platform fee, COGS, affiliate and contribution profit.

11. Filter orders by platform/date/status.

12. Export data.

13. See data quality problems.

14. Map external products to internal products.

15. Use AI to suggest mapping if API key exists.

16. Continue using the entire application normally when AI is disabled.

17. Restart Docker without losing PostgreSQL data.

Do not leave placeholder code or TODO for core functions.

Before finishing:
- run all tests;
- run migrations;
- verify Docker build;
- seed demo data;
- verify every major page manually;
- report project structure and exact start commands.