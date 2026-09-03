from django.contrib import admin

from .models import Account, Budget, Category, Tag, Transaction, TransactionSplit


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("name", "ledger", "account_type", "currency", "opening_balance", "is_active")
    list_filter = ("account_type", "is_active")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "ledger", "parent", "is_active")
    list_filter = ("kind", "is_active")


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "ledger")


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("date", "type", "amount", "currency", "ledger", "from_account", "category")
    list_filter = ("type", "ledger")
    date_hierarchy = "date"


@admin.register(TransactionSplit)
class TransactionSplitAdmin(admin.ModelAdmin):
    list_display = ("transaction", "category", "amount")


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ("ledger", "budget_type", "year", "month", "amount")
