"""退款/报销类型模型层测试（RED 先行）。"""
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from transactions.models import TransactionSplit, TransactionType

from .conftest import make_txn


def test_refund_creation(db, ledger, account_cash, category_food):
    txn = make_txn(ledger, txn_type=TransactionType.REFUND, amount=88, from_account=account_cash, category=category_food)
    assert txn.type == TransactionType.REFUND
    assert txn.amount_base == Decimal("88.00")


def test_reimbursement_creation(db, ledger, account_cash, category_food):
    txn = make_txn(ledger, txn_type=TransactionType.REIMBURSEMENT, amount=120, from_account=account_cash)
    assert txn.type == TransactionType.REIMBURSEMENT


def test_refund_requires_account(db, ledger):
    with pytest.raises(ValidationError):
        make_txn(ledger, txn_type=TransactionType.REFUND, amount=10, from_account=None)


def test_reimbursement_forbids_to_account(db, ledger, account_cash, account_bank):
    with pytest.raises(ValidationError):
        make_txn(
            ledger, txn_type=TransactionType.REIMBURSEMENT, amount=10,
            from_account=account_cash, to_account=account_bank,
        )


def test_refund_negative_amount_rejected(db, ledger, account_cash):
    with pytest.raises(ValidationError):
        make_txn(ledger, txn_type=TransactionType.REFUND, amount=-5, from_account=account_cash)


def test_signed_amount_direction(db, ledger, account_cash):
    refund = make_txn(ledger, txn_type=TransactionType.REFUND, amount=50, from_account=account_cash)
    reimb = make_txn(ledger, txn_type=TransactionType.REIMBURSEMENT, amount=30, from_account=account_cash)
    assert refund.signed_amount == Decimal("50.00")
    assert reimb.signed_amount == Decimal("30.00")


def test_refund_splits_rejected(db, ledger, account_cash, category_food):
    txn = make_txn(ledger, txn_type=TransactionType.REFUND, amount=50, from_account=account_cash, category=category_food)
    with pytest.raises(ValidationError):
        TransactionSplit.objects.create(transaction=txn, category=category_food, amount=Decimal("50"))


def test_reimbursement_splits_rejected(db, ledger, account_cash, category_food):
    txn = make_txn(ledger, txn_type=TransactionType.REIMBURSEMENT, amount=60, from_account=account_cash)
    with pytest.raises(ValidationError):
        TransactionSplit.objects.create(transaction=txn, category=category_food, amount=Decimal("60"))


def test_refund_category_cross_ledger_rejected(db, ledger, other_ledger, account_cash):
    from transactions.models import Category

    foreign = Category.objects.create(ledger=other_ledger, kind="expense", name="外账分类")
    with pytest.raises(ValidationError):
        make_txn(ledger, txn_type=TransactionType.REFUND, amount=10, from_account=account_cash, category=foreign)
