"""报表引擎测试：内置聚合、自定义报表白名单校验。"""
from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from reports.models import ReportDefinition
from reports.services import (
    DefinitionError,
    builtin_cashflow,
    builtin_category,
    builtin_compare,
    builtin_refund,
    builtin_trend,
    run_custom_report,
    validate_definition,
)
from transactions.models import TransactionType

from .conftest import make_txn


def test_validate_definition_whitelist():
    defn = {
        "date_range": {"type": "relative", "unit": "month", "value": 3},
        "types": ["expense"], "group_by": "month", "metric": "net",
        "sort": "metric_desc", "chart": "bar", "limit": 50,
    }
    assert validate_definition(defn)["group_by"] == "month"

    bad = dict(defn, group_by="任意SQL字段")
    with pytest.raises(DefinitionError):
        validate_definition(bad)

    bad2 = dict(defn, metric="drop_table")
    with pytest.raises(DefinitionError):
        validate_definition(bad2)

    bad3 = dict(defn, date_range={"type": "absolute", "start": "2026-09-01", "end": "2026-01-01"})
    with pytest.raises(DefinitionError):
        validate_definition(bad3)

    bad4 = dict(defn, types=["expense', (SELECT 1)) --"])
    with pytest.raises(DefinitionError):
        validate_definition(bad4)

    bad5 = dict(defn, limit=99999)
    with pytest.raises(DefinitionError):
        validate_definition(bad5)


def test_validate_definition_normalizes():
    defn = {
        "date_range": {"type": "relative"},
        "group_by": "category", "metric": "amount", "sort": "label_asc", "chart": "pie", "limit": 10,
    }
    out = validate_definition(defn)
    assert out["date_range"]["value"] == 3
    assert out["types"] == []


def test_custom_report_month_grouping(db, ledger, account_cash):
    make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=100, from_account=account_cash, date=date(2026, 6, 10))
    make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=200, from_account=account_cash, date=date(2026, 7, 10))
    defn = {
        "date_range": {"type": "absolute", "start": "2026-06-01", "end": "2026-07-31"},
        "types": ["expense"], "group_by": "month", "metric": "expense",
        "sort": "label_asc", "chart": "bar", "limit": 50,
    }
    result = run_custom_report(ledger, defn)
    assert len(result["rows"]) == 2
    assert result["rows"][0]["label"] == "2026-06"
    assert result["rows"][0]["value"] == Decimal("100.00")
    assert result["rows"][1]["value"] == Decimal("200.00")


def test_custom_report_category_grouping_with_splits(db, ledger, account_cash):
    from transactions.models import Category, TransactionSplit

    food = Category.objects.create(ledger=ledger, kind="expense", name="餐饮")
    fun = Category.objects.create(ledger=ledger, kind="expense", name="娱乐")
    txn = make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=300, from_account=account_cash, category=food)
    TransactionSplit.objects.create(transaction=txn, category=food, amount=Decimal("200"))
    TransactionSplit.objects.create(transaction=txn, category=fun, amount=Decimal("100"))
    defn = {
        "date_range": {"type": "relative", "unit": "month", "value": 3},
        "types": ["expense"], "group_by": "category", "metric": "expense",
        "sort": "metric_desc", "chart": "pie", "limit": 50,
    }
    result = run_custom_report(ledger, defn)
    by_label = {r["label"]: r["value"] for r in result["rows"]}
    assert by_label.get("餐饮") == Decimal("200.00")
    assert by_label.get("娱乐") == Decimal("100.00")


def test_custom_report_filters(db, ledger, account_cash):
    from transactions.models import Tag

    tag = Tag.objects.create(ledger=ledger, name="重要")
    t1 = make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=100, from_account=account_cash)
    t2 = make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=999, from_account=account_cash)
    t1.tags.add(tag)
    defn = {
        "date_range": {"type": "relative", "unit": "month", "value": 3},
        "types": ["expense"], "tag_ids": [tag.pk], "group_by": "type", "metric": "amount",
        "sort": "metric_desc", "chart": "bar", "limit": 50,
    }
    result = run_custom_report(ledger, defn)
    assert result["rows"][0]["value"] == Decimal("100.00")


def test_builtin_trend(db, ledger, account_cash):
    make_txn(ledger, txn_type=TransactionType.INCOME, amount=1000, from_account=account_cash, date=date(2026, 7, 1))
    result = builtin_trend(ledger, months=6)
    assert len(result["rows"]) == 6
    assert sum(r["income"] for r in result["rows"]) == Decimal("1000.00")


def test_builtin_category(db, ledger, account_cash, category_food):
    make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=100, from_account=account_cash, category=category_food)
    result = builtin_category(ledger, "expense", date(2026, 8, 1), date(2026, 8, 31))
    assert result["items"][0]["name"] == "餐饮"
    assert result["total"] == Decimal("100.00")


def test_builtin_cashflow(db, ledger, account_cash):
    make_txn(ledger, txn_type=TransactionType.INCOME, amount=1000, from_account=account_cash, date=date(2026, 7, 1))
    result = builtin_cashflow(ledger, date(2026, 7, 1), date(2026, 7, 31))
    assert result["rows"][0]["income"] == Decimal("1000.00")


def test_report_definition_crud(db, ledger, client_user):
    resp = client_user.post(
        reverse("reports:custom_new", args=[ledger.pk]),
        {
            "name": "我的报表", "date_range_type": "relative", "rel_unit": "month", "rel_value": "3",
            "group_by": "month", "metric": "net", "sort": "metric_desc", "chart": "bar", "limit": "50",
            "is_shared": "on",
        },
    )
    assert resp.status_code == 302
    report = ReportDefinition.objects.get(name="我的报表")
    assert report.definition_json["group_by"] == "month"
    assert report.is_shared

    resp = client_user.get(reverse("reports:custom_view", args=[ledger.pk, report.pk]))
    assert resp.status_code == 200

    resp = client_user.get(reverse("reports:builtin", args=[ledger.pk, "trend"]))
    assert resp.status_code == 200

    resp = client_user.get(reverse("reports:builtin_data", args=[ledger.pk, "trend"]))
    assert resp.status_code == 200
    assert "series" in resp.json()


def test_report_isolation(db, ledger, other_ledger, client_user):
    report = ReportDefinition.objects.create(
        ledger=other_ledger, name="别人的报表", created_by=other_ledger.owner,
        definition_json={"date_range": {"type": "relative"}, "group_by": "month"},
    )
    resp = client_user.get(reverse("reports:custom_view", args=[ledger.pk, report.pk]))
    assert resp.status_code == 404


def test_builtin_refund_report(db, ledger, account_cash, category_food):
    from transactions.models import Category

    make_txn(ledger, txn_type=TransactionType.REFUND, amount=40, from_account=account_cash, category=category_food, date=date(2026, 8, 5))
    make_txn(ledger, txn_type=TransactionType.REIMBURSEMENT, amount=25, from_account=account_cash, category=category_food, date=date(2026, 8, 6))
    result = builtin_refund(ledger, date(2026, 8, 1), date(2026, 8, 31))
    assert result["rows"][0]["name"] == "餐饮"
    assert result["rows"][0]["refund"] == Decimal("40.00")
    assert result["rows"][0]["reimbursement"] == Decimal("25.00")
    assert result["total"] == Decimal("65.00")


def test_builtin_compare_report(db, ledger, account_cash):
    make_txn(ledger, txn_type=TransactionType.INCOME, amount=5000, from_account=account_cash, date=date(2026, 7, 10))
    make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=2000, from_account=account_cash, date=date(2026, 7, 12))
    make_txn(ledger, txn_type=TransactionType.INCOME, amount=6000, from_account=account_cash, date=date(2026, 8, 10))
    make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=2500, from_account=account_cash, date=date(2026, 8, 12))
    make_txn(ledger, txn_type=TransactionType.REFUND, amount=100, from_account=account_cash, date=date(2026, 8, 15))
    result = builtin_compare(ledger, 2026, 8)
    by_label = {r["label"]: r for r in result["rows"]}
    assert by_label["收入"]["this"] == Decimal("6000.00")
    assert by_label["收入"]["last"] == Decimal("5000.00")
    assert by_label["支出"]["this"] == Decimal("2500.00")
    assert by_label["退款报销"]["this"] == Decimal("100.00")
    assert by_label["净额"]["this"] == Decimal("3600.00")


def test_custom_report_refund_bucket(db, ledger, account_cash):
    make_txn(ledger, txn_type=TransactionType.REFUND, amount=70, from_account=account_cash, date=date(2026, 7, 20))
    make_txn(ledger, txn_type=TransactionType.REIMBURSEMENT, amount=30, from_account=account_cash, date=date(2026, 7, 21))
    defn = {
        "date_range": {"type": "absolute", "start": "2026-07-01", "end": "2026-07-31"},
        "types": ["refund", "reimbursement"], "group_by": "month", "metric": "amount",
        "sort": "metric_desc", "chart": "bar", "limit": 50,
    }
    result = run_custom_report(ledger, defn)
    assert result["rows"][0]["value"] == Decimal("100.00")


def test_custom_report_refund_category_grouping(db, ledger, account_cash, category_food):
    make_txn(ledger, txn_type=TransactionType.REFUND, amount=50, from_account=account_cash, category=category_food, date=date(2026, 7, 15))
    defn = {
        "date_range": {"type": "absolute", "start": "2026-07-01", "end": "2026-07-31"},
        "types": ["refund"], "group_by": "category", "metric": "amount",
        "sort": "metric_desc", "chart": "pie", "limit": 50,
    }
    result = run_custom_report(ledger, defn)
    assert result["rows"][0]["label"] == "餐饮"
    assert result["rows"][0]["value"] == Decimal("50.00")


def test_builtin_refund_page_200(db, ledger, client_user, account_cash):
    make_txn(ledger, txn_type=TransactionType.REFUND, amount=10, from_account=account_cash)
    resp = client_user.get(reverse("reports:builtin", args=[ledger.pk, "refund"]))
    assert resp.status_code == 200
    assert "退款" in resp.content.decode()


def test_builtin_compare_page_200(db, ledger, client_user, account_cash):
    make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=100, from_account=account_cash)
    resp = client_user.get(reverse("reports:builtin", args=[ledger.pk, "compare"]))
    assert resp.status_code == 200
    assert "环比" in resp.content.decode()


def test_category_report_drilldown_links(db, ledger, client_user, account_cash, category_food):
    make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=50, from_account=account_cash, category=category_food)
    resp = client_user.get(reverse("reports:builtin", args=[ledger.pk, "category"]))
    assert resp.status_code == 200
    assert f"category={category_food.pk}" in resp.content.decode()


def test_reports_index_lists_ten(db, ledger, client_user):
    resp = client_user.get(reverse("reports:index", args=[ledger.pk]))
    content = resp.content.decode()
    assert "退款/报销统计" in content
    assert "月度收支对比" in content
