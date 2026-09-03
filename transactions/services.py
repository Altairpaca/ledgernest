"""余额与统计核心服务。

所有余额、汇总、趋势计算必须经过本模块，页面/报表/导出不得各自复制算法。
规则（与 README 一致）：
- 金额方向：expense 记 -amount_base；income 记 +amount_base；
  transfer 转出记 -、转入记 +，净额不影响账本总资产；adjustment 按金额符号。
- 软删除流水（deleted_at 非空）一律不计入。
- 多币种统一折算为基础币金额（amount_base）。
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, DateField, Q, Sum
from django.db.models.functions import Cast, ExtractMonth, ExtractYear

from .models import Account, Category, Tag, Transaction, TransactionSplit, TransactionType

ZERO = Decimal("0.00")


def _effective_qs(ledger, start=None, end=None, types=None):
    """基准查询集：限定账本、时间范围与类型，排除软删除。"""
    qs = Transaction.objects.filter(ledger=ledger)
    if start is not None:
        qs = qs.filter(date__gte=start)
    if end is not None:
        qs = qs.filter(date__lte=end)
    if types:
        qs = qs.filter(type__in=types)
    return qs


def account_balance(account: Account) -> Decimal:
    """账户余额 = 期初 + 收入 + 退款 + 报销 + 转入 + 正调整 - 支出 - 转出 - 负调整。"""
    ledger = account.ledger
    qs = Transaction.objects.filter(ledger=ledger).exclude(deleted_at__isnull=False)
    income = (
        qs.filter(type=TransactionType.INCOME, from_account=account).aggregate(s=Sum("amount_base"))["s"] or ZERO
    )
    expense = (
        qs.filter(type=TransactionType.EXPENSE, from_account=account).aggregate(s=Sum("amount_base"))["s"] or ZERO
    )
    refund = (
        qs.filter(type__in=(TransactionType.REFUND, TransactionType.REIMBURSEMENT), from_account=account)
        .aggregate(s=Sum("amount_base"))["s"]
        or ZERO
    )
    transfer_in = (
        qs.filter(type=TransactionType.TRANSFER, to_account=account).aggregate(s=Sum("amount_base"))["s"] or ZERO
    )
    transfer_out = (
        qs.filter(type=TransactionType.TRANSFER, from_account=account).aggregate(s=Sum("amount_base"))["s"] or ZERO
    )
    adjustment = (
        qs.filter(type=TransactionType.ADJUSTMENT, from_account=account).aggregate(s=Sum("amount_base"))["s"] or ZERO
    )
    return (
        account.opening_balance + income + refund + transfer_in + adjustment - expense - transfer_out
    ).quantize(Decimal("0.01"))


def ledger_totals(ledger, start: date | None = None, end: date | None = None) -> dict:
    """账本在 [start, end] 范围内的收入 / 支出 / 退款报销 / 净额（基础币）。

    净额 = 收入 - 支出 + 退款 + 报销；退款/报销单列，不并入收入/支出。
    """
    qs = _effective_qs(ledger, start, end)
    agg = qs.aggregate(
        income=Sum("amount_base", filter=Q(type=TransactionType.INCOME)),
        expense=Sum("amount_base", filter=Q(type=TransactionType.EXPENSE)),
        refund=Sum("amount_base", filter=Q(type=TransactionType.REFUND)),
        reimbursement=Sum("amount_base", filter=Q(type=TransactionType.REIMBURSEMENT)),
    )
    income = agg["income"] or ZERO
    expense = agg["expense"] or ZERO
    refund = agg["refund"] or ZERO
    reimbursement = agg["reimbursement"] or ZERO
    refund_total = refund + reimbursement
    return {
        "income": income,
        "expense": expense,
        "refund": refund,
        "reimbursement": reimbursement,
        "refund_total": refund_total,
        "net": (income - expense + refund_total).quantize(Decimal("0.01")),
        "count": qs.count(),
    }


def ledger_net_worth(ledger) -> Decimal:
    """账本总资产 = 所有启用账户余额之和（转账在账户间抵消，不影响总和）。"""
    total = ZERO
    for account in Account.objects.filter(ledger=ledger, is_active=True):
        total += account_balance(account)
    return total.quantize(Decimal("0.01"))


def monthly_series(ledger, months: int = 6, end: date | None = None) -> list[dict]:
    """最近 N 个月（含当月）逐月收入/支出/净额，不足数据的月份补 0。"""
    end = end or date.today()
    # 每月最后一天
    start = (end.replace(day=1) - timedelta(days=1)).replace(day=1)  # 上上月1号 -> 实际取 (months-1) 个月前
    start = (start.replace(day=1) + timedelta(days=32)).replace(day=1)
    # 简化：从 end 往前推 months-1 个月的月初
    year, month = end.year, end.month
    firsts = []
    for i in range(months - 1, -1, -1):
        y, m = (year, month - i) if month - i >= 1 else (year - 1, month - i + 12)
        firsts.append(date(y, m, 1))
    start = firsts[0]

    rows = (
        _effective_qs(ledger, start=start, end=end)
        .filter(type__in=(TransactionType.INCOME, TransactionType.EXPENSE, TransactionType.REFUND, TransactionType.REIMBURSEMENT))
        .annotate(y=ExtractYear("date"), m=ExtractMonth("date"))
        .values("y", "m")
        .annotate(
            income=Sum("amount_base", filter=Q(type=TransactionType.INCOME)),
            expense=Sum("amount_base", filter=Q(type=TransactionType.EXPENSE)),
            refund=Sum("amount_base", filter=Q(type=TransactionType.REFUND)),
            reimbursement=Sum("amount_base", filter=Q(type=TransactionType.REIMBURSEMENT)),
        )
    )
    by_month = {date(r["y"], r["m"], 1): r for r in rows}
    out = []
    for first in firsts:
        row = by_month.get(first, {})
        income = row.get("income") or ZERO
        expense = row.get("expense") or ZERO
        refund = row.get("refund") or ZERO
        reimbursement = row.get("reimbursement") or ZERO
        out.append(
            {
                "month": first.strftime("%Y-%m"),
                "label": first.strftime("%Y年%m月"),
                "income": income,
                "expense": expense,
                "refund": refund,
                "reimbursement": reimbursement,
                "refund_total": refund + reimbursement,
                "net": (income - expense + refund + reimbursement).quantize(Decimal("0.01")),
            }
        )
    return out


def category_summary(ledger, kind: str, start: date | None = None, end: date | None = None, limit: int = 8):
    """分类汇总：优先使用拆分项，主分类只统计未拆分的流水，防止重复计算。"""
    txn_types = [TransactionType.EXPENSE] if kind == "expense" else [TransactionType.INCOME]
    qs = _effective_qs(ledger, start, end, types=txn_types)

    # 有拆分的流水：按拆分分类聚合
    split_rows = (
        TransactionSplit.objects.filter(transaction__in=qs)
        .values("category_id")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )
    # 未拆分的流水：按主分类聚合
    no_split_ids = qs.filter(splits__isnull=True).values("id")
    main_rows = (
        qs.filter(id__in=no_split_ids, category__isnull=False)
        .values("category_id")
        .annotate(total=Sum("amount_base"))
        .order_by("-total")
    )
    totals: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for row in split_rows:
        if row["category_id"]:
            totals[row["category_id"]] += row["total"] or ZERO
    for row in main_rows:
        totals[row["category_id"]] += row["total"] or ZERO

    cats = {c.id: c for c in Category.objects.filter(ledger=ledger, kind=kind)}
    items = []
    for cid, total in sorted(totals.items(), key=lambda kv: -kv[1])[:limit]:
        cat = cats.get(cid)
        if cat is None:
            continue
        items.append(
            {
                "category": cat,
                "name": cat.name,
                "icon": cat.icon,
                "total": total.quantize(Decimal("0.01")),
            }
        )
    grand = sum((i["total"] for i in items), ZERO)
    for item in items:
        item["percent"] = float(item["total"] / grand * 100) if grand else 0.0
    return items, grand.quantize(Decimal("0.01"))


def account_balances_summary(ledger):
    """所有账户余额（按类型分组），供首页与账户页使用。"""
    accounts = list(Account.objects.filter(ledger=ledger).order_by("sort_order", "id"))
    items = [
        {
            "account": acc,
            "balance": account_balance(acc),
        }
        for acc in accounts
    ]
    total = sum((i["balance"] for i in items), ZERO)
    return items, total.quantize(Decimal("0.01"))


def member_summary(ledger, start: date | None = None, end: date | None = None, limit: int = 10):
    """成员记账汇总：按创建人统计收支笔数与金额。"""
    qs = _effective_qs(ledger, start, end, types=(TransactionType.INCOME, TransactionType.EXPENSE))
    rows = (
        qs.values("created_by")
        .annotate(
            count=Count("id"),
            income=Sum("amount_base", filter=Q(type=TransactionType.INCOME)),
            expense=Sum("amount_base", filter=Q(type=TransactionType.EXPENSE)),
        )
        .order_by("-count")[:limit]
    )
    from accounts.models import User

    users = {u.id: u for u in User.objects.filter(id__in=[r["created_by"] for r in rows if r["created_by"]])}
    out = []
    for r in rows:
        if not r["created_by"]:
            continue
        out.append(
            {
                "user": users.get(r["created_by"]),
                "count": r["count"],
                "income": r["income"] or ZERO,
                "expense": r["expense"] or ZERO,
            }
        )
    return out


def tag_summary(ledger, start: date | None = None, end: date | None = None, limit: int = 10):
    """标签汇总：通过 M2M 关联统计金额（按基础币）。"""
    qs = _effective_qs(ledger, start, end, types=(TransactionType.INCOME, TransactionType.EXPENSE))
    rows = (
        Transaction.tags.through.objects.filter(transaction__in=qs)
        .values("tag_id")
        .annotate(
            count=Count("id"),
            income=Sum("transaction__amount_base", filter=Q(transaction__type=TransactionType.INCOME)),
            expense=Sum("transaction__amount_base", filter=Q(transaction__type=TransactionType.EXPENSE)),
        )
        .order_by("-count")[:limit]
    )
    from .models import Tag

    tags = {t.id: t for t in Tag.objects.filter(id__in=[r["tag_id"] for r in rows])}
    out = []
    for r in rows:
        tag = tags.get(r["tag_id"])
        if tag is None:
            continue
        out.append(
            {
                "tag": tag,
                "count": r["count"],
                "income": r["income"] or ZERO,
                "expense": r["expense"] or ZERO,
            }
        )
    return out


def counterparty_summary(ledger, start: date | None = None, end: date | None = None, limit: int = 10):
    """交易对象汇总。"""
    qs = _effective_qs(ledger, start, end, types=(TransactionType.INCOME, TransactionType.EXPENSE)).exclude(
        counterparty=""
    )
    rows = (
        qs.values("counterparty")
        .annotate(
            count=Count("id"),
            income=Sum("amount_base", filter=Q(type=TransactionType.INCOME)),
            expense=Sum("amount_base", filter=Q(type=TransactionType.EXPENSE)),
        )
        .order_by("-count")[:limit]
    )
    return [
        {
            "counterparty": r["counterparty"],
            "count": r["count"],
            "income": r["income"] or ZERO,
            "expense": r["expense"] or ZERO,
        }
        for r in rows
    ]


def cashflow_by_day(ledger, start: date, end: date):
    """逐日收支（月度现金流报表用）。"""
    rows = (
        _effective_qs(ledger, start=start, end=end)
        .filter(type__in=(TransactionType.INCOME, TransactionType.EXPENSE))
        .annotate(day=Cast("date", output_field=DateField()))
        .values("day")
        .annotate(
            income=Sum("amount_base", filter=Q(type=TransactionType.INCOME)),
            expense=Sum("amount_base", filter=Q(type=TransactionType.EXPENSE)),
        )
        .order_by("day")
    )
    return rows


def refund_summary(ledger, start: date | None = None, end: date | None = None):
    """退款/报销分类汇总：按分类聚合退款与报销金额。"""
    qs = _effective_qs(
        ledger, start, end, types=(TransactionType.REFUND, TransactionType.REIMBURSEMENT)
    ).filter(category__isnull=False)
    rows = (
        qs.values("category_id")
        .annotate(
            refund=Sum("amount_base", filter=Q(type=TransactionType.REFUND)),
            reimbursement=Sum("amount_base", filter=Q(type=TransactionType.REIMBURSEMENT)),
            count=Count("id"),
        )
        .order_by("-refund", "-reimbursement")
    )
    cats = {c.id: c for c in Category.objects.filter(ledger=ledger)}
    out = []
    for r in rows:
        cat = cats.get(r["category_id"])
        if cat is None:
            continue
        refund = r["refund"] or ZERO
        reimbursement = r["reimbursement"] or ZERO
        out.append(
            {
                "category": cat,
                "name": cat.name,
                "icon": cat.icon,
                "refund": refund,
                "reimbursement": reimbursement,
                "total": (refund + reimbursement).quantize(Decimal("0.01")),
                "count": r["count"],
            }
        )
    return out


def daily_balances(ledger, start: date, end: date, accounts=None):
    """每日账户余额曲线（账户汇总报表）。实现为按日聚合各账户变动。"""
    qs = _effective_qs(ledger, start=start, end=end)
    if accounts is not None:
        qs = qs.filter(Q(from_account__in=accounts) | Q(to_account__in=accounts))
    deltas = defaultdict(lambda: defaultdict(Decimal))
    for txn in qs.select_related("from_account", "to_account"):
        if txn.type == TransactionType.EXPENSE:
            deltas[txn.date][txn.from_account_id] -= txn.amount_base
        elif txn.type in (TransactionType.INCOME, TransactionType.REFUND, TransactionType.REIMBURSEMENT):
            deltas[txn.date][txn.from_account_id] += txn.amount_base
        elif txn.type == TransactionType.TRANSFER:
            deltas[txn.date][txn.from_account_id] -= txn.amount_base
            deltas[txn.date][txn.to_account_id] += txn.amount_base
        elif txn.type == TransactionType.ADJUSTMENT:
            deltas[txn.date][txn.from_account_id] += txn.amount_base
    return deltas


def budget_spent(ledger, year: int, month: int, category_id=None) -> Decimal:
    """当月某范围支出（预算执行用）。

    - 总预算：当月全部支出；
    - 分类预算：该分类及其全部子孙分类当月支出（口径统一，避免重复）。
    """
    from .models import Category

    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)

    qs = _effective_qs(ledger, start=start, end=end, types=[TransactionType.EXPENSE])

    if category_id is not None:
        ids = {category_id}
        queue = list(Category.objects.filter(ledger=ledger, parent_id__in=ids).values_list("id", flat=True))
        while queue:
            new = list(
                Category.objects.filter(ledger=ledger, parent_id__in=queue).values_list("id", flat=True)
            )
            ids.update(queue)
            queue = new
        # 有拆分按拆分分类；未拆分按主分类
        split_total = (
            qs.filter(splits__category_id__in=ids)
            .annotate(split_amount=Sum("splits__amount"))
            .aggregate(s=Sum("splits__amount"))["s"]
            or ZERO
        )
        no_split = (
            qs.filter(splits__isnull=True, category_id__in=ids).aggregate(s=Sum("amount_base"))["s"] or ZERO
        )
        return (split_total + no_split).quantize(Decimal("0.01"))

    return (qs.aggregate(s=Sum("amount_base"))["s"] or ZERO).quantize(Decimal("0.01"))


def budget_status(ledger, year: int, month: int) -> list[dict]:
    """当月预算执行状态列表。"""
    from .models import Budget, BudgetType, Category

    budgets = list(Budget.objects.filter(ledger=ledger, year=year, month=month))
    out = []
    for b in budgets:
        if b.budget_type == BudgetType.TOTAL:
            spent = budget_spent(ledger, year, month)
            label = "账本总支出"
        elif b.budget_type == BudgetType.TOP_CATEGORY:
            spent = budget_spent(ledger, year, month, category_id=b.category_id)
            label = f"一级分类：{b.category.name}"
        else:
            spent = budget_spent(ledger, year, month, category_id=b.category_id)
            label = f"分类：{b.category.name}"
        percent = float(spent / b.amount * 100) if b.amount else 0.0
        out.append(
            {
                "budget": b,
                "label": label,
                "spent": spent,
                "amount": b.amount,
                "remaining": (b.amount - spent).quantize(Decimal("0.01")),
                "percent": percent,
            }
        )
    return out


def month_range(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end
