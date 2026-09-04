"""流水与基础数据管理视图：快速记账、列表、详情、编辑、删除、恢复、
账户/分类/标签管理、预算管理。

全部页面经由 ledgers.views._ensure_member 校验成员身份；编辑类操作由
_require_edit 校验角色 >= editor。
"""
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction as db_transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from audit.services import audit_log, record_transaction_change
from core.models import EDIT_ROLES

from ledgers.views import _ensure_member
from .forms import (
    AccountForm,
    BudgetForm,
    CategoryForm,
    TagForm,
    TransactionFilterForm,
    TransactionQuickForm,
)
from .models import (
    Account,
    Budget,
    Category,
    Tag,
    Transaction,
    TransactionSplit,
    TransactionType,
)
from .services import (
    ZERO,
    account_balances_summary,
    budget_status,
    ledger_totals,
    month_range,
)

PAGE_SIZE = 25


def _require_edit(request):
    """编辑权限闸门：owner/admin/editor 可编辑，viewer 只读。"""
    membership = getattr(request, "membership", None)
    if membership is None or membership.role not in EDIT_ROLES:
        return HttpResponseForbidden("只读成员不能修改数据。")
    return None


# ---------------------------------------------------------------------------
# 快速记账
# ---------------------------------------------------------------------------
@login_required
@_ensure_member
def quick_add(request, ledger_pk):
    ledger = request.ledger
    denied = _require_edit(request)
    if denied:
        return denied

    if request.method == "POST":
        form = TransactionQuickForm(ledger, request.POST)
        if form.is_valid():
            txn = form.save(commit=False)
            txn.ledger = ledger
            txn.amount_base = txn.compute_amount_base()
            txn.created_by = request.user
            txn.updated_by = request.user
            try:
                txn.full_clean(exclude=["ledger", "amount_base", "created_by", "updated_by"])
            except ValidationError as exc:
                for msg in exc.messages:
                    form.add_error(None, msg)
                return render_quick_add(request, ledger, form)
            try:
                splits = form.validate_splits()
            except ValidationError as exc:
                for msg in exc.messages:
                    form.add_error(None, msg)
                return render_quick_add(request, ledger, form)
            with db_transaction.atomic():
                txn.save()
                _save_tags(txn, form.cleaned_data.get("tag_names", ""))
                _save_splits(txn, splits)
            record_transaction_change(request.user, txn, "create")
            messages.success(request, "已记一笔。")
            return redirect("transactions:quick_add_done", ledger_pk=ledger.pk, txn_pk=txn.pk)
        return render_quick_add(request, ledger, form)

    form = TransactionQuickForm(ledger, initial={"type": "expense", "date": date.today(), "currency": ledger.base_currency, "exchange_rate": Decimal("1")})
    return render_quick_add(request, ledger, form)


def render_quick_add(request, ledger, form):
    import json

    accounts = list(Account.objects.filter(ledger=ledger, is_active=True).order_by("sort_order", "id"))
    expense_cats = Category.objects.filter(ledger=ledger, kind="expense", is_active=True)
    income_cats = Category.objects.filter(ledger=ledger, kind="income", is_active=True)

    def cat_tree(cats):
        children = {}
        roots = []
        for c in cats:
            children.setdefault(c.parent_id, []).append(c)
            if c.parent_id is None:
                roots.append(c)

        def build(items):
            return [
                {
                    "id": c.id,
                    "name": c.name,
                    "icon": c.icon or "▣",
                    "children": build(children.get(c.id, [])),
                }
                for c in items
            ]

        return build(roots)

    # 最近使用账户（按最近流水排序，去重）
    recent_ids = []
    for t in Transaction.objects.filter(ledger=ledger, from_account__isnull=False).order_by("-date", "-id").values("from_account_id")[:12]:
        if t["from_account_id"] not in recent_ids:
            recent_ids.append(t["from_account_id"])
    account_list = sorted(accounts, key=lambda a: (0 if a.id in recent_ids else 1, recent_ids.index(a.id) if a.id in recent_ids else 0))
    f = form
    data = f.data or {}
    inst = f.instance
    splits = []
    if data.get("split_category_ids"):
        cats = [c for c in data.get("split_category_ids", "").split(",") if c]
        amts = [a for a in data.get("split_amounts", "").split(",") if a]
        for cid, amt in zip(cats, amts):
            try:
                splits.append({"categoryId": int(cid), "amount": amt})
            except ValueError:
                pass
    elif inst.pk and not data:
        splits = [{"categoryId": s.category_id, "amount": str(s.amount)} for s in inst.splits.all()]
    state = {
        "type": data.get("type") or (inst.type if inst and inst.pk else "expense"),
        "amount": data.get("amount", "") if data else (inst.amount if inst and inst.pk else ""),
        "account": data.get("from_account") or (inst.from_account_id if inst and inst.pk else ""),
        "fromAccount": data.get("from_account") or (inst.from_account_id if inst and inst.pk else ""),
        "toAccount": data.get("to_account") or (inst.to_account_id if inst and inst.pk else ""),
        "category": data.get("category") or (inst.category_id if inst and inst.pk else ""),
        "splits": splits,
    }
    return render(
        request,
        "transactions/quick_add.html",
        {
            "ledger": ledger,
            "form": form,
            "quick_state_json": state,
            "accounts_json": [{"id": a.id, "name": a.name} for a in account_list],
            "expense_cats_json": cat_tree(expense_cats),
            "income_cats_json": cat_tree(income_cats),
            "all_tags": Tag.objects.filter(ledger=ledger).order_by("name"),
        },
    )


def _save_tags(txn, tag_names: str):
    txn.tags.clear()
    names = [n.strip() for n in tag_names.split(",") if n.strip()]
    for name in list(dict.fromkeys(names))[:10]:
        tag, _ = Tag.objects.get_or_create(ledger=txn.ledger, name=name)
        txn.tags.add(tag)


def _save_splits(txn, splits):
    TransactionSplit.objects.filter(transaction=txn).delete()
    for s in splits:
        TransactionSplit.objects.create(
            transaction=txn, category_id=s["category_id"], amount=s["amount"]
        )


@login_required
@_ensure_member
def quick_add_done(request, ledger_pk, txn_pk):
    txn = get_object_or_404(
        Transaction.objects.select_related("from_account", "to_account", "category").prefetch_related("tags"),
        pk=txn_pk, ledger=request.ledger,
    )
    return render(request, "transactions/quick_add_done.html", {"ledger": request.ledger, "txn": txn})


# ---------------------------------------------------------------------------
# 流水列表与筛选
# ---------------------------------------------------------------------------
@login_required
@_ensure_member
def transaction_list(request, ledger_pk):
    ledger = request.ledger
    filter_form = TransactionFilterForm(ledger, request.GET or None)
    qs = Transaction.objects.filter(ledger=ledger).select_related(
        "from_account", "to_account", "category", "created_by"
    ).prefetch_related("tags")
    if filter_form.is_valid():
        qs = filter_form.apply(qs)
    totals = qs.aggregate(
        income=Sum("amount_base", filter=Q(type=TransactionType.INCOME)),
        expense=Sum("amount_base", filter=Q(type=TransactionType.EXPENSE)),
        refund=Sum(
            "amount_base",
            filter=Q(type__in=(TransactionType.REFUND, TransactionType.REIMBURSEMENT)),
        ),
    )
    income = totals["income"] or ZERO
    expense = totals["expense"] or ZERO
    refund = totals["refund"] or ZERO
    paginator = Paginator(qs, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    members = list(ledger.memberships.select_related("user").filter(is_active=True))
    qs_args = request.GET.copy()
    qs_args.pop("page", None)
    return render(
        request,
        "transactions/list.html",
        {
            "ledger": ledger,
            "page_obj": page_obj,
            "filter_form": filter_form,
            "income": income,
            "expense": expense,
            "refund_total": refund,
            "net": income - expense + refund,
            "members": members,
            "querystring": qs_args.urlencode(),
            "deleted_count": Transaction.all_objects.filter(ledger=ledger, deleted_at__isnull=False).count(),
            "has_filter": any(filter_form.cleaned_data.values()) if filter_form.is_valid() else False,
        },
    )


@login_required
@_ensure_member
def transaction_detail(request, ledger_pk, txn_pk):
    txn = get_object_or_404(
        Transaction.objects.select_related("from_account", "to_account", "category", "created_by", "updated_by")
        .prefetch_related("tags", "splits__category"),
        pk=txn_pk, ledger=request.ledger,
    )
    return render(request, "transactions/detail.html", {"ledger": request.ledger, "txn": txn})


@login_required
@_ensure_member
def transaction_edit(request, ledger_pk, txn_pk):
    ledger = request.ledger
    denied = _require_edit(request)
    if denied:
        return denied
    txn = get_object_or_404(Transaction.objects.prefetch_related("splits"), pk=txn_pk, ledger=ledger)
    if request.method == "POST":
        form = TransactionQuickForm(ledger, request.POST, instance=txn)
        if form.is_valid():
            txn = form.save(commit=False)
            txn.ledger = ledger
            txn.amount_base = txn.compute_amount_base()
            txn.updated_by = request.user
            try:
                txn.full_clean(exclude=["ledger", "amount_base", "created_by", "updated_by"])
            except ValidationError as exc:
                for msg in exc.messages:
                    form.add_error(None, msg)
                return render_quick_add(request, ledger, form)
            try:
                splits = form.validate_splits()
            except ValidationError as exc:
                for msg in exc.messages:
                    form.add_error(None, msg)
                return render_quick_add(request, ledger, form)
            with db_transaction.atomic():
                txn.save()
                _save_tags(txn, form.cleaned_data.get("tag_names", ""))
                _save_splits(txn, splits)
            record_transaction_change(request.user, txn, "update")
            messages.success(request, "流水已更新。")
            return redirect("transactions:detail", ledger_pk=ledger.pk, txn_pk=txn.pk)
        return render_quick_add(request, ledger, form)
    initial = {
        "tag_names": ", ".join(txn.tags.values_list("name", flat=True)),
    }
    form = TransactionQuickForm(ledger, instance=txn, initial=initial)
    form.fields["amount"].widget.attrs.pop("autofocus", None)
    return render_quick_add(request, ledger, form)


@login_required
@_ensure_member
@require_POST
def transaction_delete(request, ledger_pk, txn_pk):
    denied = _require_edit(request)
    if denied:
        return denied
    txn = get_object_or_404(Transaction, pk=txn_pk, ledger=request.ledger)
    txn.soft_delete()
    record_transaction_change(request.user, txn, "delete")
    messages.success(request, "流水已删除（可在列表底部恢复）。")
    return redirect("transactions:list", ledger_pk=ledger_pk)


@login_required
@_ensure_member
@require_POST
def transaction_restore(request, ledger_pk, txn_pk):
    denied = _require_edit(request)
    if denied:
        return denied
    txn = get_object_or_404(Transaction.all_objects, pk=txn_pk, ledger=request.ledger)
    txn.restore()
    record_transaction_change(request.user, txn, "restore")
    messages.success(request, "流水已恢复。")
    return redirect("transactions:detail", ledger_pk=ledger_pk, txn_pk=txn.pk)


@login_required
@_ensure_member
@require_POST
def transaction_duplicate(request, ledger_pk, txn_pk):
    denied = _require_edit(request)
    if denied:
        return denied
    txn = get_object_or_404(
        Transaction.objects.prefetch_related("tags", "splits"), pk=txn_pk, ledger=request.ledger
    )
    copy = Transaction(
        ledger=txn.ledger, type=txn.type, date=txn.date, amount=txn.amount, currency=txn.currency,
        exchange_rate=txn.exchange_rate, amount_base=txn.amount_base, from_account=txn.from_account,
        to_account=txn.to_account, category=txn.category, counterparty=txn.counterparty,
        description=txn.description, created_by=request.user, updated_by=request.user,
    )
    copy.save()
    copy.tags.set(txn.tags.all())
    for split in txn.splits.all():
        TransactionSplit.objects.create(transaction=copy, category=split.category, amount=split.amount)
    record_transaction_change(request.user, copy, "create")
    messages.success(request, "已复制一笔，可修改后保存。")
    return redirect("transactions:edit", ledger_pk=ledger_pk, txn_pk=copy.pk)


# ---------------------------------------------------------------------------
# 账户管理
# ---------------------------------------------------------------------------
@login_required
@_ensure_member
def account_list(request, ledger_pk):
    denied = _require_edit(request)
    if denied:
        return denied
    ledger = request.ledger
    accounts = list(Account.objects.filter(ledger=ledger).order_by("is_active", "sort_order", "id"))
    items, total = account_balances_summary(ledger)
    by_id = {i["account"].id: i["balance"] for i in items}
    return render(
        request,
        "transactions/accounts.html",
        {"ledger": ledger, "accounts": accounts, "balances": by_id, "total": total},
    )


@login_required
@_ensure_member
def account_edit(request, ledger_pk, account_pk=None):
    ledger = request.ledger
    denied = _require_edit(request)
    if denied:
        return denied
    instance = None
    if account_pk:
        instance = get_object_or_404(Account.all_objects, pk=account_pk, ledger=ledger)
    form = AccountForm(ledger, request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        account = form.save()
        audit_log(
            actor=request.user, ledger=ledger,
            action="update" if account_pk else "create", object_type="account",
            object_id=account.pk, summary=f"账户「{account.name}」{'编辑' if account_pk else '创建'}",
        )
        messages.success(request, "账户已保存。")
        return redirect("transactions:accounts", ledger_pk=ledger.pk)
    return render(request, "transactions/account_form.html", {"ledger": ledger, "form": form, "account": instance})


@login_required
@_ensure_member
@require_POST
def account_toggle(request, ledger_pk, account_pk):
    denied = _require_edit(request)
    if denied:
        return denied
    account = get_object_or_404(Account.all_objects, pk=account_pk, ledger=request.ledger)
    account.is_active = not account.is_active
    account.save(update_fields=["is_active", "updated_at"])
    audit_log(
        actor=request.user, ledger=request.ledger, action="update", object_type="account",
        object_id=account.pk, summary=f"账户「{account.name}」{'停用' if not account.is_active else '启用'}",
    )
    messages.success(request, f"账户「{account.name}」已{'停用' if not account.is_active else '启用'}。")
    return redirect("transactions:accounts", ledger_pk=ledger_pk)


# ---------------------------------------------------------------------------
# 分类管理
# ---------------------------------------------------------------------------
@login_required
@_ensure_member
def category_list(request, ledger_pk):
    denied = _require_edit(request)
    if denied:
        return denied
    ledger = request.ledger
    cats = list(Category.objects.filter(ledger=ledger).select_related("parent").order_by("kind", "sort_order", "id"))

    def flat_with_children(kind):
        pool = [c for c in cats if c.kind == kind]
        children = {}
        for c in pool:
            children.setdefault(c.parent_id, []).append(c)
        out = []
        for c in pool:
            if c.parent_id is None:
                c.children_count = len(children.get(c.id, []))
                out.append(c)
        return out

    return render(
        request,
        "transactions/categories.html",
        {
            "ledger": ledger,
            "kind_groups": [
                ("支出分类", flat_with_children("expense")),
                ("收入分类", flat_with_children("income")),
            ],
        },
    )


def _category_tree(cats):
    """构建层级树。"""
    children = {}
    roots = []
    for c in cats:
        children.setdefault(c.parent_id, []).append(c)
    def walk(parent_id, depth):
        out = []
        for c in children.get(parent_id, []):
            out.append((c, depth, walk(c.id, depth + 1)))
        return out
    return walk(None, 0)


@login_required
@_ensure_member
def category_edit(request, ledger_pk, category_pk=None):
    ledger = request.ledger
    denied = _require_edit(request)
    if denied:
        return denied
    instance = None
    if category_pk:
        instance = get_object_or_404(Category.all_objects, pk=category_pk, ledger=ledger)
    form = CategoryForm(ledger, request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        category = form.save()
        audit_log(
            actor=request.user, ledger=ledger,
            action="update" if category_pk else "create", object_type="category",
            object_id=category.pk, summary=f"分类「{category.name}」{'编辑' if category_pk else '创建'}",
        )
        messages.success(request, "分类已保存。")
        return redirect("transactions:categories", ledger_pk=ledger.pk)
    return render(
        request,
        "transactions/category_form.html",
        {
            "ledger": ledger,
            "form": form,
            "category": instance,
            "icon_set": _icon_set_for(ledger),
        },
    )


def _icon_set_for(ledger):
    """分类图标选择集合：已用图标排前，其余按默认集合补齐。"""
    from core.icons import CATEGORY_ICONS

    used = list(
        Category.objects.filter(ledger=ledger)
        .exclude(icon="")
        .order_by("-updated_at")
        .values_list("icon", flat=True)[:24]
    )
    ordered = []
    for icon in used:
        if icon and icon not in ordered:
            ordered.append(icon)
    for icon in CATEGORY_ICONS:
        if icon not in ordered:
            ordered.append(icon)
    return ordered[:64]


@login_required
@_ensure_member
@require_POST
def category_toggle(request, ledger_pk, category_pk):
    denied = _require_edit(request)
    if denied:
        return denied
    category = get_object_or_404(Category.all_objects, pk=category_pk, ledger=request.ledger)
    category.is_active = not category.is_active
    category.save(update_fields=["is_active", "updated_at"])
    audit_log(
        actor=request.user, ledger=request.ledger, action="update", object_type="category",
        object_id=category.pk, summary=f"分类「{category.name}」{'停用' if not category.is_active else '启用'}",
    )
    messages.success(request, f"分类「{category.name}」已{'停用' if not category.is_active else '启用'}。")
    return redirect("transactions:categories", ledger_pk=ledger_pk)


# ---------------------------------------------------------------------------
# 标签管理
# ---------------------------------------------------------------------------
@login_required
@_ensure_member
def tag_list(request, ledger_pk):
    denied = _require_edit(request)
    if denied:
        return denied
    ledger = request.ledger
    tags = Tag.objects.filter(ledger=ledger).annotate(usage=Count("transactions")).order_by("name")
    return render(request, "transactions/tags.html", {"ledger": ledger, "tags": tags})


@login_required
@_ensure_member
def tag_edit(request, ledger_pk, tag_pk=None):
    ledger = request.ledger
    denied = _require_edit(request)
    if denied:
        return denied
    instance = None
    if tag_pk:
        instance = get_object_or_404(Tag, pk=tag_pk, ledger=ledger)
    form = TagForm(ledger, request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        tag = form.save()
        messages.success(request, "标签已保存。")
        return redirect("transactions:tags", ledger_pk=ledger.pk)
    return render(request, "transactions/tag_form.html", {"ledger": ledger, "form": form, "tag": instance})


@login_required
@_ensure_member
@require_POST
def tag_delete(request, ledger_pk, tag_pk):
    denied = _require_edit(request)
    if denied:
        return denied
    tag = get_object_or_404(Tag, pk=tag_pk, ledger=request.ledger)
    tag.delete()
    messages.success(request, "标签已删除。")
    return redirect("transactions:tags", ledger_pk=ledger_pk)


# ---------------------------------------------------------------------------
# 预算
# ---------------------------------------------------------------------------
@login_required
@_ensure_member
def budget_list(request, ledger_pk):
    denied = _require_edit(request)
    if denied:
        return denied
    ledger = request.ledger
    today = date.today()
    year = int(request.GET.get("year", today.year))
    month = int(request.GET.get("month", today.month))
    if not 1 <= month <= 12:
        month = today.month
    statuses = budget_status(ledger, year, month)
    return render(
        request,
        "transactions/budgets.html",
        {
            "ledger": ledger,
            "year": year,
            "month": month,
            "year_range": range(today.year - 1, today.year + 2),
            "month_range": range(1, 13),
            "statuses": statuses,
            "today": today,
        },
    )


@login_required
@_ensure_member
def budget_edit(request, ledger_pk, budget_pk=None):
    ledger = request.ledger
    denied = _require_edit(request)
    if denied:
        return denied
    instance = None
    if budget_pk:
        instance = get_object_or_404(Budget, pk=budget_pk, ledger=ledger)
    form = BudgetForm(ledger, request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        budget = form.save()
        audit_log(
            actor=request.user, ledger=ledger, action="update" if budget_pk else "create",
            object_type="budget", object_id=budget.pk,
            summary=f"预算 {budget.year}-{budget.month:02d} {budget.amount}",
        )
        messages.success(request, "预算已保存。")
        return redirect("transactions:budgets", ledger_pk=ledger.pk)
    return render(request, "transactions/budget_form.html", {"ledger": ledger, "form": form, "budget": instance})


@login_required
@_ensure_member
@require_POST
def budget_delete(request, ledger_pk, budget_pk):
    denied = _require_edit(request)
    if denied:
        return denied
    budget = get_object_or_404(Budget, pk=budget_pk, ledger=request.ledger)
    budget.delete()
    messages.success(request, "预算已删除。")
    return redirect("transactions:budgets", ledger_pk=ledger_pk)


# ---------------------------------------------------------------------------
# AJAX 辅助
# ---------------------------------------------------------------------------
@login_required
@_ensure_member
def ajax_categories(request, ledger_pk):
    """按类型返回分类列表（快速记账动态分类选择）。"""
    kind = request.GET.get("kind", "expense")
    cats = list(
        Category.objects.filter(ledger=request.ledger, kind=kind, is_active=True).select_related("parent")
    )
    # 保持层级缩进
    children = {}
    roots = []
    for c in cats:
        children.setdefault(c.parent_id, []).append(c)
        if c.parent_id is None:
            roots.append(c)

    def walk(items, depth):
        out = []
        for c in items:
            out.append({"id": c.id, "name": c.name, "depth": depth, "icon": c.icon})
            out.extend(walk(children.get(c.id, []), depth + 1))
        return out

    return JsonResponse({"categories": walk(roots, 0)})


@login_required
@_ensure_member
def calendar_view(request, ledger_pk):
    """流水日历：按月查看每日收支，点击日期跳转当日流水。"""
    from django.db.models import DateField
    from django.db.models.functions import Cast
    from transactions.services import _effective_qs

    ledger = request.ledger
    today = date.today()
    try:
        year, month = (int(x) for x in (request.GET.get("month") or today.strftime("%Y-%m")).split("-"))
        if not (2000 <= year <= 2100 and 1 <= month <= 12):
            raise ValueError
    except (ValueError, AttributeError):
        year, month = today.year, today.month

    import calendar as cal

    start, end = month_range(year, month)
    rows = (
        _effective_qs(ledger, start=start, end=end)
        .filter(type__in=(TransactionType.INCOME, TransactionType.EXPENSE))
        .annotate(day=Cast("date", output_field=DateField()))
        .values("day")
        .annotate(
            income=Sum("amount_base", filter=Q(type=TransactionType.INCOME)),
            expense=Sum("amount_base", filter=Q(type=TransactionType.EXPENSE)),
        )
    )
    by_day = {r["day"]: r for r in rows}

    first_weekday = cal.monthrange(year, month)[0]  # 周一=0
    days_in_month = cal.monthrange(year, month)[1]
    grid = []
    for offset in range(first_weekday):
        grid.append(None)
    for day in range(1, days_in_month + 1):
        d = date(year, month, day)
        r = by_day.get(d, {})
        grid.append(
            {
                "date": d,
                "day": day,
                "is_today": d == today,
                "expense": r.get("expense") or ZERO,
                "income": r.get("income") or ZERO,
            }
        )
    while len(grid) % 7:
        grid.append(None)
    weeks = [grid[i : i + 7] for i in range(0, len(grid), 7)]

    prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    totals = ledger_totals(ledger, start, end)
    return render(
        request,
        "transactions/calendar.html",
        {
            "ledger": ledger,
            "year": year,
            "month": month,
            "weeks": weeks,
            "weekdays": ["一", "二", "三", "四", "五", "六", "日"],
            "prev_month": prev_month,
            "next_month": next_month,
            "totals": totals,
            "is_current": (year, month) == (today.year, today.month),
        },
    )
