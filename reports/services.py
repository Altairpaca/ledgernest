"""报表引擎：内置报表执行 + 自定义报表（白名单校验 + ORM 聚合）。

安全边界：所有维度/指标/排序均来自白名单，通过 ORM 构建查询，
禁止执行任何用户输入 SQL。definition_json 经 validate_definition 归一化。
"""
import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, DateField, F, Q, Sum
from django.db.models.functions import Cast
from django.db.models.functions import ExtractMonth, ExtractYear

from transactions.models import Transaction, TransactionSplit, TransactionType
from transactions.services import ZERO, ledger_totals, month_range

# ---------------------------------------------------------------------------
# 白名单
# ---------------------------------------------------------------------------
GROUP_BY_WHITELIST = {
    "month", "day", "category", "parent_category", "account", "tag", "member", "counterparty", "type",
}
METRIC_WHITELIST = {"amount", "income", "expense", "net", "count", "avg"}
CHART_WHITELIST = {"none", "line", "bar", "pie"}
SORT_WHITELIST = {"metric_desc", "metric_asc", "label_asc", "label_desc"}
TYPE_WHITELIST = {t for t, _ in TransactionType.choices}
RELATIVE_UNITS = {"month", "year"}

DEFAULT_DEFINITION = {
    "date_range": {"type": "relative", "months": 3},
    "types": [],
    "account_ids": [],
    "category_ids": [],
    "tag_ids": [],
    "member_ids": [],
    "group_by": "month",
    "metric": "net",
    "sort": "metric_desc",
    "chart": "bar",
    "limit": 50,
}


class DefinitionError(ValueError):
    pass


def validate_definition(defn) -> dict:
    """校验并归一化报表定义，非法字段抛 DefinitionError。"""
    if not isinstance(defn, dict):
        raise DefinitionError("报表定义必须是 JSON 对象。")

    def as_int_list(key):
        val = defn.get(key, [])
        if not isinstance(val, list) or not all(isinstance(x, int) for x in val):
            raise DefinitionError(f"{key} 必须是整数数组。")
        return val

    out = dict(DEFAULT_DEFINITION)
    dr = defn.get("date_range", DEFAULT_DEFINITION["date_range"])
    if not isinstance(dr, dict):
        raise DefinitionError("date_range 必须是对象。")
    dr_type = dr.get("type", "relative")
    if dr_type == "relative":
        unit = dr.get("unit", "month")
        if unit not in RELATIVE_UNITS:
            raise DefinitionError("相对日期单位仅支持 month/year。")
        value = int(dr.get("value", 3))
        if value < 1 or value > 120:
            raise DefinitionError("相对日期范围必须在 1-120 之间。")
        out["date_range"] = {"type": "relative", "unit": unit, "value": value}
    elif dr_type == "absolute":
        try:
            start = date.fromisoformat(str(dr.get("start", "")))
            end = date.fromisoformat(str(dr.get("end", "")))
        except ValueError:
            raise DefinitionError("绝对日期格式必须为 YYYY-MM-DD。")
        if start > end:
            raise DefinitionError("开始日期不能晚于结束日期。")
        out["date_range"] = {"type": "absolute", "start": start.isoformat(), "end": end.isoformat()}
    else:
        raise DefinitionError("date_range.type 仅支持 relative/absolute。")

    types = defn.get("types", [])
    if not isinstance(types, list) or not set(types).issubset(TYPE_WHITELIST):
        raise DefinitionError("types 必须是合法流水类型数组。")
    out["types"] = types

    out["account_ids"] = as_int_list("account_ids")
    out["category_ids"] = as_int_list("category_ids")
    out["tag_ids"] = as_int_list("tag_ids")
    out["member_ids"] = as_int_list("member_ids")

    group_by = defn.get("group_by", "month")
    if group_by not in GROUP_BY_WHITELIST:
        raise DefinitionError(f"group_by 必须是白名单维度之一：{sorted(GROUP_BY_WHITELIST)}。")
    out["group_by"] = group_by

    metric = defn.get("metric", "net")
    if metric not in METRIC_WHITELIST:
        raise DefinitionError(f"metric 必须是白名单指标之一：{sorted(METRIC_WHITELIST)}。")
    out["metric"] = metric

    sort = defn.get("sort", "metric_desc")
    if sort not in SORT_WHITELIST:
        raise DefinitionError(f"sort 必须是白名单排序之一：{sorted(SORT_WHITELIST)}。")
    out["sort"] = sort

    chart = defn.get("chart", "bar")
    if chart not in CHART_WHITELIST:
        raise DefinitionError(f"chart 必须是白名单图表之一：{sorted(CHART_WHITELIST)}。")
    out["chart"] = chart

    limit = int(defn.get("limit", 50))
    if limit < 1 or limit > 200:
        raise DefinitionError("limit 必须在 1-200 之间。")
    out["limit"] = limit
    return out


def resolve_date_range(ledger, defn: dict) -> tuple[date, date]:
    dr = defn["date_range"]
    if dr["type"] == "absolute":
        return date.fromisoformat(dr["start"]), date.fromisoformat(dr["end"])
    today = date.today()
    if dr["unit"] == "year":
        return today.replace(month=1, day=1), today
    start = today.replace(day=1)
    for _ in range(dr["value"] - 1):
        if start.month == 1:
            start = start.replace(year=start.year - 1, month=12)
        else:
            start = start.replace(month=start.month - 1)
    return start, today


def _base_qs(ledger, defn: dict, start: date, end: date):
    qs = Transaction.objects.filter(ledger=ledger, date__gte=start, date__lte=end)
    if defn["types"]:
        qs = qs.filter(type__in=defn["types"])
    if defn["account_ids"]:
        qs = qs.filter(Q(from_account_id__in=defn["account_ids"]) | Q(to_account_id__in=defn["account_ids"]))
    if defn["category_ids"]:
        qs = qs.filter(
            Q(category_id__in=defn["category_ids"]) | Q(splits__category_id__in=defn["category_ids"])
        )
    if defn["tag_ids"]:
        qs = qs.filter(tags__id__in=defn["tag_ids"])
    if defn["member_ids"]:
        qs = qs.filter(created_by_id__in=defn["member_ids"])
    if defn["category_ids"] or defn["tag_ids"]:
        return qs.distinct()
    return qs


def _finalize_rows(rows: list[dict], defn: dict) -> list[dict]:
    """按 metric 计算最终值、排序、截断。"""
    metric = defn["metric"]
    for row in rows:
        income = row.get("income") or ZERO
        expense = row.get("expense") or ZERO
        refund = row.get("refund") or ZERO
        count = row.get("count") or 0
        row["income"] = income
        row["expense"] = expense
        row["refund"] = refund
        if metric == "income":
            row["value"] = income
        elif metric == "expense":
            row["value"] = expense
        elif metric == "net":
            row["value"] = income - expense + refund
        elif metric == "count":
            row["value"] = count
        elif metric == "avg":
            row["value"] = (income + expense + refund) / count if count else ZERO
        else:  # amount = 收入 + 支出 + 退款报销（支出取正）
            row["value"] = income + expense + refund
        row["value"] = Decimal(row["value"]).quantize(Decimal("0.01"))
    sort = defn["sort"]
    if sort == "metric_desc":
        rows.sort(key=lambda r: -r["value"])
    elif sort == "metric_asc":
        rows.sort(key=lambda r: r["value"])
    elif sort == "label_asc":
        rows.sort(key=lambda r: str(r["label"]))
    else:
        rows.sort(key=lambda r: -len(str(r["label"])))
        rows.sort(key=lambda r: str(r["label"]), reverse=True)
    return rows[: defn["limit"]]


def run_custom_report(ledger, defn: dict) -> dict:
    """执行自定义报表：返回 {rows, total, has_chart_data}。"""
    defn = validate_definition(defn)
    start, end = resolve_date_range(ledger, defn)
    group_by = defn["group_by"]
    qs = _base_qs(ledger, defn, start, end)

    if group_by in ("category", "parent_category"):
        rows = _run_category_grouping(ledger, defn, qs, start, end)
    else:
        rows = _run_direct_grouping(ledger, defn, qs, group_by)

    if group_by in ("month", "day"):
        rows = _fill_date_gaps(rows, group_by, start, end)

    rows = _finalize_rows(rows, defn)
    total = sum((r["value"] for r in rows), ZERO)
    return {"rows": rows, "total": total, "start": start, "end": end, "definition": defn}


def _run_direct_grouping(ledger, defn, qs, group_by):
    """直接按字段分组的通用路径：month/day/type/member/counterparty/account/tag。"""
    if group_by == "month":
        return _run_month_grouping(ledger, defn, qs)
    elif group_by == "day":
        qs = qs.annotate(key=Cast("date", output_field=DateField()))
    elif group_by == "type":
        qs = qs.annotate(key=F("type"))
    elif group_by == "member":
        qs = qs.annotate(key=F("created_by"))
    elif group_by == "counterparty":
        qs = qs.exclude(counterparty="").annotate(key=F("counterparty"))
    elif group_by == "account":
        qs = qs.exclude(type=TransactionType.TRANSFER).exclude(from_account__isnull=True).annotate(key=F("from_account"))
    elif group_by == "tag":
        return _run_tag_grouping(ledger, defn, qs)
    else:
        raise DefinitionError(f"不支持的维度：{group_by}")

    agg = (
        qs.values("key")
        .annotate(
            income=Sum("amount_base", filter=Q(type=TransactionType.INCOME)),
            expense=Sum("amount_base", filter=Q(type=TransactionType.EXPENSE)),
            refund=Sum(
                "amount_base",
                filter=Q(type__in=(TransactionType.REFUND, TransactionType.REIMBURSEMENT)),
            ),
            count=Count("id", distinct=True),
        )
    )
    labels = {
        "month": lambda k: k.strftime("%Y-%m"),
        "day": lambda k: k.strftime("%Y-%m-%d"),
        "type": lambda k: TransactionType(k).label if k else "",
        "member": lambda k: _user_label(k),
        "counterparty": lambda k: k,
        "account": lambda k: _account_label(k),
    }
    rows = []
    for r in agg:
        if r["key"] is None:
            continue
        rows.append({"label": labels[group_by](r["key"]), "income": r["income"], "expense": r["expense"], "count": r["count"]})
    return rows


def _run_month_grouping(ledger, defn, qs):
    """按月分组：ExtractYear/ExtractMonth 跨库聚合，label 为 YYYY-MM。"""
    rows = (
        qs.annotate(y=ExtractYear("date"), m=ExtractMonth("date"))
        .values("y", "m")
        .annotate(
            income=Sum("amount_base", filter=Q(type=TransactionType.INCOME)),
            expense=Sum("amount_base", filter=Q(type=TransactionType.EXPENSE)),
            refund=Sum(
                "amount_base",
                filter=Q(type__in=(TransactionType.REFUND, TransactionType.REIMBURSEMENT)),
            ),
            count=Count("id", distinct=True),
        )
    )
    out = []
    for r in rows:
        out.append(
            {
                "label": f"{r['y']}-{r['m']:02d}",
                "income": r["income"],
                "expense": r["expense"],
                "refund": r["refund"],
                "count": r["count"],
            }
        )
    return out


def _run_tag_grouping(ledger, defn, qs):
    rows = (
        Transaction.tags.through.objects.filter(transaction__in=qs)
        .values("tag_id")
        .annotate(
            income=Sum("transaction__amount_base", filter=Q(transaction__type=TransactionType.INCOME)),
            expense=Sum("transaction__amount_base", filter=Q(transaction__type=TransactionType.EXPENSE)),
            refund=Sum(
                "transaction__amount_base",
                filter=Q(transaction__type__in=(TransactionType.REFUND, TransactionType.REIMBURSEMENT)),
            ),
            count=Count("transaction_id", distinct=True),
        )
    )
    from transactions.models import Tag

    tags = {t.id: t.name for t in Tag.objects.filter(ledger=ledger)}
    out = []
    for r in rows:
        name = tags.get(r["tag_id"])
        if name is None:
            continue
        out.append(
            {"label": name, "income": r["income"], "expense": r["expense"], "refund": r["refund"], "count": r["count"]}
        )
    return out


def _run_category_grouping(ledger, defn, qs, start, end):
    """分类维度：拆分按分类、未拆分按主分类，两种来源合并防止重复。"""
    from transactions.models import Category

    use_parent = defn["group_by"] == "parent_category"
    base = _base_qs(ledger, defn, start, end)
    # 1) 有拆分的流水：按拆分分类
    split_qs = TransactionSplit.objects.filter(transaction__in=base)
    group_field = "category__parent_id" if use_parent else "category_id"
    split_rows = (
        split_qs.values(group_field)
        .annotate(
            income=Sum(
                F("amount") * F("transaction__exchange_rate"),
                filter=Q(transaction__type=TransactionType.INCOME),
            ),
            expense=Sum(
                F("amount") * F("transaction__exchange_rate"),
                filter=Q(transaction__type=TransactionType.EXPENSE),
            ),
            count=Count("transaction_id", distinct=True),
        )
    )
    # 2) 未拆分的流水：按主分类
    unsplit = base.filter(splits__isnull=True, category__isnull=False)
    main_group_field = "category__parent_id" if use_parent else "category_id"
    main_rows = (
        unsplit.values(main_group_field)
        .annotate(
            income=Sum("amount_base", filter=Q(type=TransactionType.INCOME)),
            expense=Sum("amount_base", filter=Q(type=TransactionType.EXPENSE)),
            refund=Sum(
                "amount_base",
                filter=Q(type__in=(TransactionType.REFUND, TransactionType.REIMBURSEMENT)),
            ),
            count=Count("id", distinct=True),
        )
    )
    merged: dict[int, dict] = {}
    for rows, key_field in ((split_rows, group_field), (main_rows, main_group_field)):
        for r in rows:
            key = r[key_field]
            if key is None:
                continue
            item = merged.setdefault(key, {"income": ZERO, "expense": ZERO, "refund": ZERO, "count": 0})
            item["income"] = (item["income"] or ZERO) + (r["income"] or ZERO)
            item["expense"] = (item["expense"] or ZERO) + (r["expense"] or ZERO)
            item["refund"] = (item["refund"] or ZERO) + (r.get("refund") or ZERO)
            item["count"] += r["count"] or 0
    if not merged:
        return []
    cats = {c.id: c for c in Category.all_objects.filter(ledger=ledger)}
    rows = []
    for key, item in merged.items():
        cat = cats.get(key)
        if use_parent:
            parent = cats.get(key)
            if parent is None or parent.parent_id is not None:
                continue
        label = cat.name if cat else f"#{key}"
        rows.append(
            {
                "label": label,
                "income": item["income"],
                "expense": item["expense"],
                "refund": item["refund"],
                "count": item["count"],
            }
        )
    return rows


def _fill_date_gaps(rows: list[dict], group_by: str, start: date, end: date):
    """日期维度补齐空档。"""
    by_label = {r["label"]: r for r in rows}
    out = []
    if group_by == "month":
        cur = start.replace(day=1)
        while cur <= end:
            label = cur.strftime("%Y-%m")
            r = by_label.get(label, {"label": label, "income": ZERO, "expense": ZERO, "refund": ZERO, "count": 0})
            out.append(r)
            if cur.month == 12:
                cur = cur.replace(year=cur.year + 1, month=1)
            else:
                cur = cur.replace(month=cur.month + 1)
    else:
        cur = start
        while cur <= end:
            label = cur.strftime("%Y-%m-%d")
            r = by_label.get(label, {"label": label, "income": ZERO, "expense": ZERO, "refund": ZERO, "count": 0})
            out.append(r)
            cur += timedelta(days=1)
    return out


def _user_label(user_id):
    from accounts.models import User

    if not user_id:
        return "未知"
    u = User.objects.filter(pk=user_id).first()
    return u.effective_display_name if u else f"#{user_id}"


def _account_label(account_id):
    from transactions.models import Account

    if not account_id:
        return "未知"
    a = Account.objects.filter(pk=account_id).first()
    return a.name if a else f"#{account_id}"


# ---------------------------------------------------------------------------
# 内置报表
# ---------------------------------------------------------------------------
def builtin_trend(ledger, months: int = 6):
    """收支趋势（近 N 个月）。"""
    months = max(1, min(months, 24))
    from transactions.services import monthly_series

    return {"rows": monthly_series(ledger, months=months), "months": months}


def builtin_category(ledger, kind: str, start: date, end: date, limit: int = 8):
    from transactions.services import category_summary

    items, total = category_summary(ledger, kind, start, end, limit=limit)
    return {"items": items, "total": total, "start": start, "end": end}


def builtin_account(ledger, start: date, end: date):
    """账户汇总：期初、期间流入流出、期末余额。"""
    from transactions.models import Account
    from transactions.services import account_balance, _effective_qs

    accounts = list(Account.objects.filter(ledger=ledger, is_active=True).order_by("sort_order", "id"))
    rows = []
    for acc in accounts:
        flows = _effective_qs(ledger, start, end).filter(
            Q(from_account=acc) | Q(to_account=acc)
        ).aggregate(
            inflow=Sum(
                "amount_base",
                filter=Q(type=TransactionType.INCOME, from_account=acc)
                | Q(type=TransactionType.TRANSFER, to_account=acc)
                | Q(type=TransactionType.ADJUSTMENT, from_account=acc, amount_base__gte=0),
            ),
            outflow=Sum(
                "amount_base",
                filter=Q(type=TransactionType.EXPENSE, from_account=acc)
                | Q(type=TransactionType.TRANSFER, from_account=acc)
                | Q(type=TransactionType.ADJUSTMENT, from_account=acc, amount_base__lt=0),
            ),
        )
        rows.append(
            {
                "account": acc,
                "opening": None,  # 简单模式：不推算期初，展示期间变动与期末
                "inflow": flows["inflow"] or ZERO,
                "outflow": abs(flows["outflow"] or ZERO),
                "balance": account_balance(acc),
            }
        )
    total = sum((r["balance"] for r in rows), ZERO)
    return {"rows": rows, "total": total, "start": start, "end": end}


def builtin_member(ledger, start: date, end: date, limit: int = 10):
    from transactions.services import member_summary

    return {"rows": member_summary(ledger, start, end, limit=limit), "start": start, "end": end}


def builtin_cashflow(ledger, start: date, end: date):
    """月度现金流：范围内逐月收支与净额。"""
    from transactions.services import _effective_qs

    rows = (
        _effective_qs(ledger, start, end)
        .filter(type__in=(TransactionType.INCOME, TransactionType.EXPENSE, TransactionType.REFUND, TransactionType.REIMBURSEMENT))
        .annotate(y=ExtractYear("date"), m=ExtractMonth("date"))
        .values("y", "m")
        .annotate(
            income=Sum("amount_base", filter=Q(type=TransactionType.INCOME)),
            expense=Sum("amount_base", filter=Q(type=TransactionType.EXPENSE)),
            refund=Sum(
                "amount_base",
                filter=Q(type__in=(TransactionType.REFUND, TransactionType.REIMBURSEMENT)),
            ),
            count=Count("id"),
        )
    )
    out = []
    for r in rows:
        income = r["income"] or ZERO
        expense = r["expense"] or ZERO
        refund = r["refund"] or ZERO
        out.append(
            {
                "label": date(r["y"], r["m"], 1).strftime("%Y-%m"),
                "income": income,
                "expense": expense,
                "refund": refund,
                "net": income - expense + refund,
                "count": r["count"],
            }
        )
    out.sort(key=lambda r: r["label"])
    return {"rows": out, "start": start, "end": end}


def builtin_tag(ledger, start: date, end: date, limit: int = 10):
    from transactions.services import tag_summary

    return {"rows": tag_summary(ledger, start, end, limit=limit), "start": start, "end": end}


def builtin_counterparty(ledger, start: date, end: date, limit: int = 10):
    from transactions.services import counterparty_summary

    return {"rows": counterparty_summary(ledger, start, end, limit=limit), "start": start, "end": end}


def builtin_refund(ledger, start: date, end: date):
    """退款/报销统计：按分类聚合退款与报销金额。"""
    from transactions.services import refund_summary

    rows = refund_summary(ledger, start, end)
    total_refund = sum((r["refund"] for r in rows), ZERO)
    total_reimb = sum((r["reimbursement"] for r in rows), ZERO)
    return {
        "rows": rows,
        "total": (total_refund + total_reimb).quantize(Decimal("0.01")),
        "total_refund": total_refund,
        "total_reimbursement": total_reimb,
        "start": start,
        "end": end,
    }


def builtin_compare(ledger, year: int, month: int):
    """月度收支对比：本月 vs 上月（收入/支出/退款报销/净额 + 支出分类变动）。"""
    from transactions.services import category_summary, ledger_totals, month_range

    this_start, this_end = month_range(year, month)
    if month == 1:
        last_start, last_end = month_range(year - 1, 12)
    else:
        last_start, last_end = month_range(year, month - 1)

    this = ledger_totals(ledger, this_start, this_end)
    last = ledger_totals(ledger, last_start, last_end)

    def row(label, t, l, fmt=None):
        delta = (t - l) if l else None
        pct = (float((t - l) / l * 100) if l else None)
        return {
            "label": label,
            "this": t,
            "last": l,
            "delta": delta,
            "pct": pct,
        }

    rows = [
        row("收入", this["income"], last["income"]),
        row("支出", this["expense"], last["expense"]),
        row("退款报销", this["refund_total"], last["refund_total"]),
        row("净额", this["net"], last["net"]),
    ]
    # 支出分类对比（本月 vs 上月，取本月前 5 大）
    items, _ = category_summary(ledger, "expense", this_start, this_end, limit=5)
    last_items, _ = category_summary(ledger, "expense", last_start, last_end, limit=20)
    last_map = {i["name"]: i["total"] for i in last_items}
    for item in items:
        rows.append(row(f"分类·{item['name']}", item["total"], last_map.get(item["name"], ZERO)))
    return {"rows": rows, "year": year, "month": month}


def builtin_budget(ledger, year: int, month: int):
    from transactions.services import budget_status

    return {"rows": budget_status(ledger, year, month), "year": year, "month": month}


def chart_payload(rows: list[dict]) -> dict:
    """将报表行转换为 ECharts 数据。"""
    labels = [str(r["label"]) for r in rows]
    return {
        "labels": labels,
        "income": [float(r.get("income") or 0) for r in rows],
        "expense": [float(r.get("expense") or 0) for r in rows],
        "net": [float(r.get("value") or r.get("net") or 0) for r in rows],
    }
