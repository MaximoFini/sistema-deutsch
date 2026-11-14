from django.contrib import admin

from .models import Channel, ChannelCredential, ChannelWriteSwitch, ExternalRef, InboundEvent, SyncRun


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active")


@admin.register(ChannelCredential)
class ChannelCredentialAdmin(admin.ModelAdmin):
    """Nunca muestra el valor de la credencial."""

    list_display = ("channel", "expires_at", "updated_at")
    fields = ("channel", "expires_at")
    readonly_fields = ("channel", "expires_at")

    def has_add_permission(self, request):
        return False


@admin.register(ChannelWriteSwitch)
class ChannelWriteSwitchAdmin(admin.ModelAdmin):
    list_display = ("channel", "kind", "enabled", "changed_by", "changed_at")
    readonly_fields = ("channel", "kind", "enabled", "changed_by", "changed_at")

    def has_add_permission(self, request):
        return False


@admin.register(InboundEvent)
class InboundEventAdmin(admin.ModelAdmin):
    list_display = ("received_at", "channel", "topic", "status", "attempts")
    list_filter = ("channel", "status", "topic")
    search_fields = ("dedupe_key",)


admin.site.register(ExternalRef)
admin.site.register(SyncRun)
