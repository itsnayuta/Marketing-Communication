from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

from core.models import Platform


class Command(BaseCommand):
    help = "Seed 5 nền tảng bắt buộc và hai role ADMIN/VIEWER."

    def handle(self, *args, **options):
        names = {
            Platform.Code.TIKTOK: "TikTok",
            Platform.Code.SHOPEE: "Shopee",
            Platform.Code.FACEBOOK: "Facebook",
            Platform.Code.ZALO: "Zalo",
            Platform.Code.OTHER: "Khác",
        }
        for code, name in names.items():
            Platform.objects.update_or_create(code=code, defaults={"name": name, "is_active": True})
        admin, _ = Group.objects.get_or_create(name="ADMIN")
        viewer, _ = Group.objects.get_or_create(name="VIEWER")
        core_permissions = Permission.objects.filter(content_type__app_label="core")
        admin.permissions.set(core_permissions)
        viewer.permissions.set(core_permissions.filter(codename__startswith="view_"))
        self.stdout.write(self.style.SUCCESS("Seeded 5 platforms and roles ADMIN/VIEWER."))
