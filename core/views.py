import csv
import io

import pandas as pd
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import ConfirmImportForm, MappingForm, PlatformForm, ProductAliasForm, ProductForm, UploadForm
from .models import DataQualityIssue, ImportBatch, MappingProfile, Order, OrderItem, Platform, Product, ProductAlias, RawOrderRecord
from .services.ai import AIService
from .services.import_pipeline import (
    CANONICAL_FIELDS,
    commit_batch,
    create_batch,
    mapping_from_default_profile,
    preview_batch,
    save_mapping_profile,
)


def _can_edit(user):
    return user.is_superuser or user.groups.filter(name="ADMIN").exists()


def _require_editor(request):
    if not _can_edit(request.user):
        return HttpResponseForbidden("Tài khoản VIEWER chỉ có quyền xem.")
    return None


def _date_filter(queryset, request, field="order_created_at"):
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    if date_from:
        queryset = queryset.filter(**{f"{field}__date__gte": date_from})
    if date_to:
        queryset = queryset.filter(**{f"{field}__date__lte": date_to})
    return queryset


@login_required
def dashboard(request):
    orders = Order.objects.select_related("platform", "financial")
    orders = _date_filter(orders, request)
    platform = request.GET.get("platform")
    if platform:
        orders = orders.filter(platform_id=platform)
    order_ids = orders.values("id")
    finance = orders.aggregate(
        gross=Sum("financial__gross_revenue"), net=Sum("financial__net_revenue"),
        fee=Sum("financial__platform_fee"), affiliate=Sum("financial__affiliate_commission"),
        cogs=Sum("financial__cost_of_goods"), profit=Sum("financial__contribution_profit"),
    )
    quantity = Order.objects.filter(id__in=order_ids).aggregate(total=Sum("items__quantity"))["total"] or 0
    issues = DataQualityIssue.objects.filter(order_id__in=order_ids, status=DataQualityIssue.Status.OPEN).count()
    daily_revenue = {
        str(row["day"]): float(row["revenue"] or 0)
        for row in orders.annotate(day=TruncDate("order_created_at")).values("day").annotate(
            revenue=Sum("financial__net_revenue")
        ).order_by("day")
    }
    daily_quantity = {
        str(row["day"]): row["quantity"] or 0
        for row in OrderItem.objects.filter(order_id__in=order_ids).annotate(
            day=TruncDate("order__order_created_at")
        ).values("day").annotate(quantity=Sum("quantity")).order_by("day")
    }
    days = sorted(set(daily_revenue) | set(daily_quantity))
    by_platform = list(orders.values("platform__name").annotate(
        revenue=Sum("financial__net_revenue"), profit=Sum("financial__contribution_profit")
    ).order_by("platform__name"))
    chart_data = {
        "days": days,
        "dailyRevenue": [daily_revenue.get(day, 0) for day in days],
        "dailyQuantity": [daily_quantity.get(day, 0) for day in days],
        "platforms": [row["platform__name"] for row in by_platform],
        "platformRevenue": [float(row["revenue"] or 0) for row in by_platform],
        "platformProfit": [float(row["profit"] or 0) for row in by_platform],
    }
    context = {
        "orders_count": orders.count(), "quantity": quantity, "issues_count": issues,
        "finance": finance, "platforms": Platform.objects.filter(is_active=True),
        "chart_data": chart_data,
    }
    return render(request, "core/dashboard.html", context)


def _filtered_orders(request):
    queryset = Order.objects.select_related("platform", "financial", "import_batch").prefetch_related("items__product")
    queryset = _date_filter(queryset, request)
    filters = {
        "platform_id": request.GET.get("platform"),
        "order_status": request.GET.get("status"),
        "data_quality_status": request.GET.get("quality"),
    }
    for key, value in filters.items():
        if value:
            queryset = queryset.filter(**{key: value})
    if request.GET.get("sku"):
        queryset = queryset.filter(items__external_sku__icontains=request.GET["sku"])
    if request.GET.get("q"):
        term = request.GET["q"]
        queryset = queryset.filter(
            Q(external_order_id__icontains=term) | Q(platform_user_id__icontains=term)
            | Q(shipping_id__icontains=term) | Q(items__external_sku__icontains=term)
            | Q(items__product_name_snapshot__icontains=term)
        )
    sorting = request.GET.get("sort", "-order_created_at")
    allowed = {"order_created_at", "-order_created_at", "external_order_id", "-external_order_id", "order_status", "-order_status"}
    return queryset.order_by(sorting if sorting in allowed else "-order_created_at").distinct()


@login_required
def order_list(request):
    queryset = _filtered_orders(request)
    try:
        per_page = int(request.GET.get("per_page", 25))
    except ValueError:
        per_page = 25
    per_page = per_page if per_page in {10, 25, 50, 100} else 25
    page_obj = Paginator(queryset, per_page).get_page(request.GET.get("page"))
    return render(request, "core/order_list.html", {
        "page_obj": page_obj, "platforms": Platform.objects.all(),
        "statuses": Order.objects.exclude(order_status="").values_list("order_status", flat=True).distinct(),
        "per_page": per_page,
    })


@login_required
def order_detail(request, pk):
    order = get_object_or_404(Order.objects.select_related("platform", "customer", "financial", "import_batch").prefetch_related("items__product", "quality_issues"), pk=pk)
    raw_records = [record for record in order.import_batch.raw_records.all() if record.normalized_data.get("external_order_id") == order.external_order_id]
    return render(request, "core/order_detail.html", {"order": order, "raw_records": raw_records})


def _order_export_rows(queryset):
    for order in queryset:
        items = list(order.items.all())
        financial = order.financial
        yield {
            "Platform": order.platform.name,
            "Order ID": order.external_order_id,
            "Date": order.order_created_at.isoformat(),
            "User ID": order.platform_user_id,
            "Shipping ID": order.shipping_id,
            "SKU": ", ".join(item.external_sku for item in items),
            "Product": ", ".join(item.product_name_snapshot for item in items),
            "Quantity": sum(item.quantity for item in items),
            "Gross Revenue": financial.gross_revenue,
            "Net Revenue": financial.net_revenue,
            "Platform Fee": financial.platform_fee,
            "COGS": financial.cost_of_goods,
            "Affiliate Commission": financial.affiliate_commission,
            "Contribution Profit": financial.contribution_profit,
            "Order Status": order.order_status,
            "Data Quality": order.data_quality_status,
        }


@login_required
def order_export(request, format):
    rows = list(_order_export_rows(_filtered_orders(request)))
    filename = f"baka-orders-{timezone.localdate().isoformat()}"
    if format == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
        response.write("\ufeff")
        writer = csv.DictWriter(response, fieldnames=rows[0].keys() if rows else ["Order ID"])
        writer.writeheader()
        writer.writerows(rows)
        return response
    if format == "xlsx":
        output = io.BytesIO()
        pd.DataFrame(rows).to_excel(output, index=False, engine="openpyxl")
        response = HttpResponse(output.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
        return response
    return HttpResponse(status=404)


@login_required
def import_start(request):
    denied = _require_editor(request)
    if denied:
        return denied
    form = PlatformForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        return redirect(f"{reverse('import-upload')}?platform={form.cleaned_data['platform'].pk}")
    return render(request, "core/import_step.html", {"form": form, "step": 1, "title": "Chọn nền tảng"})


@login_required
def import_upload(request):
    denied = _require_editor(request)
    if denied:
        return denied
    platform = get_object_or_404(Platform, pk=request.GET.get("platform"), is_active=True)
    form = UploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            batch = create_batch(platform, form.cleaned_data["data_file"])
            return redirect("import-mapping", pk=batch.pk)
        except ValueError as exc:
            form.add_error("data_file", str(exc))
    return render(request, "core/import_step.html", {"form": form, "step": 2, "title": "Tải tệp dữ liệu", "platform": platform})


@login_required
def import_mapping(request, pk):
    denied = _require_editor(request)
    if denied:
        return denied
    batch = get_object_or_404(ImportBatch, pk=pk)
    first = batch.raw_records.first()
    columns = list(first.raw_data) if first else []
    initial = batch.mapping_snapshot or mapping_from_default_profile(batch.platform, columns)
    if request.method == "POST" and request.POST.get("action") == "ai":
        sample_records = list(batch.raw_records.all()[:3])
        samples = {column: [record.raw_data.get(column, "") for record in sample_records] for column in columns}
        result = AIService().suggest_column_mapping(batch.platform.code, columns, samples)
        initial.update({item["target_field"]: item["source_column"] for item in result["mappings"] if item["target_field"] in CANONICAL_FIELDS})
        messages.info(request, "Đã nạp đề xuất AI." if result["source"] == "ai" else "AI không khả dụng; đã dùng gợi ý cục bộ an toàn.")
        form = MappingForm(columns=columns, initial_mapping=initial)
    else:
        form = MappingForm(request.POST or None, columns=columns, initial_mapping=initial)
        if request.method == "POST" and form.is_valid():
            mapping = form.mapping()
            if form.cleaned_data.get("save_profile"):
                save_mapping_profile(batch.platform, form.cleaned_data.get("profile_name"), mapping)
            preview_batch(batch, mapping)
            return redirect("import-preview", pk=batch.pk)
    return render(request, "core/import_mapping.html", {"form": form, "batch": batch, "step": 3, "columns": columns})


@login_required
def import_preview(request, pk):
    batch = get_object_or_404(ImportBatch.objects.select_related("platform"), pk=pk)
    records = batch.raw_records.all()[:100]
    return render(request, "core/import_preview.html", {"batch": batch, "records": records, "form": ConfirmImportForm(), "step": 4})


@login_required
@require_POST
def import_confirm(request, pk):
    denied = _require_editor(request)
    if denied:
        return denied
    batch = get_object_or_404(ImportBatch, pk=pk)
    form = ConfirmImportForm(request.POST)
    if form.is_valid():
        try:
            result = commit_batch(batch, form.cleaned_data["duplicate_action"])
            messages.success(request, f"Đã ghi {result['committed_rows']} dòng; bỏ qua {result['skipped_rows']} dòng trùng.")
            return redirect("batch-detail", pk=batch.pk)
        except ValueError as exc:
            messages.error(request, str(exc))
    return redirect("import-preview", pk=batch.pk)


@login_required
def import_history(request):
    batches = ImportBatch.objects.select_related("platform")
    return render(request, "core/import_history.html", {"batches": batches})


@login_required
def batch_detail(request, pk):
    batch = get_object_or_404(ImportBatch.objects.select_related("platform"), pk=pk)
    preview_records = list(batch.raw_records.all()[:100])
    ai_summary = None
    if request.GET.get("ai_summary") == "1":
        ai_summary = AIService().summarize_import_batch({
            "platform": batch.platform.code, "total_rows": batch.total_rows,
            "success_rows": batch.success_rows, "warning_rows": batch.warning_rows,
            "error_rows": batch.error_rows, "duplicate_rows": batch.duplicate_rows,
            "status": batch.status,
        })
    return render(request, "core/batch_detail.html", {
        "batch": batch,
        "errors": [record for record in preview_records if record.error_messages],
        "warnings": [record for record in preview_records if record.warning_messages],
        "duplicates": [record for record in preview_records if record.processing_status == RawOrderRecord.Status.DUPLICATE],
        "raw_records": preview_records[:50],
        "ai_summary": ai_summary,
    })


@login_required
def product_list(request):
    denied = _require_editor(request) if request.method == "POST" else None
    if denied:
        return denied
    form = ProductForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Đã thêm Product Master.")
        return redirect("products")
    products = Product.objects.prefetch_related("aliases")
    if request.GET.get("q"):
        products = products.filter(Q(internal_sku__icontains=request.GET["q"]) | Q(product_name__icontains=request.GET["q"]))
    return render(request, "core/products.html", {"products": products, "form": form})


@login_required
def product_aliases(request):
    denied = _require_editor(request) if request.method == "POST" else None
    if denied:
        return denied
    form = ProductAliasForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        alias = form.save(commit=False)
        alias.mapping_source = ProductAlias.Source.MANUAL
        alias.save()
        messages.success(request, "Đã xác nhận mapping sản phẩm.")
        return redirect("product-aliases")
    aliases = ProductAlias.objects.select_related("platform", "product")
    return render(request, "core/product_aliases.html", {"aliases": aliases, "form": form})


@login_required
def mapping_profiles(request):
    profiles = MappingProfile.objects.select_related("platform").prefetch_related("rules")
    return render(request, "core/mapping_profiles.html", {"profiles": profiles})


@login_required
def data_quality(request):
    issues = DataQualityIssue.objects.select_related("import_batch__platform", "order", "raw_record")
    params = {"severity": "severity", "platform": "import_batch__platform_id", "batch": "import_batch_id", "field": "field_name", "status": "status"}
    for query_key, lookup in params.items():
        if request.GET.get(query_key):
            issues = issues.filter(**{lookup: request.GET[query_key]})
    page_obj = Paginator(issues, 50).get_page(request.GET.get("page"))
    ai_explanation = None
    if request.GET.get("explain") == "1":
        ai_explanation = AIService().explain_data_quality_anomalies(list(issues.values("issue_type", "severity", "field_name")[:200]))
    return render(request, "core/data_quality.html", {
        "page_obj": page_obj, "platforms": Platform.objects.all(),
        "batches": ImportBatch.objects.all()[:100], "ai_explanation": ai_explanation,
    })


@login_required
@require_POST
def resolve_issue(request, pk):
    denied = _require_editor(request)
    if denied:
        return denied
    issue = get_object_or_404(DataQualityIssue, pk=pk)
    issue.status = DataQualityIssue.Status.RESOLVED
    issue.resolved_at = timezone.now()
    issue.save(update_fields=["status", "resolved_at"])
    if request.headers.get("HX-Request") == "true":
        return HttpResponse("")
    return redirect(request.POST.get("next") or "data-quality")


@login_required
def ai_assistant(request):
    result = None
    result_type = "column"
    if request.method == "POST":
        result_type = request.POST.get("action", "column")
        if result_type == "product":
            candidates = list(Product.objects.filter(is_active=True).values("internal_sku", "product_name", "variant_name"))
            result = AIService().suggest_product_mapping(
                request.POST.get("platform", "OTHER"), request.POST.get("external_sku", ""),
                request.POST.get("external_product_name", ""), candidates,
            )
        else:
            headers = [item.strip() for item in request.POST.get("headers", "").split(",") if item.strip()]
            result = AIService().suggest_column_mapping(request.POST.get("platform", "OTHER"), headers)
    return render(request, "core/ai_assistant.html", {
        "result": result, "result_type": result_type, "ai_enabled": AIService().enabled,
        "platforms": Platform.objects.all(),
    })


@login_required
def settings_page(request):
    return render(request, "core/settings.html", {"ai_enabled": AIService().enabled, "can_edit": _can_edit(request.user)})
