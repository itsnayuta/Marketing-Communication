import hashlib
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
from django.db import transaction
from django.db.models import Count, Min, Max, Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.models import (
    DataQualityIssue,
    ImportBatch,
    MappingProfile,
    MappingRule,
    Order,
    OrderFinancial,
    OrderItem,
    PlatformCustomer,
    ProductAlias,
    RawOrderRecord,
)
from core.services.financials import ZERO, calculate_financials, decimal_value


CANONICAL_FIELDS = {
    "external_order_id": "Mã đơn hàng",
    "external_item_id": "Mã dòng sản phẩm",
    "order_created_at": "Ngày tạo đơn",
    "paid_at": "Ngày thanh toán",
    "completed_at": "Ngày hoàn tất",
    "platform_user_id": "User ID nền tảng",
    "shipping_id": "Mã vận đơn",
    "external_sku": "SKU ngoài",
    "product_name": "Tên sản phẩm",
    "variant_name": "Phân loại",
    "quantity": "Số lượng",
    "unit_price": "Đơn giá",
    "original_unit_price": "Đơn giá gốc",
    "seller_discount": "Giảm giá người bán",
    "platform_discount": "Giảm giá nền tảng",
    "gross_revenue": "Doanh thu gộp",
    "refund_amount": "Hoàn tiền",
    "platform_fee": "Phí nền tảng",
    "affiliate_commission": "Hoa hồng affiliate",
    "shipping_cost_seller": "Phí ship người bán",
    "other_variable_cost": "Chi phí biến đổi khác",
    "allocated_ad_cost": "Chi phí quảng cáo phân bổ",
    "order_status": "Trạng thái đơn",
    "payment_status": "Trạng thái thanh toán",
}
REQUIRED_FIELDS = {"external_order_id", "order_created_at", "product_name", "quantity", "gross_revenue"}
MONEY_FIELDS = {
    "unit_price", "original_unit_price", "seller_discount", "platform_discount", "gross_revenue",
    "refund_amount", "platform_fee", "affiliate_commission", "shipping_cost_seller",
    "other_variable_cost", "allocated_ad_cost",
}
DATE_FIELDS = {"order_created_at", "paid_at", "completed_at"}
PII_TOKENS = {"phone", "address", "customer", "name", "user", "shipping"}


def file_sha256(uploaded_file) -> str:
    digest = hashlib.sha256()
    for chunk in uploaded_file.chunks():
        digest.update(chunk)
    uploaded_file.seek(0)
    return digest.hexdigest()


def _json_value(value):
    if pd.isna(value):
        return ""
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    return str(value).strip()


def read_tabular(file_obj, filename: str) -> pd.DataFrame:
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        try:
            frame = pd.read_csv(file_obj, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        except UnicodeDecodeError:
            file_obj.seek(0)
            frame = pd.read_csv(file_obj, dtype=str, keep_default_na=False, encoding="utf-8")
    elif suffix == ".xlsx":
        frame = pd.read_excel(file_obj, dtype=str, keep_default_na=False, engine="openpyxl")
    else:
        raise ValueError("Định dạng tệp không được hỗ trợ.")
    frame.columns = [str(column).strip() for column in frame.columns]
    if not len(frame.columns) or frame.empty:
        raise ValueError("Tệp không chứa dòng dữ liệu nào.")
    if len(frame) > 100_000:
        raise ValueError("Tệp vượt quá giới hạn 100.000 dòng cho một batch.")
    return frame


def create_batch(platform, uploaded_file) -> ImportBatch:
    digest = file_sha256(uploaded_file)
    frame = read_tabular(uploaded_file, uploaded_file.name)
    uploaded_file.seek(0)
    with transaction.atomic():
        batch = ImportBatch.objects.create(
            platform=platform,
            original_filename=uploaded_file.name,
            file_path=uploaded_file,
            file_hash=digest,
            total_rows=len(frame),
            started_at=timezone.now(),
        )
        records = [
            RawOrderRecord(
                import_batch=batch,
                row_number=index + 2,
                raw_data={str(key): _json_value(value) for key, value in row.items()},
            )
            for index, row in frame.iterrows()
        ]
        RawOrderRecord.objects.bulk_create(records, batch_size=1000)
    return batch


def suggest_mapping_locally(columns) -> dict:
    aliases = {
        "external_order_id": ("order_id", "orderid", "ma_don", "mã đơn", "id đơn"),
        "external_item_id": ("item_id", "line_id", "id sản phẩm"),
        "order_created_at": ("order_date", "created_at", "ngày đặt", "ngay_dat"),
        "paid_at": ("paid_at", "payment_date", "ngày thanh toán"),
        "completed_at": ("completed_at", "complete_date", "ngày hoàn tất"),
        "platform_user_id": ("user_id", "buyer_id", "customer_id"),
        "shipping_id": ("shipping_id", "tracking_id", "mã vận đơn"),
        "external_sku": ("sku", "seller_sku", "external_sku"),
        "product_name": ("product_name", "item_name", "tên sản phẩm"),
        "variant_name": ("variant", "variation", "phân loại"),
        "quantity": ("quantity", "qty", "số lượng"),
        "unit_price": ("unit_price", "price", "đơn giá"),
        "gross_revenue": ("gross_revenue", "revenue", "amount", "doanh thu"),
        "refund_amount": ("refund", "refund_amount", "hoàn tiền"),
        "platform_fee": ("platform_fee", "phí nền tảng"),
        "affiliate_commission": ("affiliate", "affiliate_commission", "hoa hồng"),
        "order_status": ("order_status", "status", "trạng thái đơn"),
        "payment_status": ("payment_status", "trạng thái thanh toán"),
    }
    normalized = {str(column).lower().strip().replace("-", "_"): column for column in columns}
    result = {}
    for target, candidates in aliases.items():
        for candidate in (target, *candidates):
            key = candidate.lower().strip().replace("-", "_")
            if key in normalized:
                result[target] = normalized[key]
                break
    return result


def mapping_from_default_profile(platform, columns) -> dict:
    profile = MappingProfile.objects.filter(platform=platform, is_default=True).order_by("-version").first()
    if not profile:
        return suggest_mapping_locally(columns)
    available = set(columns)
    return {rule.target_field: rule.source_column for rule in profile.rules.all() if rule.source_column in available}


def save_mapping_profile(platform, name: str, mapping: dict):
    latest = MappingProfile.objects.filter(platform=platform, name=name).order_by("-version").first()
    version = (latest.version + 1) if latest else 1
    MappingProfile.objects.filter(platform=platform, is_default=True).update(is_default=False)
    profile = MappingProfile.objects.create(platform=platform, name=name or "Mapping import", version=version, is_default=True)
    MappingRule.objects.bulk_create([
        MappingRule(profile=profile, source_column=source, target_field=target, required=target in REQUIRED_FIELDS)
        for target, source in mapping.items()
    ])
    return profile


def _parse_date(value, field_name):
    if not value:
        return None
    parsed = parse_datetime(str(value))
    if not parsed:
        try:
            parsed = pd.to_datetime(value, dayfirst=False).to_pydatetime()
        except (ValueError, TypeError, OverflowError):
            raise ValueError(f"{field_name} không phải ngày hợp lệ")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _serialize_normalized(data):
    return {key: (value.isoformat() if isinstance(value, datetime) else str(value) if isinstance(value, Decimal) else value) for key, value in data.items()}


def normalize_record(raw: dict, mapping: dict, platform) -> tuple[dict, list[dict], list[dict]]:
    value = lambda target: raw.get(mapping.get(target, ""), "")
    normalized = {key: value(key).strip() if isinstance(value(key), str) else value(key) for key in CANONICAL_FIELDS}
    errors, warnings = [], []

    def issue(bucket, issue_type, field, message):
        bucket.append({"issue_type": issue_type, "field_name": field, "current_value": str(normalized.get(field, "")), "message": message})

    if not platform:
        issue(errors, "MISSING_REQUIRED", "platform", "Thiếu nền tảng.")
    for field in ("external_order_id", "product_name"):
        if not normalized.get(field):
            issue(errors, "MISSING_REQUIRED", field, f"Thiếu {CANONICAL_FIELDS[field].lower()}.")
    try:
        quantity_decimal = decimal_value(normalized.get("quantity"), field_name="quantity")
        if quantity_decimal != quantity_decimal.to_integral_value():
            raise ValueError
        quantity = int(quantity_decimal)
        if quantity <= 0:
            raise ValueError
        normalized["quantity"] = quantity
    except (ValueError, TypeError):
        issue(errors, "INVALID_QUANTITY", "quantity", "Số lượng phải là số nguyên lớn hơn 0.")
        normalized["quantity"] = 0
    gross_was_missing = normalized.get("gross_revenue") in (None, "")
    affiliate_was_missing = normalized.get("affiliate_commission") in (None, "")
    for field in MONEY_FIELDS:
        try:
            normalized[field] = decimal_value(normalized.get(field), field_name=field)
            if field == "gross_revenue" and (gross_was_missing or normalized[field] < ZERO):
                raise ValueError
        except ValueError:
            issue(errors, "INVALID_REVENUE" if field == "gross_revenue" else "INVALID_MONEY", field, f"{CANONICAL_FIELDS[field]} không hợp lệ.")
            normalized[field] = ZERO
    for field in DATE_FIELDS:
        try:
            normalized[field] = _parse_date(normalized.get(field), field)
            if field == "order_created_at" and not normalized[field]:
                raise ValueError
        except ValueError:
            issue(errors, "INVALID_DATE", field, f"{CANONICAL_FIELDS[field]} không hợp lệ.")
            normalized[field] = None
    if not normalized.get("shipping_id"):
        issue(warnings, "MISSING_OPTIONAL", "shipping_id", "Thiếu mã vận đơn.")
    if not normalized.get("platform_user_id"):
        issue(warnings, "MISSING_OPTIONAL", "platform_user_id", "Thiếu user ID nền tảng.")

    alias = None
    if normalized.get("external_sku"):
        alias = ProductAlias.objects.select_related("product").filter(platform=platform, external_sku=normalized["external_sku"]).first()
    if not alias and normalized.get("product_name"):
        alias = ProductAlias.objects.select_related("product").filter(platform=platform, external_product_name__iexact=normalized["product_name"]).first()
    normalized["product_id"] = alias.product_id if alias else None
    normalized["unit_cost"] = alias.product.default_cost if alias else ZERO
    if not alias:
        issue(warnings, "UNMAPPED_PRODUCT", "external_sku", "SKU chưa được map với Product Master.")
    elif alias.product.default_cost == ZERO:
        issue(warnings, "ZERO_COST", "unit_cost", "Giá vốn sản phẩm bằng 0.")
    if affiliate_was_missing:
        issue(warnings, "MISSING_AFFILIATE", "affiliate_commission", "Không có dữ liệu affiliate.")
    return normalized, errors, warnings


def preview_batch(batch: ImportBatch, mapping: dict) -> ImportBatch:
    batch.mapping_snapshot = mapping
    batch.status = ImportBatch.Status.PROCESSING
    batch.save(update_fields=["mapping_snapshot", "status"])
    DataQualityIssue.objects.filter(import_batch=batch).delete()
    normalized_rows = []
    order_ids = []
    for record in batch.raw_records.all():
        normalized, errors, warnings = normalize_record(record.raw_data, mapping, batch.platform)
        normalized_rows.append((record, normalized, errors, warnings))
        if normalized.get("external_order_id"):
            order_ids.append(normalized["external_order_id"])
    existing_ids = set(Order.objects.filter(platform=batch.platform, external_order_id__in=order_ids).values_list("external_order_id", flat=True))
    counts = defaultdict(int)
    seen_item_keys = set()
    quality_issues = []
    totals = defaultdict(int)
    for record, normalized, errors, warnings in normalized_rows:
        order_id = normalized.get("external_order_id")
        external_item_id = normalized.get("external_item_id")
        item_key = (order_id, "item", external_item_id) if external_item_id else (order_id, "fallback", normalized.get("external_sku"), record.row_number)
        duplicate = order_id in existing_ids or item_key in seen_item_keys
        seen_item_keys.add(item_key)
        if errors:
            status = RawOrderRecord.Status.ERROR
        elif duplicate:
            status = RawOrderRecord.Status.DUPLICATE
        elif warnings:
            status = RawOrderRecord.Status.WARNING
        else:
            status = RawOrderRecord.Status.VALID
        totals[status] += 1
        record.normalized_data = _serialize_normalized(normalized)
        record.processing_status = status
        record.error_messages = errors
        record.warning_messages = warnings
        record.save(update_fields=["normalized_data", "processing_status", "error_messages", "warning_messages"])
        for severity, issues in ((DataQualityIssue.Severity.ERROR, errors), (DataQualityIssue.Severity.WARNING, warnings)):
            quality_issues.extend(DataQualityIssue(
                import_batch=batch,
                raw_record=record,
                issue_type=item["issue_type"],
                severity=severity,
                field_name=item["field_name"],
                current_value=item["current_value"],
                message=item["message"],
            ) for item in issues)
    DataQualityIssue.objects.bulk_create(quality_issues, batch_size=1000)
    batch.success_rows = totals[RawOrderRecord.Status.VALID]
    batch.warning_rows = totals[RawOrderRecord.Status.WARNING]
    batch.error_rows = totals[RawOrderRecord.Status.ERROR]
    batch.duplicate_rows = totals[RawOrderRecord.Status.DUPLICATE]
    batch.status = ImportBatch.Status.PREVIEWED
    batch.save(update_fields=["success_rows", "warning_rows", "error_rows", "duplicate_rows", "status"])
    return batch


def _deserialize_row(data: dict) -> dict:
    result = dict(data)
    for field in MONEY_FIELDS | {"unit_cost"}:
        result[field] = decimal_value(result.get(field))
    for field in DATE_FIELDS:
        result[field] = _parse_date(result.get(field), field) if result.get(field) else None
    result["quantity"] = int(result.get("quantity") or 0)
    return result


def _customer_for(batch, first_row):
    user_id = first_row.get("platform_user_id")
    if not user_id:
        return None
    customer, _ = PlatformCustomer.objects.get_or_create(platform=batch.platform, platform_user_id=user_id)
    return customer


def _create_or_update_order(batch, rows, duplicate_action):
    first_record, first = rows[0]
    existing = Order.objects.filter(platform=batch.platform, external_order_id=first["external_order_id"]).first()
    if existing and duplicate_action == "SKIP":
        return None, 0, len(rows)
    customer = _customer_for(batch, first)
    values = {
        "platform_user_id": first.get("platform_user_id", ""),
        "shipping_id": first.get("shipping_id", ""),
        "order_created_at": first["order_created_at"],
        "paid_at": first.get("paid_at"),
        "completed_at": first.get("completed_at"),
        "order_status": first.get("order_status", ""),
        "payment_status": first.get("payment_status", ""),
        "customer": customer,
        "import_batch": batch,
        "data_quality_status": Order.Quality.WARNING if any(record.warning_messages for record, _ in rows) else Order.Quality.GOOD,
    }
    if existing:
        for field, value in values.items():
            setattr(existing, field, value)
        existing.save()
        existing.items.all().delete()
        order = existing
    else:
        order = Order.objects.create(platform=batch.platform, external_order_id=first["external_order_id"], **values)
    totals = defaultdict(lambda: ZERO)
    seen_external_items = set()
    committed_rows = skipped_rows = 0
    for line_number, (record, row) in enumerate(rows, 1):
        external_item_id = row.get("external_item_id", "")
        if external_item_id and external_item_id in seen_external_items:
            record.processing_status = RawOrderRecord.Status.DUPLICATE
            record.save(update_fields=["processing_status"])
            skipped_rows += 1
            continue
        if external_item_id:
            seen_external_items.add(external_item_id)
        quantity = row["quantity"]
        unit_cost = row.get("unit_cost", ZERO)
        gross = row.get("gross_revenue", ZERO)
        OrderItem.objects.create(
            order=order,
            external_item_id=external_item_id,
            line_number=line_number,
            product_id=row.get("product_id") or None,
            external_sku=row.get("external_sku", ""),
            product_name_snapshot=row.get("product_name", ""),
            variant_name_snapshot=row.get("variant_name", ""),
            quantity=quantity,
            unit_price=row.get("unit_price") or (gross / quantity if quantity else ZERO),
            original_unit_price=row.get("original_unit_price") or row.get("unit_price") or ZERO,
            seller_discount=row.get("seller_discount", ZERO),
            platform_discount=row.get("platform_discount", ZERO),
            gross_item_revenue=gross,
            unit_cost_snapshot=unit_cost,
            total_cost=unit_cost * quantity,
        )
        for field in MONEY_FIELDS:
            totals[field] += row.get(field, ZERO)
        totals["cost_of_goods"] += unit_cost * quantity
        record.processing_status = RawOrderRecord.Status.COMMITTED
        record.save(update_fields=["processing_status"])
        DataQualityIssue.objects.filter(raw_record=record).update(order=order)
        committed_rows += 1
    financials = calculate_financials(totals)
    OrderFinancial.objects.update_or_create(order=order, defaults=financials)
    return order, committed_rows, skipped_rows


@transaction.atomic
def commit_batch(batch: ImportBatch, duplicate_action="SKIP") -> dict:
    batch = ImportBatch.objects.select_for_update().get(pk=batch.pk)
    if batch.status != ImportBatch.Status.PREVIEWED:
        raise ValueError("Batch phải ở trạng thái đã xem trước trước khi xác nhận.")
    batch.status = ImportBatch.Status.PROCESSING
    batch.duplicate_action = duplicate_action
    batch.save(update_fields=["status", "duplicate_action"])
    grouped = defaultdict(list)
    for record in batch.raw_records.exclude(processing_status=RawOrderRecord.Status.ERROR):
        row = _deserialize_row(record.normalized_data)
        if row.get("external_order_id"):
            grouped[row["external_order_id"]].append((record, row))
    committed = skipped = 0
    for rows in grouped.values():
        order, committed_count, skipped_count = _create_or_update_order(batch, rows, duplicate_action)
        committed += committed_count
        skipped += skipped_count
    batch.status = ImportBatch.Status.COMPLETED
    batch.completed_at = timezone.now()
    batch.success_rows = committed
    batch.duplicate_rows = skipped
    batch.save(update_fields=["status", "completed_at", "success_rows", "duplicate_rows"])
    refresh_customer_summaries(batch.platform_id)
    return {"committed_rows": committed, "skipped_rows": skipped, "orders": len(grouped)}


def refresh_customer_summaries(platform_id=None):
    customers = PlatformCustomer.objects.all()
    if platform_id:
        customers = customers.filter(platform_id=platform_id)
    for customer in customers:
        summary = customer.orders.aggregate(
            first=Min("order_created_at"), last=Max("order_created_at"), orders=Count("id"),
            revenue=Sum("financial__net_revenue"),
        )
        quantity = customer.orders.aggregate(quantity=Sum("items__quantity"))["quantity"]
        customer.first_order_at = summary["first"]
        customer.last_order_at = summary["last"]
        customer.total_orders = summary["orders"] or 0
        customer.total_quantity = quantity or 0
        customer.total_revenue = summary["revenue"] or ZERO
        customer.save(update_fields=["first_order_at", "last_order_at", "total_orders", "total_quantity", "total_revenue"])
