"""账户、分类、标签、流水、拆分与预算模型。

金额约定（README 中有完整说明）：
- 流水金额 amount 一律存正数（Decimal），方向由 type 决定；
- 唯一例外是 adjustment（调整），其金额带符号：正数=余额增加，负数=余额减少；
- amount_base 为按汇率折算后的基础货币金额（调整与基础货币流水时 amount_base=amount）；
- 转账不影响账本总资产，只改变账户间分布。
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from core.models import BaseModel, SoftDeleteModel


# ---------------------------------------------------------------------------
# 账户
# ---------------------------------------------------------------------------
class AccountType(models.TextChoices):
    CASH = "cash", "现金"
    BANK = "bank", "银行卡"
    CREDIT = "credit", "信用卡"
    WALLET = "wallet", "数字钱包"
    INVESTMENT = "investment", "投资账户"
    OTHER = "other", "其他"


class Account(SoftDeleteModel):
    """资金账户。已被历史流水使用的账户优先停用而非物理删除。"""

    ledger = models.ForeignKey("ledgers.Ledger", on_delete=models.CASCADE, related_name="accounts")
    name = models.CharField("名称", max_length=64)
    account_type = models.CharField("类型", max_length=16, choices=AccountType.choices, default=AccountType.BANK)
    currency = models.CharField("币种", max_length=8, default=settings.DEFAULT_CURRENCY)
    opening_balance = models.DecimalField("期初余额", max_digits=18, decimal_places=2, default=Decimal("0"))
    is_active = models.BooleanField("启用", default=True)
    sort_order = models.PositiveSmallIntegerField("排序", default=0)

    class Meta:
        verbose_name = "账户"
        verbose_name_plural = "账户"
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["ledger", "name"], name="uniq_account_ledger_name"),
        ]
        indexes = [models.Index(fields=["ledger", "is_active"])]

    def __str__(self):
        return self.name

    def balance(self):
        """账户当前余额（期初 + 全部有效流水影响），集中逻辑见 transactions.services。"""
        from transactions.services import account_balance

        return account_balance(self)


class Category(SoftDeleteModel):
    """分类：属于账本，区分收入/支出，支持父子层级。"""

    KIND_EXPENSE = "expense"
    KIND_INCOME = "income"
    KIND_CHOICES = [(KIND_EXPENSE, "支出"), (KIND_INCOME, "收入")]

    ledger = models.ForeignKey("ledgers.Ledger", on_delete=models.CASCADE, related_name="categories")
    kind = models.CharField("类型", max_length=8, choices=KIND_CHOICES, default=KIND_EXPENSE)
    name = models.CharField("名称", max_length=32)
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="children", verbose_name="父分类"
    )
    icon = models.CharField("图标", max_length=16, blank=True, default="")
    sort_order = models.PositiveSmallIntegerField("排序", default=0)
    is_active = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "分类"
        verbose_name_plural = "分类"
        ordering = ["kind", "sort_order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["ledger", "kind", "name"], name="uniq_category_ledger_kind_name"),
        ]
        indexes = [models.Index(fields=["ledger", "kind", "is_active"])]

    def __str__(self):
        return self.name

    def clean(self):
        if self.parent_id:
            parent = Category.all_objects.filter(pk=self.parent_id).first()
            if parent is None:
                raise ValidationError({"parent": "父分类不存在。"})
            if parent.ledger_id != self.ledger_id:
                raise ValidationError({"parent": "父分类必须属于同一账本。"})
            if parent.kind != self.kind:
                raise ValidationError({"parent": "父分类与子分类的类型必须一致。"})
            if parent.pk == self.pk:
                raise ValidationError({"parent": "分类不能作为自己的父分类。"})
            if self._would_create_cycle(parent):
                raise ValidationError({"parent": "父分类关系会造成循环引用。"})

    def _would_create_cycle(self, parent) -> bool:
        """检查 parent 是否为自身（含子孙）的祖先。"""
        seen = set()
        node = parent
        while node is not None and node.pk not in seen:
            seen.add(node.pk)
            if node.pk == self.pk:
                return True
            node = node.parent
        return False


class Tag(BaseModel):
    """标签：账本内名称唯一。"""

    ledger = models.ForeignKey("ledgers.Ledger", on_delete=models.CASCADE, related_name="tags")
    name = models.CharField("名称", max_length=32)
    color = models.CharField("颜色", max_length=16, blank=True, default="")

    class Meta:
        verbose_name = "标签"
        verbose_name_plural = "标签"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["ledger", "name"], name="uniq_tag_ledger_name"),
        ]

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# 流水
# ---------------------------------------------------------------------------
class TransactionType(models.TextChoices):
    EXPENSE = "expense", "支出"
    INCOME = "income", "收入"
    TRANSFER = "transfer", "转账"
    ADJUSTMENT = "adjustment", "调整"
    REFUND = "refund", "退款"
    REIMBURSEMENT = "reimbursement", "报销"


class Transaction(SoftDeleteModel):
    """一笔流水。转账不计入收支；软删除记录不参与余额与统计。"""

    ledger = models.ForeignKey("ledgers.Ledger", on_delete=models.CASCADE, related_name="transactions")
    type = models.CharField("类型", max_length=16, choices=TransactionType.choices)
    date = models.DateField("日期", db_index=True)
    amount = models.DecimalField("金额", max_digits=18, decimal_places=2)  # 正数（调整可为负）
    currency = models.CharField("原币币种", max_length=8, default=settings.DEFAULT_CURRENCY)
    exchange_rate = models.DecimalField("汇率", max_digits=18, decimal_places=6, default=Decimal("1"))
    amount_base = models.DecimalField("基础币金额", max_digits=18, decimal_places=2)  # 统一计算
    from_account = models.ForeignKey(
        Account, on_delete=models.PROTECT, null=True, blank=True, related_name="outgoing", verbose_name="来源账户"
    )
    to_account = models.ForeignKey(
        Account, on_delete=models.PROTECT, null=True, blank=True, related_name="incoming", verbose_name="目标账户"
    )
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, null=True, blank=True, related_name="transactions", verbose_name="分类"
    )
    counterparty = models.CharField("交易对象", max_length=128, blank=True)
    description = models.CharField("描述", max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+", verbose_name="创建人"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+", verbose_name="修改人"
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="transactions")

    class Meta:
        verbose_name = "流水"
        verbose_name_plural = "流水"
        ordering = ["-date", "-id"]
        indexes = [
            models.Index(fields=["ledger", "date"]),
            models.Index(fields=["ledger", "type", "date"]),
            models.Index(fields=["ledger", "from_account"]),
            models.Index(fields=["ledger", "to_account"]),
            models.Index(fields=["ledger", "category"]),
        ]

    def __str__(self):
        return f"{self.get_type_display()} {self.amount}"

    @property
    def is_transfer(self) -> bool:
        return self.type == TransactionType.TRANSFER

    @property
    def signed_amount(self) -> Decimal:
        """带符号的基础币金额：支出为负，收入/退款/报销/转入为正，调整跟随金额符号。"""
        if self.type == TransactionType.EXPENSE:
            return -self.amount_base
        if self.type == TransactionType.TRANSFER:
            return Decimal("0")
        return self.amount_base

    def clean(self):
        errors = {}
        if self.ledger_id and self.from_account_id:
            if self.from_account.ledger_id != self.ledger_id:
                errors["from_account"] = "账户必须属于同一账本。"
        if self.ledger_id and self.to_account_id:
            if self.to_account.ledger_id != self.ledger_id:
                errors["to_account"] = "账户必须属于同一账本。"
        if self.ledger_id and self.category_id:
            if self.category.ledger_id != self.ledger_id:
                errors["category"] = "分类必须属于同一账本。"
        if self.type in (TransactionType.EXPENSE, TransactionType.INCOME, TransactionType.REFUND, TransactionType.REIMBURSEMENT):
            if not self.from_account:
                errors["from_account"] = "支出/收入/退款/报销必须指定账户。"
            if self.to_account:
                errors["to_account"] = "该类型不能指定目标账户。"
        elif self.type == TransactionType.TRANSFER:
            if not self.from_account or not self.to_account:
                errors["to_account"] = "转账必须同时指定来源账户和目标账户。"
            if self.from_account and self.to_account and self.from_account_id == self.to_account_id:
                errors["to_account"] = "转账的来源账户和目标账户不能相同。"
        elif self.type == TransactionType.ADJUSTMENT:
            if not self.from_account:
                errors["from_account"] = "调整必须指定账户。"
            if self.to_account:
                errors["to_account"] = "调整不能指定目标账户。"
            if self.amount < 0 and self.exchange_rate != 1:
                errors["exchange_rate"] = "负向调整（余额减少）不支持多币种换算，请使用基础货币。"
        if self.amount is not None:
            if self.type != TransactionType.ADJUSTMENT and self.amount <= 0:
                errors["amount"] = "金额必须大于 0。"
            if self.type == TransactionType.ADJUSTMENT and self.amount == 0:
                errors["amount"] = "调整金额不能为 0。"
        if errors:
            raise ValidationError(errors)

    def compute_amount_base(self) -> Decimal:
        """按汇率计算基础币金额（负向调整保持符号）。"""
        if self.type == TransactionType.ADJUSTMENT and self.amount < 0:
            return self.amount
        return (self.amount * self.exchange_rate).quantize(Decimal("0.01"))


class TransactionSplit(BaseModel):
    """将一笔收入/支出拆分到多个分类。启用拆分时主分类可为空，统计基于拆分项。"""

    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name="splits")
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, null=True, blank=True, related_name="splits", verbose_name="分类"
    )
    amount = models.DecimalField("拆分金额", max_digits=18, decimal_places=2)  # 原币金额，正数

    class Meta:
        verbose_name = "流水拆分"
        verbose_name_plural = "流水拆分"
        ordering = ["id"]

    def __str__(self):
        return f"{self.category} {self.amount}"

    def clean(self):
        if self.amount is not None and self.amount <= 0:
            raise ValidationError({"amount": "拆分金额必须大于 0。"})
        if self.transaction_id:
            txn = Transaction.objects.filter(pk=self.transaction_id).first()
            if txn and txn.type in (TransactionType.REFUND, TransactionType.REIMBURSEMENT, TransactionType.TRANSFER, TransactionType.ADJUSTMENT):
                raise ValidationError({"amount": "该流水类型不支持拆分。"})
            if txn and self.category_id and txn.ledger_id != self.category.ledger_id:
                raise ValidationError({"category": "拆分分类必须属于同一账本。"})
        if self.transaction_id and self.amount is not None:
            txn = Transaction.objects.filter(pk=self.transaction_id).first()
            if txn and txn.type in (TransactionType.EXPENSE, TransactionType.INCOME):
                total = (
                    TransactionSplit.objects.filter(transaction_id=self.transaction_id)
                    .exclude(pk=self.pk)
                    .aggregate(s=Sum("amount"))["s"]
                    or Decimal("0")
                )
                total += self.amount
                if total > txn.amount:
                    raise ValidationError({"amount": f"拆分金额合计 {total} 超过流水金额 {txn.amount}。"})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# 预算
# ---------------------------------------------------------------------------
class BudgetType(models.TextChoices):
    TOTAL = "total", "账本总支出"
    CATEGORY = "category", "分类支出"
    TOP_CATEGORY = "top_category", "一级分类支出"


class Budget(BaseModel):
    """按月预算：账本总支出 / 一级分类 / 具体分类。"""

    ledger = models.ForeignKey("ledgers.Ledger", on_delete=models.CASCADE, related_name="budgets")
    budget_type = models.CharField("类型", max_length=16, choices=BudgetType.choices, default=BudgetType.CATEGORY)
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, null=True, blank=True, related_name="budgets", verbose_name="分类"
    )
    year = models.PositiveSmallIntegerField("年份")
    month = models.PositiveSmallIntegerField("月份")
    amount = models.DecimalField("预算金额", max_digits=18, decimal_places=2)

    class Meta:
        verbose_name = "预算"
        verbose_name_plural = "预算"
        ordering = ["-year", "-month", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["ledger", "budget_type", "category", "year", "month"],
                name="uniq_budget_scope",
            )
        ]

    def __str__(self):
        return f"{self.year}-{self.month:02d} {self.get_budget_type_display()} {self.amount}"

    def clean(self):
        if not 1 <= self.month <= 12:
            raise ValidationError({"month": "月份必须是 1-12。"})
        if self.budget_type == BudgetType.TOTAL:
            self.category = None
        elif self.budget_type in (BudgetType.CATEGORY, BudgetType.TOP_CATEGORY) and not self.category:
            raise ValidationError({"category": "分类预算必须指定分类。"})
        if self.category and self.category.ledger_id != self.ledger_id:
            raise ValidationError({"category": "分类必须属于同一账本。"})
        if self.budget_type == BudgetType.TOP_CATEGORY and self.category and self.category.parent_id:
            raise ValidationError({"category": "一级分类预算必须选择一级分类。"})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
