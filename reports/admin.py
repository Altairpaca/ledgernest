from django.contrib import admin

from .models import ReportDefinition


@admin.register(ReportDefinition)
class ReportDefinitionAdmin(admin.ModelAdmin):
    list_display = ("name", "ledger", "created_by", "is_shared", "updated_at")
