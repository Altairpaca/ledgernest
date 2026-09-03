"""seed_demo 演示数据测试：随手记分类体系 + 退款报销演示流水 + 幂等。"""
from django.core.management import call_command

from transactions.models import Category, Transaction, TransactionType

EXPENSE_TOP = {"餐饮", "交通", "购物", "居住", "娱乐", "医疗", "人情", "教育", "通讯", "育儿", "其他"}
INCOME_TOP = {"工资", "奖金", "兼职", "理财", "投资", "红包", "礼金", "退款", "报销", "其他收入"}


def test_seed_creates_shuishouji_categories(db):
    call_command("seed_demo")
    expense_tops = set(
        Category.objects.filter(kind="expense", parent__isnull=True).values_list("name", flat=True)
    )
    income_tops = set(
        Category.objects.filter(kind="income", parent__isnull=True).values_list("name", flat=True)
    )
    assert EXPENSE_TOP.issubset(expense_tops), f"缺少支出大类: {EXPENSE_TOP - expense_tops}"
    assert INCOME_TOP.issubset(income_tops), f"缺少收入分类: {INCOME_TOP - income_tops}"
    # 有子分类
    assert Category.objects.filter(kind="expense", parent__isnull=False).count() > 10


def test_seed_creates_refund_transactions(db):
    call_command("seed_demo")
    assert Transaction.objects.filter(type=TransactionType.REFUND).exists()
    assert Transaction.objects.filter(type=TransactionType.REIMBURSEMENT).exists()


def test_seed_idempotent(db):
    call_command("seed_demo")
    first = Transaction.objects.count()
    call_command("seed_demo")
    assert Transaction.objects.count() == first
