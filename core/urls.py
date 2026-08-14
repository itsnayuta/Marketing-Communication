from django.urls import path

from . import views


urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("orders/", views.order_list, name="orders"),
    path("orders/export/<str:format>/", views.order_export, name="order-export"),
    path("orders/<uuid:pk>/", views.order_detail, name="order-detail"),
    path("imports/new/", views.import_start, name="import-start"),
    path("imports/upload/", views.import_upload, name="import-upload"),
    path("imports/<int:pk>/mapping/", views.import_mapping, name="import-mapping"),
    path("imports/<int:pk>/preview/", views.import_preview, name="import-preview"),
    path("imports/<int:pk>/confirm/", views.import_confirm, name="import-confirm"),
    path("imports/history/", views.import_history, name="import-history"),
    path("imports/<int:pk>/", views.batch_detail, name="batch-detail"),
    path("products/", views.product_list, name="products"),
    path("products/aliases/", views.product_aliases, name="product-aliases"),
    path("mappings/columns/", views.mapping_profiles, name="mapping-profiles"),
    path("quality/", views.data_quality, name="data-quality"),
    path("quality/<int:pk>/resolve/", views.resolve_issue, name="resolve-issue"),
    path("ai/", views.ai_assistant, name="ai-assistant"),
    path("settings/", views.settings_page, name="settings"),
]

