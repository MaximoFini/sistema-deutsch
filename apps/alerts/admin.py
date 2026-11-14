from django.contrib import admin

from .models import Alert, AlertType


@admin.register(AlertType)
class AlertTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "severity", "send_email", "is_active")
    filter_horizontal = ("roles",)


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("created_at", "alert_type", "title")
    list_filter = ("alert_type",)
