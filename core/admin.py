from django.contrib import admin

from core.models import ApiKey, Invoice, Organization, UsageRecord


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "plan")


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ("organization", "label", "key", "revoked_at")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("organization", "period_start", "gross_cents", "credit_cents", "status")


@admin.register(UsageRecord)
class UsageRecordAdmin(admin.ModelAdmin):
    list_display = ("external_id", "organization", "metric", "quantity", "recorded_at")
