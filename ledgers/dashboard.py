"""账本首页仪表盘（支持 ?month=YYYY-MM 切换）。"""
import calendar
from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from transactions.models import Transaction
from transactions.services import (
    account_balances_summary,
    budget_status,
    category_summary,
    ledger_totals,
    monthly_series,
    month_range,
)

from .models import LedgerMembership
from .views import _ensure_member


def _parse_month(value, today: date) -> tuple[int, int]:
    try:
        year, month = (int(x) for x in value.split("-"))
        if 2000 <= year <= 2100 and 1 <= month <= 12:
            return year, month
    except (ValueError, AttributeError):
        pass
    return today.year, today.month


@login_required
@_ensure_member
def dashboard(request, ledger_pk):
    ledger = request.ledger
    today = date.today()
    year, month = _parse_month(request.GET.get("month"), today)
    is_current = (year, month) == (today.year, today.month)
    this_start, this_end = month_range(year, month)
    if month == 1:
        last_start, last_end = month_range(year - 1, 12)
    else:
        last_start, last_end = month_range(year, month - 1)

    this = ledger_totals(ledger, this_start, this_end)
    last = ledger_totals(ledger, last_start, last_end)

    def pct(cur: Decimal, prev: Decimal):
        if prev == 0:
            return None if cur == 0 else 100.0
        return float((cur - prev) / prev * 100)

    expense_items, expense_total = category_summary(ledger, "expense", this_start, this_end, limit=6)
    income_items, income_total = category_summary(ledger, "income", this_start, this_end, limit=6)
    balances, total_balance = account_balances_summary(ledger)
    trend_end = this_end if not is_current else today
    trend = monthly_series(ledger, months=6, end=trend_end)
    budgets = budget_status(ledger, year, month)

    recent = (
        Transaction.objects.filter(ledger=ledger, date__gte=this_start, date__lte=this_end)
        .select_related("from_account", "to_account", "category")
        .prefetch_related("tags")
        .order_by("-date", "-id")[:8]
    )

    my_ledgers = (
        LedgerMembership.objects.select_related("ledger")
        .filter(user=request.user, is_active=True)
        .order_by("-ledger__created_at")
    )
    prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_month = (year + 1, 1) if month == 12 else (year, month + 1)

    asset_colors = [
        "#2d9c76", "#4fb791", "#84d2b3", "#1f7d5f", "#eab308",
        "#3b82f6", "#a855f7", "#ef4444", "#f97316", "#14b8a6",
    ]
    positive = [item for item in balances if item["balance"] > 0]
    for idx, item in enumerate(positive):
        item["color"] = asset_colors[idx % len(asset_colors)]
    for item in balances:
        item.setdefault("color", "#9ca3af")
    assets_chart = {
        "labels": [i["account"].name for i in positive],
        "series": [{"name": "资产", "data": [float(i["balance"]) for i in positive]}],
    }
    import json as json_module

    return render(
        request,
        "ledgers/dashboard.html",
        {
            "ledger": ledger,
            "year": year,
            "month": month,
            "is_current": is_current,
            "prev_month": prev_month,
            "next_month": next_month,
            "this": this,
            "last": last,
            "pct_income": pct(this["income"], last["income"]),
            "pct_expense": pct(this["expense"], last["expense"]),
            "pct_refund": pct(this["refund_total"], last["refund_total"]),
            "expense_items": expense_items,
            "expense_total": expense_total,
            "income_items": income_items,
            "income_total": income_total,
            "balances": balances,
            "assets_chart_json": json_module.dumps(assets_chart, ensure_ascii=False),
            "total_balance": total_balance,
            "trend": trend,
            "budgets": budgets,
            "recent": recent,
            "today": today,
            "my_ledgers": my_ledgers,
            "calendar": calendar,
        },
    )
