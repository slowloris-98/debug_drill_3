from django.contrib import admin
from django.urls import include, path

from dashboard import views as dashboard_views

urlpatterns = [
    path("", dashboard_views.invoice_report, name="invoice-report"),
    path("usage/", dashboard_views.usage_report, name="usage-report"),
    path("api/v1/", include("api.urls")),
    path("admin/", admin.site.urls),
]
