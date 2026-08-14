import tempfile
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import ImportBatch, MappingProfile, Order, Platform, Product, ProductAlias, RawOrderRecord
from core.services.ai import AIService
from core.services.financials import calculate_financials
from core.services.import_pipeline import (
    commit_batch,
    create_batch,
    mapping_from_default_profile,
    normalize_record,
    preview_batch,
    save_mapping_profile,
)


MAPPING = {
    "external_order_id": "order_id",
    "external_item_id": "item_id",
    "order_created_at": "date",
    "platform_user_id": "user_id",
    "shipping_id": "shipping_id",
    "external_sku": "sku",
    "product_name": "product",
    "quantity": "quantity",
    "unit_price": "unit_price",
    "gross_revenue": "gross",
    "refund_amount": "refund",
    "platform_fee": "fee",
    "affiliate_commission": "affiliate",
    "shipping_cost_seller": "shipping",
    "other_variable_cost": "other",
    "allocated_ad_cost": "ads",
    "order_status": "status",
}
HEADER = "order_id,item_id,date,user_id,shipping_id,sku,product,quantity,unit_price,gross,refund,fee,affiliate,shipping,other,ads,status\n"


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class PipelineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.platform = Platform.objects.create(code=Platform.Code.TIKTOK, name="TikTok")
        cls.product = Product.objects.create(
            internal_sku="BAKA-01", product_name="BAKA 500g", variant_name="500g", default_cost=Decimal("50")
        )
        ProductAlias.objects.create(platform=cls.platform, external_sku="SKU-1", product=cls.product)

    def batch(self, rows):
        content = HEADER + "\n".join(rows) + "\n"
        upload = SimpleUploadedFile("orders.csv", content.encode("utf-8"), content_type="text/csv")
        return create_batch(self.platform, upload)

    def test_multi_item_order_and_financial_formula(self):
        batch = self.batch([
            "A-1,I-1,2026-01-01 10:00,u-1,ship-1,SKU-1,BAKA 500g,1,100,100,0,10,0,5,2,3,COMPLETED",
            "A-1,I-2,2026-01-01 10:00,u-1,ship-1,SKU-1,BAKA 500g,2,100,200,0,20,10,0,0,0,COMPLETED",
        ])
        preview_batch(batch, MAPPING)
        result = commit_batch(batch)
        order = Order.objects.get(external_order_id="A-1")
        self.assertEqual(order.items.count(), 2)
        self.assertEqual(result["committed_rows"], 2)
        self.assertEqual(order.financial.gross_revenue, Decimal("300"))
        self.assertEqual(order.financial.cost_of_goods, Decimal("150"))
        self.assertEqual(order.financial.contribution_profit, Decimal("100"))

    def test_invalid_quantity_and_revenue_are_errors(self):
        raw = {"order_id": "A-2", "date": "bad-date", "product": "X", "quantity": "0", "gross": "abc"}
        _, errors, _ = normalize_record(raw, MAPPING, self.platform)
        issue_types = {issue["issue_type"] for issue in errors}
        self.assertIn("INVALID_QUANTITY", issue_types)
        self.assertIn("INVALID_REVENUE", issue_types)
        self.assertIn("INVALID_DATE", issue_types)

    def test_product_alias_matches_without_creating_product(self):
        raw = {"order_id": "A-3", "date": "2026-01-01", "product": "External", "quantity": "1", "gross": "100", "sku": "SKU-1"}
        normalized, _, warnings = normalize_record(raw, MAPPING, self.platform)
        self.assertEqual(normalized["product_id"], self.product.pk)
        self.assertEqual(normalized["unit_cost"], Decimal("50"))
        self.assertNotIn("UNMAPPED_PRODUCT", {issue["issue_type"] for issue in warnings})

    def test_existing_order_is_skipped_by_default(self):
        row = "A-4,I-1,2026-01-01 10:00,u-1,ship-1,SKU-1,BAKA 500g,1,100,100,0,10,0,0,0,0,COMPLETED"
        first = self.batch([row])
        preview_batch(first, MAPPING)
        commit_batch(first)
        second = self.batch([row])
        preview_batch(second, MAPPING)
        result = commit_batch(second, "SKIP")
        self.assertEqual(Order.objects.filter(external_order_id="A-4").count(), 1)
        self.assertEqual(result["skipped_rows"], 1)

    def test_order_update_replaces_items_and_financials(self):
        first = self.batch(["A-5,I-1,2026-01-01 10:00,u-1,ship-1,SKU-1,BAKA 500g,1,100,100,0,10,0,0,0,0,NEW"])
        preview_batch(first, MAPPING)
        commit_batch(first)
        second = self.batch(["A-5,I-2,2026-01-02 10:00,u-1,ship-2,SKU-1,BAKA 500g,2,100,200,0,20,0,0,0,0,COMPLETED"])
        preview_batch(second, MAPPING)
        commit_batch(second, "UPDATE")
        order = Order.objects.get(external_order_id="A-5")
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.items.get().external_item_id, "I-2")
        self.assertEqual(order.financial.gross_revenue, Decimal("200"))
        self.assertEqual(order.order_status, "COMPLETED")

    def test_duplicate_item_inside_file_is_not_inserted_twice(self):
        row = "A-6,I-1,2026-01-01 10:00,u-1,ship-1,SKU-1,BAKA 500g,1,100,100,0,10,0,0,0,0,NEW"
        batch = self.batch([row, row])
        preview_batch(batch, MAPPING)
        result = commit_batch(batch)
        self.assertEqual(Order.objects.get(external_order_id="A-6").items.count(), 1)
        self.assertEqual(result["skipped_rows"], 1)

    def test_mapping_profile_round_trip(self):
        profile = save_mapping_profile(self.platform, "TikTok standard", MAPPING)
        loaded = mapping_from_default_profile(self.platform, list(MAPPING.values()))
        self.assertTrue(profile.is_default)
        self.assertEqual(loaded["external_order_id"], "order_id")
        self.assertEqual(MappingProfile.objects.count(), 1)

    def test_raw_data_is_immutable(self):
        batch = self.batch(["A-7,I-1,2026-01-01 10:00,u-1,ship-1,SKU-1,BAKA 500g,1,100,100,0,10,0,0,0,0,NEW"])
        record = batch.raw_records.get()
        record.raw_data = {"changed": True}
        with self.assertRaises(ValidationError):
            record.save()

    def test_unique_order_constraint(self):
        batch = ImportBatch.objects.create(platform=self.platform, original_filename="x.csv", file_path="uploads/x.csv", file_hash="x")
        fields = dict(platform=self.platform, external_order_id="UNIQUE", order_created_at=timezone.now(), import_batch=batch)
        Order.objects.create(**fields)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Order.objects.create(**fields)


class FinancialTests(TestCase):
    def test_financial_formulas(self):
        result = calculate_financials({
            "gross_revenue": "1000", "refund_amount": "100", "platform_fee": "50",
            "affiliate_commission": "40", "cost_of_goods": "300", "shipping_cost_seller": "20",
            "allocated_ad_cost": "30", "other_variable_cost": "10",
        })
        self.assertEqual(result["net_revenue"], Decimal("900"))
        self.assertEqual(result["contribution_profit"], Decimal("450"))


class _FailingResponses:
    def create(self, **kwargs):
        raise RuntimeError("network unavailable")


class _FailingClient:
    responses = _FailingResponses()


class AITests(TestCase):
    @override_settings(AI_ENABLED=False, OPENAI_API_KEY="")
    def test_ai_disabled_uses_local_mapping(self):
        result = AIService().suggest_column_mapping("TIKTOK", ["order_id", "quantity"])
        self.assertEqual(result["source"], "local")
        self.assertTrue(result["mappings"])

    @override_settings(AI_ENABLED=True, OPENAI_API_KEY="test-key")
    def test_ai_failure_falls_back_without_breaking_import(self):
        result = AIService(client=_FailingClient()).suggest_column_mapping("TIKTOK", ["order_id", "quantity"])
        self.assertEqual(result["source"], "fallback")
        self.assertTrue(result["mappings"])

    @override_settings(AI_ENABLED=False, OPENAI_API_KEY="")
    def test_optional_ai_use_cases_have_local_fallbacks(self):
        service = AIService()
        product = service.suggest_product_mapping("SHOPEE", "BAKA-01", "BAKA 500g", [
            {"internal_sku": "BAKA-01", "product_name": "BAKA 500g", "variant_name": "500g"}
        ])
        anomaly = service.explain_data_quality_anomalies([
            {"issue_type": "UNMAPPED_PRODUCT", "severity": "WARNING", "field_name": "external_sku"}
        ])
        summary = service.summarize_import_batch({"platform": "SHOPEE", "total_rows": 10, "success_rows": 8})
        self.assertEqual(product["suggestions"][0]["internal_sku"], "BAKA-01")
        self.assertIn("UNMAPPED_PRODUCT", anomaly["summary"])
        self.assertIn("10", summary["summary"])
