"""共享测试夹具。"""
import pytest
from django.test import Client

from accounts.models import User
from core.models import ROLE_ADMIN, ROLE_EDITOR, ROLE_OWNER, ROLE_VIEWER
from ledgers.models import Ledger, LedgerMembership
from transactions.models import Account, Category, Tag, Transaction, TransactionSplit, TransactionType


@pytest.fixture
def user(db):
    return User.objects.create_user("alice", "alice@example.com", "pass1234", display_name="Alice")


@pytest.fixture
def bob(db):
    return User.objects.create_user("bob", "bob@example.com", "pass1234", display_name="Bob")


@pytest.fixture
def carol(db):
    return User.objects.create_user("carol", "carol@example.com", "pass1234", display_name="Carol")


@pytest.fixture
def ledger(user):
    l = Ledger.objects.create(name="家庭账本", owner=user, base_currency="CNY")
    LedgerMembership.objects.create(ledger=l, user=user, role=ROLE_OWNER, invited_by=user)
    return l


@pytest.fixture
def other_ledger(bob):
    l = Ledger.objects.create(name="别人的账本", owner=bob, base_currency="CNY")
    LedgerMembership.objects.create(ledger=l, user=bob, role=ROLE_OWNER, invited_by=bob)
    return l


def add_member(ledger, user, role=ROLE_EDITOR, invited_by=None):
    return LedgerMembership.objects.create(ledger=ledger, user=user, role=role, invited_by=invited_by)


@pytest.fixture
def editor_membership(ledger, bob):
    return add_member(ledger, bob, ROLE_EDITOR)


@pytest.fixture
def viewer_membership(ledger, carol):
    return add_member(ledger, carol, ROLE_VIEWER)


@pytest.fixture
def account_cash(ledger):
    return Account.objects.create(ledger=ledger, name="现金", account_type="cash", opening_balance=0)


@pytest.fixture
def account_bank(ledger):
    return Account.objects.create(ledger=ledger, name="工资卡", account_type="bank", opening_balance=0)


@pytest.fixture
def category_food(ledger):
    return Category.objects.create(ledger=ledger, kind="expense", name="餐饮")


@pytest.fixture
def category_salary(ledger):
    return Category.objects.create(ledger=ledger, kind="income", name="工资")


@pytest.fixture
def tag_family(ledger):
    return Tag.objects.create(ledger=ledger, name="家庭")


def make_txn(
    ledger,
    *,
    txn_type=TransactionType.EXPENSE,
    amount=100,
    from_account=None,
    to_account=None,
    category=None,
    date=None,
    description="",
    currency="CNY",
    exchange_rate=1,
    created_by=None,
    **kwargs,
):
    from datetime import date as d

    from decimal import Decimal

    amount = Decimal(str(amount))
    rate = Decimal(str(exchange_rate))
    if txn_type == TransactionType.ADJUSTMENT and amount < 0:
        amount_base = amount
    else:
        amount_base = (amount * rate).quantize(Decimal("0.01"))
    txn = Transaction(
        ledger=ledger,
        type=txn_type,
        date=date or d(2026, 8, 1),
        amount=amount,
        currency=currency,
        exchange_rate=rate,
        amount_base=amount_base,
        from_account=from_account,
        to_account=to_account,
        category=category,
        description=description,
        created_by=created_by,
        updated_by=created_by,
        **kwargs,
    )
    txn.full_clean(exclude=["created_by", "updated_by", "amount_base", "ledger"])
    txn.save()
    return txn


@pytest.fixture
def client_user(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def client_bob(bob):
    c = Client()
    c.force_login(bob)
    return c


@pytest.fixture
def client_carol(carol):
    c = Client()
    c.force_login(carol)
    return c
