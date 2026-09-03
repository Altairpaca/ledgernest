from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "ledger", "actor", "action", "object_type", "summary")
    list_filter = ("action", "ledger")
    search_fields = ("summary",)
    readonly_fields = [f.name for f in AuditLog._meta.fields]
