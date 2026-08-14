from django.contrib import admin

from .models import (
    DataQualityIssue,
    ImportBatch,
    MappingProfile,
    MappingRule,
    Order,
    OrderFinancial,
    OrderItem,
    Platform,
    PlatformCustomer,
    Product,
    ProductAlias,
    RawOrderRecord,
)


admin.site.site_header = "BAKA Technical Administration"
admin.site.site_title = "BAKA Admin"


@admin.register(Platform)
class PlatformAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")


class MappingRuleInline(admin.TabularInline):
    model = MappingRule
    extra = 0


@admin.register(MappingProfile)
class MappingProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "platform", "version", "is_default")
    inlines = [MappingRuleInline]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("internal_sku", "product_name", "variant_name", "default_cost", "is_active")
    search_fields = ("internal_sku", "product_name")


@admin.register(ProductAlias)
class ProductAliasAdmin(admin.ModelAdmin):
    list_display = ("platform", "external_sku", "external_product_name", "product", "mapping_source")
    search_fields = ("external_sku", "external_product_name", "product__internal_sku")


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = ("id", "platform", "original_filename", "total_rows", "status", "created_at")
    list_filter = ("platform", "status")
    readonly_fields = ("file_hash", "created_at", "started_at", "completed_at")


@admin.register(RawOrderRecord)
class RawOrderRecordAdmin(admin.ModelAdmin):
    list_display = ("import_batch", "row_number", "processing_status")
    list_filter = ("processing_status",)
    readonly_fields = ("raw_data", "created_at")


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("external_item_id", "external_sku", "quantity", "gross_item_revenue", "total_cost")


class OrderFinancialInline(admin.StackedInline):
    model = OrderFinancial
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("external_order_id", "platform", "order_created_at", "order_status", "data_quality_status")
    list_filter = ("platform", "order_status", "data_quality_status")
    search_fields = ("external_order_id", "platform_user_id", "shipping_id")
    inlines = [OrderItemInline, OrderFinancialInline]


admin.site.register(PlatformCustomer)
admin.site.register(DataQualityIssue)

