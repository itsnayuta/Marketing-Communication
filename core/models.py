import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models


MONEY_ARGS = {"max_digits": 18, "decimal_places": 2, "default": Decimal("0")}


class Platform(models.Model):
    class Code(models.TextChoices):
        TIKTOK = "TIKTOK", "TikTok"
        SHOPEE = "SHOPEE", "Shopee"
        FACEBOOK = "FACEBOOK", "Facebook"
        ZALO = "ZALO", "Zalo"
        OTHER = "OTHER", "Khác"

    code = models.CharField(max_length=20, choices=Code.choices, unique=True)
    name = models.CharField(max_length=80)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.name


class ImportBatch(models.Model):
    class Status(models.TextChoices):
        UPLOADED = "UPLOADED", "Đã tải lên"
        PREVIEWED = "PREVIEWED", "Đã xem trước"
        PROCESSING = "PROCESSING", "Đang xử lý"
        COMPLETED = "COMPLETED", "Hoàn tất"
        FAILED = "FAILED", "Thất bại"

    platform = models.ForeignKey(Platform, on_delete=models.PROTECT, related_name="import_batches")
    original_filename = models.CharField(max_length=255)
    file_path = models.FileField(upload_to="uploads/%Y/%m/")
    file_hash = models.CharField(max_length=64, db_index=True)
    total_rows = models.PositiveIntegerField(default=0)
    success_rows = models.PositiveIntegerField(default=0)
    warning_rows = models.PositiveIntegerField(default=0)
    error_rows = models.PositiveIntegerField(default=0)
    duplicate_rows = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPLOADED, db_index=True)
    mapping_snapshot = models.JSONField(default=dict, blank=True)
    duplicate_action = models.CharField(max_length=10, choices=(("SKIP", "Bỏ qua"), ("UPDATE", "Cập nhật")), default="SKIP")
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["platform", "created_at"])]

    @property
    def processing_seconds(self):
        if self.started_at and self.completed_at:
            return round((self.completed_at - self.started_at).total_seconds(), 2)
        return None

    def __str__(self):
        return f"#{self.pk} {self.original_filename}"


class RawOrderRecord(models.Model):
    class Status(models.TextChoices):
        RAW = "RAW", "Raw"
        VALID = "VALID", "Hợp lệ"
        WARNING = "WARNING", "Cảnh báo"
        ERROR = "ERROR", "Lỗi"
        DUPLICATE = "DUPLICATE", "Trùng lặp"
        COMMITTED = "COMMITTED", "Đã ghi"

    import_batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="raw_records")
    row_number = models.PositiveIntegerField()
    raw_data = models.JSONField()
    normalized_data = models.JSONField(default=dict, blank=True)
    processing_status = models.CharField(max_length=20, choices=Status.choices, default=Status.RAW, db_index=True)
    error_messages = models.JSONField(default=list, blank=True)
    warning_messages = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["row_number"]
        constraints = [models.UniqueConstraint(fields=["import_batch", "row_number"], name="uq_raw_batch_row")]
        indexes = [models.Index(fields=["import_batch", "processing_status"])]

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.only("raw_data").get(pk=self.pk)
            if original.raw_data != self.raw_data:
                raise ValidationError("Dữ liệu RAW là bất biến và không thể chỉnh sửa.")
        super().save(*args, **kwargs)


class MappingProfile(models.Model):
    platform = models.ForeignKey(Platform, on_delete=models.CASCADE, related_name="mapping_profiles")
    name = models.CharField(max_length=120)
    version = models.PositiveIntegerField(default=1)
    is_default = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["platform", "name", "version"], name="uq_mapping_version")]
        ordering = ["platform", "name", "-version"]

    def __str__(self):
        return f"{self.platform.code} · {self.name} v{self.version}"


class MappingRule(models.Model):
    profile = models.ForeignKey(MappingProfile, on_delete=models.CASCADE, related_name="rules")
    source_column = models.CharField(max_length=160)
    target_field = models.CharField(max_length=100)
    transform_rule = models.CharField(max_length=80, blank=True)
    required = models.BooleanField(default=False)
    default_value = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["profile", "source_column"], name="uq_mapping_source")]


class Product(models.Model):
    internal_sku = models.CharField(max_length=100, unique=True, db_index=True)
    product_name = models.CharField(max_length=255)
    variant_name = models.CharField(max_length=255, blank=True)
    default_cost = models.DecimalField(**MONEY_ARGS)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["internal_sku"]

    def __str__(self):
        return f"{self.internal_sku} · {self.product_name}"


class ProductAlias(models.Model):
    class Source(models.TextChoices):
        MANUAL = "MANUAL", "Thủ công"
        IMPORT = "IMPORT", "Import"
        AI_CONFIRMED = "AI_CONFIRMED", "AI đã xác nhận"

    platform = models.ForeignKey(Platform, on_delete=models.CASCADE, related_name="product_aliases")
    external_sku = models.CharField(max_length=160, blank=True)
    external_product_name = models.CharField(max_length=255, blank=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="aliases")
    confidence = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("1"))
    mapping_source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["platform", "external_sku", "external_product_name"], name="uq_product_alias")
        ]
        indexes = [models.Index(fields=["platform", "external_sku"])]


class PlatformCustomer(models.Model):
    platform = models.ForeignKey(Platform, on_delete=models.PROTECT, related_name="customers")
    platform_user_id = models.CharField(max_length=160)
    internal_customer_id = models.UUIDField(default=uuid.uuid4, editable=False)
    first_order_at = models.DateTimeField(null=True, blank=True)
    last_order_at = models.DateTimeField(null=True, blank=True)
    total_orders = models.PositiveIntegerField(default=0)
    total_quantity = models.PositiveIntegerField(default=0)
    total_revenue = models.DecimalField(**MONEY_ARGS)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["platform", "platform_user_id"], name="uq_platform_customer")]
        indexes = [models.Index(fields=["platform", "platform_user_id"])]


class Order(models.Model):
    class Quality(models.TextChoices):
        GOOD = "GOOD", "Tốt"
        WARNING = "WARNING", "Cảnh báo"
        ERROR = "ERROR", "Lỗi"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    platform = models.ForeignKey(Platform, on_delete=models.PROTECT, related_name="orders")
    external_order_id = models.CharField(max_length=160)
    platform_user_id = models.CharField(max_length=160, blank=True, db_index=True)
    shipping_id = models.CharField(max_length=160, blank=True, db_index=True)
    order_created_at = models.DateTimeField(db_index=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    order_status = models.CharField(max_length=50, blank=True, db_index=True)
    payment_status = models.CharField(max_length=50, blank=True)
    currency = models.CharField(max_length=3, default="VND")
    customer = models.ForeignKey(PlatformCustomer, on_delete=models.SET_NULL, null=True, blank=True, related_name="orders")
    source_type = models.CharField(max_length=20, default="IMPORT")
    import_batch = models.ForeignKey(ImportBatch, on_delete=models.PROTECT, related_name="orders", db_index=True)
    data_quality_status = models.CharField(max_length=20, choices=Quality.choices, default=Quality.GOOD, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-order_created_at"]
        constraints = [models.UniqueConstraint(fields=["platform", "external_order_id"], name="uq_platform_order")]
        indexes = [
            models.Index(fields=["platform", "external_order_id"]),
            models.Index(fields=["platform", "order_created_at"]),
        ]

    def __str__(self):
        return f"{self.platform.code} · {self.external_order_id}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    external_item_id = models.CharField(max_length=160, blank=True)
    line_number = models.PositiveIntegerField(default=1)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, null=True, blank=True, related_name="order_items")
    external_sku = models.CharField(max_length=160, blank=True, db_index=True)
    product_name_snapshot = models.CharField(max_length=255)
    variant_name_snapshot = models.CharField(max_length=255, blank=True)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(**MONEY_ARGS)
    original_unit_price = models.DecimalField(**MONEY_ARGS)
    seller_discount = models.DecimalField(**MONEY_ARGS)
    platform_discount = models.DecimalField(**MONEY_ARGS)
    gross_item_revenue = models.DecimalField(**MONEY_ARGS)
    unit_cost_snapshot = models.DecimalField(**MONEY_ARGS)
    total_cost = models.DecimalField(**MONEY_ARGS)

    class Meta:
        ordering = ["line_number"]
        constraints = [
            models.UniqueConstraint(fields=["order", "external_item_id"], condition=~models.Q(external_item_id=""), name="uq_order_external_item"),
            models.UniqueConstraint(fields=["order", "external_sku", "line_number"], condition=models.Q(external_item_id=""), name="uq_order_fallback_item"),
        ]


class OrderFinancial(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="financial")
    gross_revenue = models.DecimalField(**MONEY_ARGS)
    seller_discount = models.DecimalField(**MONEY_ARGS)
    platform_discount = models.DecimalField(**MONEY_ARGS)
    refund_amount = models.DecimalField(**MONEY_ARGS)
    net_revenue = models.DecimalField(**MONEY_ARGS)
    platform_fee = models.DecimalField(**MONEY_ARGS)
    affiliate_commission = models.DecimalField(**MONEY_ARGS)
    cost_of_goods = models.DecimalField(**MONEY_ARGS)
    shipping_cost_seller = models.DecimalField(**MONEY_ARGS)
    other_variable_cost = models.DecimalField(**MONEY_ARGS)
    allocated_ad_cost = models.DecimalField(**MONEY_ARGS)
    contribution_profit = models.DecimalField(**MONEY_ARGS)


class DataQualityIssue(models.Model):
    class Severity(models.TextChoices):
        ERROR = "ERROR", "Lỗi"
        WARNING = "WARNING", "Cảnh báo"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Chưa xử lý"
        RESOLVED = "RESOLVED", "Đã xử lý"

    import_batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="quality_issues")
    raw_record = models.ForeignKey(RawOrderRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name="quality_issues")
    order = models.ForeignKey(Order, on_delete=models.CASCADE, null=True, blank=True, related_name="quality_issues")
    issue_type = models.CharField(max_length=80)
    severity = models.CharField(max_length=10, choices=Severity.choices, db_index=True)
    field_name = models.CharField(max_length=100, blank=True, db_index=True)
    current_value = models.TextField(blank=True)
    message = models.TextField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["import_batch", "severity", "status"])]

