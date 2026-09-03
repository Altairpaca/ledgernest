"""流水、账户、分类、标签、预算表单。"""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Q

from .models import (
    Account,
    Budget,
    BudgetType,
    Category,
    Tag,
    Transaction,
    TransactionSplit,
    TransactionType,
)


def parse_decimal(value, field_name):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise ValidationError({field_name: "请输入有效的数字。"})


class TransactionForm(forms.ModelForm):
    """快速记账表单。

    与 service 层配合：保存前统一计算 amount_base；拆分在 POST 处理中校验。
    """

    split_category_ids = forms.CharField(widget=forms.HiddenInput(), required=False)
    split_amounts = forms.CharField(widget=forms.HiddenInput(), required=False)
    tag_names = forms.CharField(label="标签", required=False, help_text="多个标签用逗号分隔")

    class Meta:
        model = Transaction
        fields = [
            "type", "date", "amount", "currency", "exchange_rate",
            "from_account", "to_account", "category", "counterparty", "description",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "form-input"}),
            "amount": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01", "autofocus": True}),
            "currency": forms.TextInput(attrs={"maxlength": "8", "class": "w-20"}),
            "exchange_rate": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.000001"}),
            "description": forms.TextInput(attrs={"placeholder": "备注（可选）"}),
        }

    def __init__(self, ledger, *args, **kwargs):
        self.ledger = ledger
        super().__init__(*args, **kwargs)
        accounts = Account.objects.filter(ledger=ledger, is_active=True)
        categories = Category.objects.filter(ledger=ledger, is_active=True)
        self.fields["from_account"].queryset = accounts
        self.fields["to_account"].queryset = accounts
        self.fields["category"].queryset = categories
        self.fields["from_account"].label = "账户"
        self.fields["to_account"].label = "目标账户"
        self.fields["category"].label = "分类"
        self.fields["counterparty"].label = "交易对象"
        self.fields["description"].label = "备注"
        self.fields["amount"].label = "金额"
        self.fields["date"].label = "日期"
        self.fields["type"].label = "类型"
        self.fields["currency"].label = "币种"
        self.fields["exchange_rate"].label = "汇率"

    def clean_amount(self):
        amount = parse_decimal(self.cleaned_data.get("amount"), "amount")
        if amount is None:
            raise ValidationError("请输入金额。")
        return amount

    def clean(self):
        cleaned = super().clean()
        txn_type = cleaned.get("type")
        amount = cleaned.get("amount")
        if txn_type and txn_type != TransactionType.ADJUSTMENT and amount is not None and amount <= 0:
            self.add_error("amount", "金额必须大于 0。")
        if txn_type == TransactionType.ADJUSTMENT and amount == 0:
            self.add_error("amount", "调整金额不能为 0。")
        rate = parse_decimal(cleaned.get("exchange_rate"), "exchange_rate")
        if rate is None:
            rate = Decimal("1")
        cleaned["exchange_rate"] = rate
        if txn_type == TransactionType.ADJUSTMENT and amount is not None and amount < 0 and rate != 1:
            self.add_error("exchange_rate", "负向调整不支持多币种换算，请使用基础货币。")
        return cleaned

    def _parse_splits(self, txn: Transaction) -> list[dict]:
        """解析隐藏字段中的拆分数据；返回 [{category_id, amount}]。"""
        cats = (self.cleaned_data.get("split_category_ids") or "").split(",")
        amts = (self.cleaned_data.get("split_amounts") or "").split(",")
        out = []
        for cid, amt in zip(cats, amts):
            cid = cid.strip()
            amt = amt.strip()
            if not cid or not amt:
                continue
            try:
                amount = Decimal(amt)
            except InvalidOperation:
                raise ValidationError("拆分金额格式不正确。")
            if amount <= 0:
                raise ValidationError("拆分金额必须大于 0。")
            out.append({"category_id": int(cid), "amount": amount})
        return out

    def validate_splits(self) -> list[dict]:
        """校验拆分总和等于流水金额；返回有效拆分列表。

        退款/报销/转账/调整不支持拆分，携带拆分数据时直接拒绝。
        """
        txn_type = self.cleaned_data.get("type")
        if txn_type not in (TransactionType.EXPENSE, TransactionType.INCOME):
            if txn_type in (TransactionType.REFUND, TransactionType.REIMBURSEMENT) and (
                self.cleaned_data.get("split_category_ids") or self.cleaned_data.get("split_amounts")
            ):
                raise ValidationError("退款/报销不支持分类拆分。")
            return []
        splits = self._parse_splits(self.instance)
        if not splits:
            return []
        amount = self.cleaned_data.get("amount") or Decimal("0")
        total = sum((s["amount"] for s in splits), Decimal("0"))
        if total != amount:
            raise ValidationError(f"拆分金额合计 {total} 与流水金额 {amount} 不一致。")
        category_ids = [s["category_id"] for s in splits]
        valid_cats = set(
            Category.objects.filter(ledger=self.ledger, id__in=category_ids, is_active=True).values_list(
                "id", flat=True
            )
        )
        for s in splits:
            if s["category_id"] not in valid_cats:
                raise ValidationError("拆分包含无效分类。")
        return splits


class TransactionQuickForm(TransactionForm):
    """快速记账：默认今天、隐藏低频字段。"""


class TransactionFilterForm(forms.Form):
    """流水筛选：全部字段可空。"""

    TYPE_CHOICES = [("", "全部类型")] + list(TransactionType.choices)
    SORT_CHOICES = [("-date", "日期最新"), ("date", "日期最早"), ("-amount", "金额最大"), ("amount", "金额最小")]

    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    keyword = forms.CharField(required=False, max_length=100)
    type = forms.ChoiceField(required=False, choices=TYPE_CHOICES)
    account = forms.ModelChoiceField(required=False, queryset=Account.objects.none())
    category = forms.ModelChoiceField(required=False, queryset=Category.objects.none())
    tag = forms.ModelChoiceField(required=False, queryset=Tag.objects.none())
    created_by = forms.IntegerField(required=False)
    amount_min = forms.DecimalField(required=False, max_digits=18, decimal_places=2)
    amount_max = forms.DecimalField(required=False, max_digits=18, decimal_places=2)
    sort = forms.ChoiceField(required=False, choices=SORT_CHOICES)

    def __init__(self, ledger, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = Account.objects.filter(ledger=ledger, is_active=True)
        self.fields["category"].queryset = Category.objects.filter(ledger=ledger, is_active=True)
        self.fields["tag"].queryset = Tag.objects.filter(ledger=ledger)
        for f in self.fields.values():
            f.label = ""

    def apply(self, qs):
        d = self.cleaned_data
        if d.get("date_from"):
            qs = qs.filter(date__gte=d["date_from"])
        if d.get("date_to"):
            qs = qs.filter(date__lte=d["date_to"])
        if d.get("keyword"):
            kw = d["keyword"]
            qs = qs.filter(
                Q(description__icontains=kw)
                | Q(counterparty__icontains=kw)
                | Q(category__name__icontains=kw)
            )
        if d.get("type"):
            qs = qs.filter(type=d["type"])
        if d.get("account"):
            qs = qs.filter(Q(from_account=d["account"]) | Q(to_account=d["account"]))
        if d.get("category"):
            qs = qs.filter(Q(category=d["category"]) | Q(splits__category=d["category"]))
        if d.get("tag"):
            qs = qs.filter(tags=d["tag"])
        if d.get("created_by"):
            qs = qs.filter(created_by_id=d["created_by"])
        if d.get("amount_min") is not None:
            qs = qs.filter(amount__gte=d["amount_min"])
        if d.get("amount_max") is not None:
            qs = qs.filter(amount__lte=d["amount_max"])
        sort = d.get("sort") or "-date"
        return qs.order_by(sort, "-id") if sort != "date" else qs.order_by("date", "id")


class AccountForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = ["name", "account_type", "currency", "opening_balance", "is_active", "sort_order"]

    def __init__(self, ledger, *args, **kwargs):
        self.ledger = ledger
        super().__init__(*args, **kwargs)
        self.fields["name"].label = "名称"
        self.fields["account_type"].label = "类型"
        self.fields["currency"].label = "币种"
        self.fields["opening_balance"].label = "期初余额"
        self.fields["is_active"].label = "启用"
        self.fields["sort_order"].label = "排序"

    def clean(self):
        cleaned = super().clean()
        name = cleaned.get("name", "").strip()
        if name:
            qs = Account.all_objects.filter(ledger=self.ledger, name=name)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error("name", "同名账户已存在。")
        return cleaned

    def save(self, commit=True):
        inst = super().save(commit=False)
        inst.ledger = self.ledger
        if commit:
            inst.save()
        return inst


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["kind", "name", "parent", "icon", "sort_order", "is_active"]

    def __init__(self, ledger, *args, **kwargs):
        self.ledger = ledger
        super().__init__(*args, **kwargs)
        self.fields["kind"].label = "类型"
        self.fields["name"].label = "名称"
        self.fields["parent"].label = "父分类"
        self.fields["icon"].label = "图标"
        self.fields["sort_order"].label = "排序"
        self.fields["is_active"].label = "启用"
        self.fields["parent"].queryset = Category.objects.filter(ledger=ledger, is_active=True)
        self.fields["parent"].required = False

    def clean_name(self):
        name = self.cleaned_data.get("name", "").strip()
        if not name:
            raise ValidationError("分类名称不能为空。")
        kind = self.cleaned_data.get("kind")
        qs = Category.all_objects.filter(ledger=self.ledger, kind=kind, name=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("同类下同名分类已存在。")
        return name

    def save(self, commit=True):
        inst = super().save(commit=False)
        inst.ledger = self.ledger
        if commit:
            inst.full_clean()
            inst.save()
        return inst


class TagForm(forms.ModelForm):
    class Meta:
        model = Tag
        fields = ["name", "color"]

    def __init__(self, ledger, *args, **kwargs):
        self.ledger = ledger
        super().__init__(*args, **kwargs)
        self.fields["name"].label = "名称"
        self.fields["color"].label = "颜色"

    def save(self, commit=True):
        inst = super().save(commit=False)
        inst.ledger = self.ledger
        if commit:
            inst.save()
        return inst


class BudgetForm(forms.ModelForm):
    class Meta:
        model = Budget
        fields = ["budget_type", "category", "year", "month", "amount"]
        widgets = {"year": forms.NumberInput(attrs={"min": "2000", "max": "2100"}), "month": forms.Select(choices=[(m, f"{m} 月") for m in range(1, 13)])}

    def __init__(self, ledger, *args, **kwargs):
        self.ledger = ledger
        super().__init__(*args, **kwargs)
        self.fields["budget_type"].label = "预算范围"
        self.fields["category"].label = "分类"
        self.fields["year"].label = "年份"
        self.fields["month"].label = "月份"
        self.fields["amount"].label = "预算金额"
        self.fields["category"].queryset = Category.objects.filter(ledger=ledger, is_active=True, kind="expense")
        self.fields["category"].required = False

    def clean(self):
        cleaned = super().clean()
        btype = cleaned.get("budget_type")
        category = cleaned.get("category")
        if btype and btype != BudgetType.TOTAL and category is None:
            self.add_error("category", "分类预算必须选择分类。")
        if btype == BudgetType.TOP_CATEGORY and category and category.parent_id:
            self.add_error("category", "一级分类预算必须选择一级分类。")
        return cleaned

    def save(self, commit=True):
        inst = super().save(commit=False)
        inst.ledger = self.ledger
        if commit:
            inst.save()
        return inst


def default_quick_context():
    """快速记账默认值：今天、最近使用的账户。"""
    return {
        "default_date": date.today(),
        "recent_days": 30,
    }
