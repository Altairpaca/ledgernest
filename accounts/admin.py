from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class LedgerNestUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("偏好", {"fields": ("display_name", "locale", "timezone")}),)
    list_display = ("username", "display_name", "email", "is_active", "date_joined")
    search_fields = ("username", "display_name", "email")
