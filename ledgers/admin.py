from django.contrib import admin

from .models import Ledger, LedgerInvitation, LedgerMembership


@admin.register(Ledger)
class LedgerAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "base_currency", "archived_at", "created_at")
    search_fields = ("name",)


@admin.register(LedgerMembership)
class LedgerMembershipAdmin(admin.ModelAdmin):
    list_display = ("ledger", "user", "role", "is_active", "joined_at")
    list_filter = ("role", "is_active")


@admin.register(LedgerInvitation)
class LedgerInvitationAdmin(admin.ModelAdmin):
    list_display = ("ledger", "role", "created_by", "expires_at", "accepted_at")
