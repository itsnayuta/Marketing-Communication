from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management import call_command
from django.core.management.base import BaseCommand

from core.models import ImportBatch, Platform, Product, ProductAlias
from core.services.import_pipeline import commit_batch, create_batch, preview_batch


class Command(BaseCommand):
    help = "Seed Product Master và import các tệp demo của 5 nền tảng."

    def handle(self, *args, **options):
        call_command("seed_platforms")
        products = {
            "BAKA-01": ("BAKA Resistant Starch 500g", "500g", "85000"),
            "BAKA-02": ("BAKA Resistant Starch 1kg", "1kg", "155000"),
            "BAKA-03": ("BAKA Daily Sachets", "30 gói", "120000"),
        }
        product_objects = {}
        for sku, (name, variant, cost) in products.items():
            product_objects[sku], _ = Product.objects.update_or_create(
                internal_sku=sku,
                defaults={"product_name": name, "variant_name": variant, "default_cost": cost, "is_active": True},
            )
        for platform in Platform.objects.all():
            for sku, product in product_objects.items():
                ProductAlias.objects.get_or_create(
                    platform=platform,
                    external_sku=sku,
                    external_product_name="",
                    defaults={"product": product, "mapping_source": ProductAlias.Source.MANUAL},
                )
        mapping = {
            "external_order_id": "order_id", "external_item_id": "item_id", "order_created_at": "order_date",
            "paid_at": "paid_at", "completed_at": "completed_at", "platform_user_id": "user_id",
            "shipping_id": "shipping_id", "external_sku": "sku", "product_name": "product_name",
            "variant_name": "variant", "quantity": "quantity", "unit_price": "unit_price",
            "original_unit_price": "original_unit_price", "seller_discount": "seller_discount",
            "platform_discount": "platform_discount", "gross_revenue": "gross_revenue",
            "refund_amount": "refund_amount", "platform_fee": "platform_fee",
            "affiliate_commission": "affiliate_commission", "shipping_cost_seller": "shipping_cost_seller",
            "other_variable_cost": "other_variable_cost", "allocated_ad_cost": "allocated_ad_cost",
            "order_status": "order_status", "payment_status": "payment_status",
        }
        sample_dir = settings.BASE_DIR / "sample_data"
        imported = 0
        for path in sorted(sample_dir.glob("*.csv")):
            code = path.stem.upper()
            platform = Platform.objects.filter(code=code).first()
            if not platform:
                continue
            with path.open("rb") as handle:
                wrapped = File(handle, name=path.name)
                from core.services.import_pipeline import file_sha256
                digest = file_sha256(wrapped)
                if ImportBatch.objects.filter(file_hash=digest, platform=platform, status=ImportBatch.Status.COMPLETED).exists():
                    self.stdout.write(f"Skipped {path.name}: already imported.")
                    continue
                batch = create_batch(platform, wrapped)
            preview_batch(batch, mapping)
            commit_batch(batch, "SKIP")
            imported += 1
        self.stdout.write(self.style.SUCCESS(f"Demo data ready; imported {imported} new batches."))
