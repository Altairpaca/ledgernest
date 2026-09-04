"""流水、余额、拆分、多币种与数据隔离测试。"""
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from audit.models import AuditLog
from transactions.models import (
    Account,
    Budget,
    BudgetType,
    Category,
    Tag,
    Transaction,
    TransactionSplit,
    TransactionType,
)
from transactions.services import (
    account_balance,
    budget_status,
    budget_spent,
    category_summary,
    ledger_net_worth,
    ledger_totals,
    monthly_series,
    refund_summary,
)

from .conftest import make_txn


# ---------------------------------------------------------------------------
# 创建与校验
# ---------------------------------------------------------------------------
def test_expense_income_transfer_adjustment_creation(db, ledger, account_cash, account_bank, category_food):
    exp = make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=100, from_account=account_cash, category=category_food)
    inc = make_txn(ledger, txn_type=TransactionType.INCOME, amount=500, from_account=account_bank)
    trf = make_txn(ledger, txn_type=TransactionType.TRANSFER, amount=200, from_account=account_cash, to_account=account_bank)
    adj = make_txn(ledger, txn_type=TransactionType.ADJUSTMENT, amount=50, from_account=account_cash)
    neg = make_txn(ledger, txn_type=TransactionType.ADJUSTMENT, amount=-30, from_account=account_cash)
    assert all(isinstance(t.amount_base, Decimal) for t in [exp, inc, trf, adj, neg])


def test_transfer_requires_two_different_accounts(db, ledger, account_cash):
    with pytest.raises(Exception):
        make_txn(ledger, txn_type=TransactionType.TRANSFER, amount=100, from_account=account_cash, to_account=account_cash)


def test_expense_requires_account(db, ledger):
    with pytest.raises(Exception):
        make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=100, from_account=None)


def test_negative_amount_rejected(db, ledger, account_cash):
    with pytest.raises(Exception):
        make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=-5, from_account=account_cash)


# ---------------------------------------------------------------------------
# 余额
# ---------------------------------------------------------------------------
def test_balance_calculation(db, ledger, account_cash, account_bank):
    assert account_balance(account_cash) == Decimal("0.00")
    make_txn(ledger, txn_type=TransactionType.INCOME, amount=1000, from_account=account_cash)
    make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=300, from_account=account_cash)
    make_txn(ledger, txn_type=TransactionType.TRANSFER, amount=200, from_account=account_cash, to_account=account_bank)
    make_txn(ledger, txn_type=TransactionType.ADJUSTMENT, amount=50, from_account=account_cash)
    assert account_balance(account_cash) == Decimal("550.00")
    assert account_balance(account_bank) == Decimal("200.00")
    assert ledger_net_worth(ledger) == Decimal("750.00")


def test_transfer_does_not_change_net_worth(db, ledger, account_cash, account_bank):
    make_txn(ledger, txn_type=TransactionType.TRANSFER, amount=999, from_account=account_cash, to_account=account_bank)
    assert ledger_net_worth(ledger) == Decimal("0.00")


def test_soft_delete_excludes_from_balance(db, ledger, account_cash):
    txn = make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=100, from_account=account_cash)
    assert account_balance(account_cash) == Decimal("-100.00")
    txn.soft_delete()
    assert account_balance(account_cash) == Decimal("0.00")
    txn.restore()
    assert account_balance(account_cash) == Decimal("-100.00")


def test_edit_updates_balance(db, ledger, account_cash):
    txn = make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=100, from_account=account_cash)
    txn.amount = Decimal("250")
    txn.amount_base = Decimal("250.00")
    txn.save()
    assert account_balance(account_cash) == Decimal("-250.00")


# ---------------------------------------------------------------------------
# 拆分
# ---------------------------------------------------------------------------
def test_split_sum_must_equal_amount(db, ledger, account_cash, category_food):
    txn = make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=300, from_account=account_cash)
    TransactionSplit.objects.create(transaction=txn, category=category_food, amount=Decimal("200"))
    # 拆分总和超过流水金额时必须报错
    with pytest.raises(ValidationError):
        TransactionSplit.objects.create(transaction=txn, category=category_food, amount=Decimal("200"))


def test_split_stats_no_double_count(db, ledger, account_cash, category_food):
    from transactions.models import Category

    category_fun = Category.objects.create(ledger=ledger, kind="expense", name="娱乐")
    txn = make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=300, from_account=account_cash, category=category_food)
    TransactionSplit.objects.create(transaction=txn, category=category_food, amount=Decimal("200"))
    TransactionSplit.objects.create(transaction=txn, category=category_fun, amount=Decimal("100"))
    items, total = category_summary(ledger, "expense", date(2026, 8, 1), date(2026, 8, 31))
    by_name = {i["name"]: i["total"] for i in items}
    assert by_name.get("餐饮") == Decimal("200.00")
    assert by_name.get("娱乐") == Decimal("100.00")
    assert total == Decimal("300.00")  # 不重复计算主分类


def test_split_category_must_belong_to_ledger(db, ledger, other_ledger, account_cash):
    from transactions.models import Category

    foreign = Category.objects.create(ledger=other_ledger, kind="expense", name="外账分类")
    txn = make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=100, from_account=account_cash)
    with pytest.raises(ValidationError):
        TransactionSplit.objects.create(transaction=txn, category=foreign, amount=Decimal("50"))


# ---------------------------------------------------------------------------
# 多币种
# ---------------------------------------------------------------------------
def test_multicurrency_base_amount(db, ledger, account_cash):
    txn = make_txn(
        ledger, txn_type=TransactionType.EXPENSE, amount=10, from_account=account_cash,
        currency="USD", exchange_rate=7.2,
    )
    assert txn.amount_base == Decimal("72.00")


def test_multicurrency_totals_use_base(db, ledger, account_cash):
    make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=100, from_account=account_cash)
    make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=10, from_account=account_cash, currency="USD", exchange_rate=7.2)
    totals = ledger_totals(ledger, date(2026, 8, 1), date(2026, 8, 31))
    assert totals["expense"] == Decimal("172.00")


# ---------------------------------------------------------------------------
# 跨账本隔离
# ---------------------------------------------------------------------------
def test_account_cannot_be_reused_across_ledgers(db, ledger, other_ledger):
    Account.objects.create(ledger=other_ledger, name="现金")  # 不同账本同名账户允许
    acc2 = Account.objects.create(ledger=other_ledger, name="现金2")
    with pytest.raises(ValidationError):
        # 流水不能引用其他账本的账户
        make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=10, from_account=acc2)


def test_category_cycle_detection(db, ledger):
    a = Category.objects.create(ledger=ledger, kind="expense", name="A")
    b = Category.objects.create(ledger=ledger, kind="expense", name="B", parent=a)
    c = Category.objects.create(ledger=ledger, kind="expense", name="C", parent=b)
    a.parent = c
    with pytest.raises(ValidationError):
        a.full_clean()


def test_category_parent_must_match_kind(db, ledger, category_salary):
    cat = Category(ledger=ledger, kind="expense", name="X", parent=category_salary)
    with pytest.raises(ValidationError):
        cat.full_clean()


def test_tag_unique_per_ledger(db, ledger, other_ledger):
    from django.db import IntegrityError, transaction

    Tag.objects.create(ledger=ledger, name="家庭")
    with transaction.atomic():
        with pytest.raises(IntegrityError):
            Tag.objects.create(ledger=ledger, name="家庭")
    Tag.objects.create(ledger=other_ledger, name="家庭")  # 其他账本可以


def test_transaction_isolation(db, ledger, other_ledger):
    make_txn(
        other_ledger, txn_type=TransactionType.EXPENSE, amount=999,
        from_account=Account.objects.create(ledger=other_ledger, name="外账现金"),
    )
    assert ledger_totals(ledger)["expense"] == Decimal("0.00")
    assert Transaction.objects.filter(ledger=ledger).count() == 0


# ---------------------------------------------------------------------------
# 流水生命周期
# ---------------------------------------------------------------------------
def test_duplicate_restore_soft_delete(db, ledger, account_cash, client_user):
    txn = make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=100, from_account=account_cash)
    resp = client_user.post(reverse("transactions:duplicate", args=[ledger.pk, txn.pk]))
    assert resp.status_code == 302
    assert Transaction.objects.filter(ledger=ledger).count() == 2
    resp = client_user.post(reverse("transactions:delete", args=[ledger.pk, txn.pk]))
    assert resp.status_code == 302
    assert Transaction.objects.filter(ledger=ledger).count() == 1
    assert Transaction.all_objects.filter(ledger=ledger).count() == 2
    resp = client_user.post(reverse("transactions:restore", args=[ledger.pk, txn.pk]))
    assert resp.status_code == 302
    assert Transaction.objects.filter(ledger=ledger).count() == 2


def test_transaction_changes_audited(db, ledger, account_cash, client_user):
    txn = make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=100, from_account=account_cash)
    client_user.post(reverse("transactions:delete", args=[ledger.pk, txn.pk]))
    assert AuditLog.objects.filter(ledger=ledger, action="delete", object_type="transaction").exists()


def test_quick_add_creates_audit(client_user, ledger, account_cash):
    resp = client_user.post(
        reverse("transactions:quick_add", args=[ledger.pk]),
        {
            "type": "expense", "date": "2026-08-01", "amount": "66", "currency": "CNY",
            "exchange_rate": "1", "from_account": str(account_cash.pk),
        },
    )
    assert resp.status_code == 302
    assert Transaction.objects.filter(ledger=ledger, amount=Decimal("66")).exists()
    assert AuditLog.objects.filter(ledger=ledger, action="create").exists()


def test_quick_add_json_escapes_editor_values(client_user, ledger):
    dangerous = "</script><script>alert(1)</script>"
    Account.objects.create(ledger=ledger, name=dangerous, account_type="cash")
    Category.objects.create(ledger=ledger, kind="expense", name=dangerous)

    response = client_user.get(reverse("transactions:quick_add", args=[ledger.pk]))

    content = response.content.decode()
    assert response.status_code == 200
    assert dangerous not in content
    assert "\\u003C/script\\u003E" in content


def test_dashboard_chart_json_escapes_account_names(client_user, ledger):
    dangerous = "' onmouseover='alert(1)"
    Account.objects.create(ledger=ledger, name=dangerous, account_type="cash", opening_balance=100)

    response = client_user.get(reverse("ledgers:dashboard", args=[ledger.pk]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "data-chart='" not in content
    assert 'id="assets-chart-json" type="application/json"' in content
    assert dangerous in content


def test_quick_add_split_via_form(client_user, ledger, account_cash, category_food):
    from transactions.models import Category

    cat_fun = Category.objects.create(ledger=ledger, kind="expense", name="娱乐")
    resp = client_user.post(
        reverse("transactions:quick_add", args=[ledger.pk]),
        {
            "type": "expense", "date": "2026-08-01", "amount": "300", "currency": "CNY",
            "exchange_rate": "1", "from_account": str(account_cash.pk), "category": "",
            "split_category_ids": f"{category_food.pk},{cat_fun.pk}", "split_amounts": "200,100",
        },
    )
    assert resp.status_code == 302
    txn = Transaction.objects.latest("id")
    assert txn.splits.count() == 2


def test_quick_add_split_mismatch_rejected(client_user, ledger, account_cash, category_food):
    resp = client_user.post(
        reverse("transactions:quick_add", args=[ledger.pk]),
        {
            "type": "expense", "date": "2026-08-01", "amount": "300", "currency": "CNY",
            "exchange_rate": "1", "from_account": str(account_cash.pk),
            "split_category_ids": str(category_food.pk), "split_amounts": "250",
        },
    )
    assert resp.status_code == 200  # 表单错误
    assert Transaction.objects.filter(ledger=ledger).count() == 0


# ---------------------------------------------------------------------------
# 预算
# ---------------------------------------------------------------------------
def test_budget_spent_total(db, ledger, account_cash):
    make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=300, from_account=account_cash, date=date(2026, 8, 10))
    make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=200, from_account=account_cash, date=date(2026, 9, 10))
    assert budget_spent(ledger, 2026, 8) == Decimal("300.00")


def test_budget_spent_includes_children(db, ledger, account_cash):
    parent = Category.objects.create(ledger=ledger, kind="expense", name="餐饮")
    child = Category.objects.create(ledger=ledger, kind="expense", name="外卖", parent=parent)
    make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=80, from_account=account_cash, category=child)
    assert budget_spent(ledger, 2026, 8, category_id=parent.pk) == Decimal("80.00")


def test_budget_status_and_execution(db, ledger, account_cash):
    Budget.objects.create(ledger=ledger, budget_type=BudgetType.TOTAL, year=2026, month=8, amount=Decimal("1000"))
    make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=400, from_account=account_cash)
    statuses = budget_status(ledger, 2026, 8)
    assert len(statuses) == 1
    assert statuses[0]["spent"] == Decimal("400.00")
    assert statuses[0]["remaining"] == Decimal("600.00")


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------
def test_monthly_series_pads_empty_months(db, ledger, account_cash):
    make_txn(ledger, txn_type=TransactionType.INCOME, amount=1000, from_account=account_cash, date=date(2026, 7, 15))
    series = monthly_series(ledger, months=3, end=date(2026, 8, 31))
    assert len(series) == 3
    assert series[-1]["month"] == "2026-08"
    assert series[-2]["income"] == Decimal("1000.00")
    assert series[-1]["income"] == Decimal("0.00")


def test_category_summary_uses_splits(db, ledger, account_cash, category_food):
    make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=100, from_account=account_cash, category=category_food)
    make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=50, from_account=account_cash, category=category_food)
    items, total = category_summary(ledger, "expense", date(2026, 8, 1), date(2026, 8, 31))
    assert total == Decimal("150.00")


def test_calendar_view_renders_200(db, ledger, account_cash, client_user):
    make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=100, from_account=account_cash, date=date(2026, 7, 15))
    resp = client_user.get(reverse("transactions:calendar", args=[ledger.pk]), {"month": "2026-07"})
    assert resp.status_code == 200
    assert "date_from" in resp.content.decode()
    assert "2026-07-15" in resp.content.decode()


# ---------------------------------------------------------------------------
# 退款/报销统计
# ---------------------------------------------------------------------------
def test_ledger_totals_refund_formula(db, ledger, account_cash, account_bank):
    make_txn(ledger, txn_type=TransactionType.INCOME, amount=1000, from_account=account_cash)
    make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=600, from_account=account_cash)
    make_txn(ledger, txn_type=TransactionType.REFUND, amount=100, from_account=account_cash)
    make_txn(ledger, txn_type=TransactionType.REIMBURSEMENT, amount=50, from_account=account_bank)
    totals = ledger_totals(ledger)
    assert totals["income"] == Decimal("1000.00")
    assert totals["expense"] == Decimal("600.00")
    assert totals["refund"] == Decimal("100.00")
    assert totals["reimbursement"] == Decimal("50.00")
    assert totals["refund_total"] == Decimal("150.00")
    assert totals["net"] == Decimal("550.00")


def test_balance_refund_increases(db, ledger, account_cash):
    make_txn(ledger, txn_type=TransactionType.REFUND, amount=100, from_account=account_cash)
    make_txn(ledger, txn_type=TransactionType.REIMBURSEMENT, amount=50, from_account=account_cash)
    assert account_balance(account_cash) == Decimal("150.00")


def test_net_worth_includes_refund(db, ledger, account_cash):
    make_txn(ledger, txn_type=TransactionType.REFUND, amount=80, from_account=account_cash)
    assert ledger_net_worth(ledger) == Decimal("80.00")


def test_category_summary_excludes_refund(db, ledger, account_cash, category_food):
    make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=100, from_account=account_cash, category=category_food)
    make_txn(ledger, txn_type=TransactionType.REFUND, amount=30, from_account=account_cash, category=category_food)
    items, total = category_summary(ledger, "expense", date(2026, 8, 1), date(2026, 8, 31))
    assert total == Decimal("100.00")


def test_monthly_series_refund(db, ledger, account_cash):
    make_txn(ledger, txn_type=TransactionType.REFUND, amount=60, from_account=account_cash, date=date(2026, 7, 10))
    series = monthly_series(ledger, months=3, end=date(2026, 8, 31))
    july = next(r for r in series if r["month"] == "2026-07")
    assert july["refund"] == Decimal("60.00")


def test_refund_summary_service(db, ledger, account_cash, category_food):
    from transactions.models import Category

    cat_fun = Category.objects.create(ledger=ledger, kind="expense", name="娱乐")
    make_txn(ledger, txn_type=TransactionType.REFUND, amount=40, from_account=account_cash, category=category_food)
    make_txn(ledger, txn_type=TransactionType.REIMBURSEMENT, amount=25, from_account=account_cash, category=cat_fun)
    rows = refund_summary(ledger, date(2026, 8, 1), date(2026, 8, 31))
    by_name = {r["name"]: r for r in rows}
    assert by_name["餐饮"]["refund"] == Decimal("40.00")
    assert by_name["娱乐"]["reimbursement"] == Decimal("25.00")


# ---------------------------------------------------------------------------
# 表单层退款/报销
# ---------------------------------------------------------------------------
def test_quick_add_refund_via_form(client_user, ledger, account_cash, category_food):
    resp = client_user.post(
        reverse("transactions:quick_add", args=[ledger.pk]),
        {
            "type": "refund", "date": "2026-08-01", "amount": "88", "currency": "CNY",
            "exchange_rate": "1", "from_account": str(account_cash.pk), "category": str(category_food.pk),
            "description": "退货退款",
        },
    )
    assert resp.status_code == 302
    txn = Transaction.objects.get(type=TransactionType.REFUND)
    assert txn.amount == Decimal("88.00")
    assert account_balance(account_cash) == Decimal("88.00")


def test_quick_add_reimbursement_via_form(client_user, ledger, account_cash):
    resp = client_user.post(
        reverse("transactions:quick_add", args=[ledger.pk]),
        {
            "type": "reimbursement", "date": "2026-08-01", "amount": "50", "currency": "CNY",
            "exchange_rate": "1", "from_account": str(account_cash.pk), "description": "出差报销",
        },
    )
    assert resp.status_code == 302
    assert Transaction.objects.filter(type=TransactionType.REIMBURSEMENT).exists()


def test_quick_add_refund_split_rejected(client_user, ledger, account_cash, category_food):
    resp = client_user.post(
        reverse("transactions:quick_add", args=[ledger.pk]),
        {
            "type": "refund", "date": "2026-08-01", "amount": "50", "currency": "CNY",
            "exchange_rate": "1", "from_account": str(account_cash.pk),
            "split_category_ids": str(category_food.pk), "split_amounts": "50",
        },
    )
    assert resp.status_code == 200
    assert not Transaction.objects.filter(type=TransactionType.REFUND).exists()


def test_filter_type_choices_include_refund(db, ledger):
    from transactions.forms import TransactionFilterForm

    form = TransactionFilterForm(ledger)
    values = [v for v, _ in form.fields["type"].choices]
    assert "refund" in values
    assert "reimbursement" in values
