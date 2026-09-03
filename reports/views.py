"""报表视图：内置报表、自定义报表定义器、图表数据 API、导出。"""
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
import json as json_module

from core.models import EDIT_ROLES
from ledgers.views import _ensure_member

from transactions.models import TransactionType

from .models import ReportDefinition
from .services import (
    DefinitionError,
    builtin_account,
    builtin_budget,
    builtin_cashflow,
    builtin_category,
    builtin_compare,
    builtin_counterparty,
    builtin_member,
    builtin_refund,
    builtin_tag,
    builtin_trend,
    chart_payload,
    run_custom_report,
    validate_definition,
)

BUILTIN_META = [
    {"key": "trend", "name": "收支趋势", "desc": "近 6/12 个月收支与净额趋势"},
    {"key": "category", "name": "分类汇总", "desc": "指定日期范围内的分类收支排行"},
    {"key": "account", "name": "账户汇总", "desc": "各账户期间变动与期末余额"},
    {"key": "member", "name": "成员记账汇总", "desc": "成员记账笔数与金额统计"},
    {"key": "cashflow", "name": "月度现金流", "desc": "逐月收入、支出与净现金流"},
    {"key": "tag", "name": "标签汇总", "desc": "标签使用次数与金额统计"},
    {"key": "counterparty", "name": "交易对象汇总", "desc": "交易对象频次与金额统计"},
    {"key": "refund", "name": "退款/报销统计", "desc": "按分类统计退款与报销金额"},
    {"key": "compare", "name": "月度收支对比", "desc": "本月与上月收支分类逐项对比"},
    {"key": "budget", "name": "预算执行", "desc": "指定月份预算执行进度"},
]

DEFAULT_RANGE = {"start": (date.today() - timedelta(days=90)).isoformat(), "end": date.today().isoformat()}


def _month_nav(start: date, end: date):
    """报表日期导航：上/下月参数（目标月 1 号与最后一天）。"""
    from transactions.services import month_range

    def target(months):
        total = start.year * 12 + (start.month - 1) + months
        y, m = divmod(total, 12)
        return month_range(y, m + 1)

    prev = target(-1)
    nxt = target(1)
    return {
        "prev_month_start": prev[0].isoformat(),
        "prev_month_end": prev[1].isoformat(),
        "next_month_start": nxt[0].isoformat(),
        "next_month_end": nxt[1].isoformat(),
    }


@login_required
@_ensure_member
def report_index(request, ledger_pk):
    ledger = request.ledger
    custom = ReportDefinition.objects.filter(ledger=ledger).select_related("created_by").order_by("-updated_at")
    return render(
        request,
        "reports/index.html",
        {"ledger": ledger, "builtin": BUILTIN_META, "custom": custom},
    )


def _parse_range(request):
    start = request.GET.get("start") or DEFAULT_RANGE["start"]
    end = request.GET.get("end") or DEFAULT_RANGE["end"]
    try:
        return date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        return date.fromisoformat(DEFAULT_RANGE["start"]), date.fromisoformat(DEFAULT_RANGE["end"])


def _recent_range(months=3):
    end = date.today()
    start = end.replace(day=1)
    for _ in range(months - 1):
        if start.month == 1:
            start = start.replace(year=start.year - 1, month=12)
        else:
            start = start.replace(month=start.month - 1)
    return start, end


@login_required
@_ensure_member
def builtin_report(request, ledger_pk, report_key):
    ledger = request.ledger
    if report_key not in {m["key"] for m in BUILTIN_META}:
        from django.http import Http404

        raise Http404
    ctx = {"ledger": ledger, "key": report_key, "meta": next(m for m in BUILTIN_META if m["key"] == report_key)}

    if report_key == "trend":
        try:
            months = int(request.GET.get("months", 6))
        except ValueError:
            months = 6
        result = builtin_trend(ledger, months=months)
        ctx.update(result)
        ctx["chart"] = chart_payload(result["rows"])
        ctx["chart_type"] = "line"
        ctx["chart_json"] = json_module.dumps(ctx.get("chart") or {})
        ctx["params"] = {"months": months}
        return render(request, "reports/builtin/trend.html", ctx)

    if report_key == "refund":
        start, end = _parse_range(request)
        result = builtin_refund(ledger, start, end)
        ctx.update(result)
        ctx["params"] = {"start": start.isoformat(), "end": end.isoformat()}
        ctx["chart"] = chart_payload(
            [{"label": r["name"], "value": float(r["total"]), "income": None, "expense": None} for r in result["rows"]]
        )
        ctx["chart_type"] = "pie"
        ctx["chart_json"] = json_module.dumps(ctx["chart"])
        return render(request, "reports/builtin/refund.html", ctx)

    if report_key == "compare":
        today = date.today()
        try:
            year = int(request.GET.get("year", today.year))
            month = int(request.GET.get("month", today.month))
        except ValueError:
            year, month = today.year, today.month
        result = builtin_compare(ledger, year, month)
        ctx.update(result)
        ctx["params"] = {"year": year, "month": month}
        ctx["year_range"] = range(today.year - 1, today.year + 2)
        ctx["month_range"] = range(1, 13)
        ctx["chart"] = chart_payload(
            [
                {"label": r["label"], "value": float(r["this"]), "income": float(r["this"]), "expense": None}
                for r in result["rows"]
            ]
        )
        ctx["chart_type"] = "bar"
        ctx["chart_json"] = json_module.dumps(ctx["chart"])
        return render(request, "reports/builtin/compare.html", ctx)

    if report_key == "budget":
        today = date.today()
        try:
            year = int(request.GET.get("year", today.year))
            month = int(request.GET.get("month", today.month))
        except ValueError:
            year, month = today.year, today.month
        result = builtin_budget(ledger, year, month)
        ctx.update(result)
        ctx["params"] = {"year": year, "month": month}
        ctx["year_range"] = range(today.year - 1, today.year + 2)
        ctx["month_range"] = range(1, 13)
        ctx["chart"] = chart_payload(
            [{"label": r["label"], "value": r["spent"], "income": None, "expense": None} for r in result["rows"]]
        )
        ctx["chart_type"] = "bar"
        ctx["chart_json"] = json_module.dumps(ctx.get("chart") or {})
        return render(request, "reports/builtin/budget.html", ctx)

    start, end = _parse_range(request)
    ctx.update({"start": start, "end": end, "params": {"start": start.isoformat(), "end": end.isoformat()}})

    if report_key == "category":
        kind = request.GET.get("kind", "expense")
        result = builtin_category(ledger, kind, start, end)
        ctx.update(result)
        ctx["kind"] = kind
        ctx.update(_month_nav(start, end))
        ctx["chart"] = chart_payload(
            [{"label": r["name"], "value": r["total"], "income": None, "expense": None} for r in result["items"]]
        )
        ctx["chart_type"] = "pie"
        ctx["chart_json"] = json_module.dumps(ctx.get("chart") or {})
        return render(request, "reports/builtin/category.html", ctx)

    if report_key == "account":
        result = builtin_account(ledger, start, end)
        ctx.update(result)
        ctx["chart"] = chart_payload(
            [
                {
                    "label": r["account"].name,
                    "value": float(r["balance"]),
                    "income": float(r["inflow"]),
                    "expense": float(r["outflow"]),
                }
                for r in result["rows"]
            ]
        )
        ctx["chart_type"] = "bar"
        ctx["chart_json"] = json_module.dumps(ctx.get("chart") or {})
        return render(request, "reports/builtin/account.html", ctx)

    if report_key == "member":
        result = builtin_member(ledger, start, end)
        ctx.update(result)
        ctx["chart"] = chart_payload(
            [
                {
                    "label": r["user"].effective_display_name if r["user"] else "未知",
                    "value": float(r["count"]),
                    "income": float(r["income"]),
                    "expense": float(r["expense"]),
                }
                for r in result["rows"]
            ]
        )
        ctx["chart_type"] = "bar"
        ctx["chart_json"] = json_module.dumps(ctx.get("chart") or {})
        return render(request, "reports/builtin/member.html", ctx)

    if report_key == "cashflow":
        result = builtin_cashflow(ledger, start, end)
        ctx.update(result)
        ctx["chart"] = chart_payload(result["rows"])
        ctx["chart_type"] = "bar"
        ctx["chart_json"] = json_module.dumps(ctx.get("chart") or {})
        return render(request, "reports/builtin/cashflow.html", ctx)

    if report_key == "tag":
        result = builtin_tag(ledger, start, end)
        ctx.update(result)
        ctx["chart"] = chart_payload(
            [
                {
                    "label": r["tag"].name,
                    "value": float(r["count"]),
                    "income": float(r["income"]),
                    "expense": float(r["expense"]),
                }
                for r in result["rows"]
            ]
        )
        ctx["chart_type"] = "bar"
        ctx["chart_json"] = json_module.dumps(ctx.get("chart") or {})
        return render(request, "reports/builtin/tag.html", ctx)

    if report_key == "counterparty":
        result = builtin_counterparty(ledger, start, end)
        ctx.update(result)
        ctx["chart"] = chart_payload(
            [
                {
                    "label": r["counterparty"],
                    "value": float(r["count"]),
                    "income": float(r["income"]),
                    "expense": float(r["expense"]),
                }
                for r in result["rows"]
            ]
        )
        ctx["chart_type"] = "bar"
        ctx["chart_json"] = json_module.dumps(ctx.get("chart") or {})
        return render(request, "reports/builtin/counterparty.html", ctx)


# ---------------------------------------------------------------------------
# 自定义报表
# ---------------------------------------------------------------------------
CUSTOM_FORM_SPEC = {
    "group_by_choices": [
        ("month", "月份"), ("day", "日期"), ("category", "分类"), ("parent_category", "父分类"),
        ("account", "账户"), ("tag", "标签"), ("member", "成员"), ("counterparty", "交易对象"),
        ("type", "流水类型"),
    ],
    "metric_choices": [
        ("amount", "金额合计"), ("income", "收入"), ("expense", "支出"),
        ("net", "净额"), ("count", "记录数"), ("avg", "平均金额"),
    ],
    "chart_choices": [("none", "无图表"), ("line", "折线图"), ("bar", "柱状图"), ("pie", "饼图")],
    "sort_choices": [
        ("metric_desc", "指标从高到低"), ("metric_asc", "指标从低到高"),
        ("label_asc", "标签升序"), ("label_desc", "标签降序"),
    ],
}


@login_required
@_ensure_member
def custom_report_build(request, ledger_pk, report_pk=None):
    """自定义报表定义器：分步表单 + 预览，前端提交 definition_json 由后端校验。"""
    ledger = request.ledger
    instance = None
    if report_pk:
        instance = get_object_or_404(ReportDefinition, pk=report_pk, ledger=ledger)
    if request.method == "POST":
        definition = _definition_from_post(request.POST)
        try:
            definition = validate_definition(definition)
        except DefinitionError as exc:
            messages.error(request, f"报表定义无效：{exc}")
            return redirect("reports:custom_build", ledger_pk=ledger.pk)
        name = request.POST.get("name", "").strip() or "未命名报表"
        description = request.POST.get("description", "").strip()
        is_shared = request.POST.get("is_shared") == "on"
        if instance:
            instance.name = name
            instance.description = description
            instance.definition_json = definition
            instance.is_shared = is_shared
            instance.save(update_fields=["name", "description", "definition_json", "is_shared", "updated_at"])
            messages.success(request, "报表定义已更新。")
        else:
            instance = ReportDefinition.objects.create(
                ledger=ledger, name=name, description=description,
                definition_json=definition, created_by=request.user, is_shared=is_shared,
            )
            messages.success(request, "报表已保存。")
        return redirect("reports:custom_view", ledger_pk=ledger.pk, report_pk=instance.pk)

    from transactions.models import Account, Category, Tag

    definition = instance.definition_json if instance else None
    preview = None
    if definition:
        try:
            preview = run_custom_report(ledger, definition)
        except DefinitionError:
            preview = None
    return render(
        request,
        "reports/custom_build.html",
        {
            "ledger": ledger,
            "instance": instance,
            "spec": CUSTOM_FORM_SPEC,
            "definition": definition,
            "preview": preview,
            "accounts": Account.objects.filter(ledger=ledger, is_active=True),
            "categories": Category.objects.filter(ledger=ledger, is_active=True),
            "tags": Tag.objects.filter(ledger=ledger),
            "members": ledger.memberships.select_related("user").filter(is_active=True),
            "types_choices": list(TransactionType.choices),
        },
    )


def _definition_from_post(post) -> dict:
    dr_type = post.get("date_range_type", "relative")
    if dr_type == "absolute":
        date_range = {"type": "absolute", "start": post.get("start", ""), "end": post.get("end", "")}
    else:
        date_range = {"type": "relative", "unit": post.get("rel_unit", "month"), "value": post.get("rel_value", 3)}
    return {
        "date_range": date_range,
        "types": [t for t in post.getlist("types")],
        "account_ids": [int(x) for x in post.getlist("account_ids")],
        "category_ids": [int(x) for x in post.getlist("category_ids")],
        "tag_ids": [int(x) for x in post.getlist("tag_ids")],
        "member_ids": [int(x) for x in post.getlist("member_ids")],
        "group_by": post.get("group_by", "month"),
        "metric": post.get("metric", "net"),
        "sort": post.get("sort", "metric_desc"),
        "chart": post.get("chart", "bar"),
        "limit": post.get("limit", 50),
    }


@login_required
@_ensure_member
def custom_report_view(request, ledger_pk, report_pk):
    ledger = request.ledger
    report = get_object_or_404(
        ReportDefinition.objects.select_related("created_by"), pk=report_pk, ledger=ledger
    )
    try:
        result = run_custom_report(ledger, report.definition_json)
    except DefinitionError as exc:
        messages.error(request, f"报表定义已损坏：{exc}")
        result = {"rows": [], "total": 0, "start": None, "end": None}
    ctx = {
        "ledger": ledger,
        "report": report,
        "result": result,
        "chart": chart_payload(result["rows"]),
        "chart_json": json_module.dumps(chart_payload(result["rows"])),
        "chart_type": report.definition_json.get("chart", "bar"),
    }
    if request.GET.get("format") == "json":
        return JsonResponse(
            {
                "name": report.name,
                "labels": ctx["chart"]["labels"],
                "income": ctx["chart"]["income"],
                "expense": ctx["chart"]["expense"],
                "net": ctx["chart"]["net"],
                "rows": result["rows"],
            }
        )
    return render(request, "reports/custom_view.html", ctx)


@login_required
@_ensure_member
def custom_report_delete(request, ledger_pk, report_pk):
    report = get_object_or_404(ReportDefinition, pk=report_pk, ledger=request.ledger)
    if request.membership.role not in EDIT_ROLES and report.created_by_id != request.user.id:
        from django.http import HttpResponseForbidden

        return HttpResponseForbidden
    report.delete()
    messages.success(request, "报表已删除。")
    return redirect("reports:index", ledger_pk=ledger_pk)


@login_required
@_ensure_member
def custom_report_toggle_share(request, ledger_pk, report_pk):
    report = get_object_or_404(ReportDefinition, pk=report_pk, ledger=request.ledger)
    report.is_shared = not report.is_shared
    report.save(update_fields=["is_shared", "updated_at"])
    messages.success(request, f"报表已{'共享给所有成员' if report.is_shared else '仅自己可见'}。")
    return redirect("reports:custom_view", ledger_pk=ledger_pk, report_pk=report.pk)


# ---------------------------------------------------------------------------
# 图表数据 API（JSON）
# ---------------------------------------------------------------------------
@login_required
@_ensure_member
def builtin_chart_data(request, ledger_pk, report_key):
    """ECharts 数据接口：后端聚合，浏览器端只负责渲染。"""
    if report_key == "trend":
        try:
            months = int(request.GET.get("months", 6))
        except ValueError:
            months = 6
        result = builtin_trend(request.ledger, months=months)
        payload = chart_payload(result["rows"])
        payload["series"] = [{"name": "收入", "data": payload["income"]}, {"name": "支出", "data": payload["expense"]}]
        return JsonResponse(payload)
    if report_key == "category":
        start, end = _parse_range(request)
        kind = request.GET.get("kind", "expense")
        result = builtin_category(request.ledger, kind, start, end)
        return JsonResponse(
            {
                "labels": [r["name"] for r in result["items"]],
                "series": [{"name": "金额", "data": [float(r["total"]) for r in result["items"]]}],
            }
        )
    if report_key == "account":
        start, end = _parse_range(request)
        result = builtin_account(request.ledger, start, end)
        return JsonResponse(
            {
                "labels": [r["account"].name for r in result["rows"]],
                "series": [
                    {"name": "期末余额", "data": [float(r["balance"]) for r in result["rows"]]},
                    {"name": "流入", "data": [float(r["inflow"]) for r in result["rows"]]},
                    {"name": "流出", "data": [float(r["outflow"]) for r in result["rows"]]},
                ],
            }
        )
    if report_key == "cashflow":
        start, end = _parse_range(request)
        result = builtin_cashflow(request.ledger, start, end)
        payload = chart_payload(result["rows"])
        payload["series"] = [
            {"name": "收入", "data": payload["income"]},
            {"name": "支出", "data": payload["expense"]},
            {"name": "净额", "data": [float(r["net"]) for r in result["rows"]]},
        ]
        return JsonResponse(payload)
    if report_key == "budget":
        today = date.today()
        try:
            year = int(request.GET.get("year", today.year))
            month = int(request.GET.get("month", today.month))
        except ValueError:
            year, month = today.year, today.month
        result = builtin_budget(request.ledger, year, month)
        return JsonResponse(
            {
                "labels": [r["label"] for r in result["rows"]],
                "series": [
                    {"name": "已支出", "data": [float(r["spent"]) for r in result["rows"]]},
                    {"name": "预算", "data": [float(r["amount"]) for r in result["rows"]]},
                ],
            }
        )
    from django.http import Http404

    raise Http404
