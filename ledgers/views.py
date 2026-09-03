"""账本视图：选择/创建/切换、成员管理、邀请、设置。

LedgerScopeMixin 是全部账本内页面共用的权限闸门：
- 从 URL 中解析 ledger_pk，校验当前用户是否为启用成员，否则 403；
- 将 request.ledger / request.membership 注入并同步 session 当前账本。
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from audit.services import audit_log
from core.models import (
    PERM_MANAGE_MEMBERS,
    PERM_MANAGE_SETTINGS,
    ROLE_ADMIN,
    ROLE_CHOICES,
    ROLE_EDITOR,
    ROLE_OWNER,
)

from .models import Ledger, LedgerInvitation, LedgerMembership


class LedgerScopeMixin:
    """账本作用域与权限混入（类视图用）：要求 URL 包含 <int:ledger_pk>。"""

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        ledger_pk = kwargs.get("ledger_pk")
        membership = None
        if ledger_pk is not None:
            membership = (
                LedgerMembership.objects.select_related("ledger")
                .filter(user=request.user, ledger_id=ledger_pk, is_active=True)
                .first()
            )
        if membership is None:
            from django.http import Http404

            raise Http404("账本不存在或无权访问。")
        request.ledger = membership.ledger
        request.membership = membership
        request.session["current_ledger_id"] = membership.ledger_id

    def require_perm(self, min_role: int):
        membership = getattr(self.request, "membership", None)
        if membership is None or membership.role > min_role:
            from django.http import HttpResponseForbidden

            raise HttpResponseForbidden("没有权限执行此操作。")


def request_membership(request):
    return getattr(request, "membership", None)


def _ensure_member(view):
    """函数视图的账本成员校验装饰器：URL 需含 ledger_pk 参数。"""

    def wrapper(request, *args, **kwargs):
        ledger_pk = kwargs.get("ledger_pk")
        if ledger_pk is None:
            from django.http import Http404

            raise Http404
        membership = (
            LedgerMembership.objects.select_related("ledger")
            .filter(user=request.user, ledger_id=ledger_pk, is_active=True)
            .first()
        )
        if membership is None:
            from django.http import Http404

            raise Http404("账本不存在或无权访问。")
        request.ledger = membership.ledger
        request.membership = membership
        request.session["current_ledger_id"] = membership.ledger_id
        return view(request, *args, **kwargs)

    return wrapper


def _require_role(role: int):
    """函数视图装饰器：要求角色不低于指定值，否则 403。"""

    def decorator(view):
        def wrapper(request, *args, **kwargs):
            membership = request_membership(request)
            if membership is None or membership.role > role:
                return render(request, "core/403.html", status=403)
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# 账本选择与创建
# ---------------------------------------------------------------------------
@login_required
def index(request):
    """进入最近使用的账本；没有则跳转账本选择页。"""
    ledger = getattr(request, "ledger", None)
    if ledger is not None:
        return redirect("ledgers:dashboard", ledger_pk=ledger.pk)
    membership = (
        LedgerMembership.objects.select_related("ledger")
        .filter(user=request.user, is_active=True)
        .order_by("-created_at")
        .first()
    )
    if membership:
        request.session["current_ledger_id"] = membership.ledger_id
        return redirect("ledgers:dashboard", ledger_pk=membership.ledger_id)
    return redirect("ledgers:list")


@login_required
def ledger_list(request):
    memberships = (
        LedgerMembership.objects.select_related("ledger")
        .filter(user=request.user, is_active=True)
        .order_by("-ledger__created_at")
    )
    archived = [m for m in memberships if m.ledger.is_archived]
    active = [m for m in memberships if not m.ledger.is_archived]
    return render(request, "ledgers/list.html", {"active": active, "archived": archived})


@login_required
@require_POST
def ledger_create(request):
    name = request.POST.get("name", "").strip()
    description = request.POST.get("description", "").strip()
    base_currency = request.POST.get("base_currency", "").strip()
    if not name:
        messages.error(request, "账本名称不能为空。")
        return redirect("ledgers:list")
    from django.conf import settings

    ledger = Ledger.objects.create(
        name=name,
        description=description,
        owner=request.user,
        base_currency=base_currency or settings.DEFAULT_CURRENCY,
        timezone=request.user.timezone or settings.TIME_ZONE,
    )
    LedgerMembership.objects.create(ledger=ledger, user=request.user, role=ROLE_OWNER, invited_by=request.user)
    audit_log(actor=request.user, ledger=ledger, action="create", object_type="ledger", object_id=ledger.pk, summary=f"创建账本 {ledger.name}")
    messages.success(request, f"账本「{ledger.name}」已创建。")
    return redirect("ledgers:dashboard", ledger_pk=ledger.pk)


@login_required
@require_POST
def ledger_switch(request, ledger_pk):
    membership = LedgerMembership.objects.filter(
        user=request.user, ledger_id=ledger_pk, is_active=True
    ).first()
    if membership is None:
        messages.error(request, "无权访问该账本。")
        return redirect("ledgers:list")
    request.session["current_ledger_id"] = ledger_pk
    return redirect("ledgers:dashboard", ledger_pk=ledger_pk)


@login_required
@_ensure_member
@_require_role(PERM_MANAGE_SETTINGS)
@require_POST
def ledger_archive(request, ledger_pk):
    ledger = request.ledger
    if ledger.owner_id != request.user.id:
        messages.error(request, "只有所有者可以归档账本。")
        return redirect("ledgers:list")
    ledger.archive()
    audit_log(
        actor=request.user, ledger=ledger, action="ledger_update", object_type="ledger",
        object_id=ledger.pk, summary=f"归档账本 {ledger.name}",
    )
    messages.success(request, "账本已归档。")
    return redirect("ledgers:list")


@login_required
@_ensure_member
@_require_role(PERM_MANAGE_SETTINGS)
@require_POST
def ledger_unarchive(request, ledger_pk):
    ledger = request.ledger
    ledger.unarchive()
    audit_log(
        actor=request.user, ledger=ledger, action="ledger_update", object_type="ledger",
        object_id=ledger.pk, summary=f"恢复账本 {ledger.name}",
    )
    messages.success(request, "账本已恢复。")
    return redirect("ledgers:list")


@login_required
@_ensure_member
def ledger_settings(request, ledger_pk):
    if request.membership.role > PERM_MANAGE_SETTINGS:
        return render(request, "core/403.html", status=403)
    ledger = request.ledger
    if request.method == "POST":
        old = {
            "name": ledger.name,
            "description": ledger.description,
            "base_currency": ledger.base_currency,
            "timezone": ledger.timezone,
            "fiscal_year_start_month": ledger.fiscal_year_start_month,
        }
        ledger.name = request.POST.get("name", ledger.name).strip() or ledger.name
        ledger.description = request.POST.get("description", "").strip()
        ledger.base_currency = request.POST.get("base_currency", ledger.base_currency).strip()
        ledger.timezone = request.POST.get("timezone", ledger.timezone).strip()
        try:
            ledger.fiscal_year_start_month = int(request.POST.get("fiscal_year_start_month", "1"))
        except ValueError:
            ledger.fiscal_year_start_month = 1
        try:
            ledger.full_clean()
        except Exception as exc:
            messages.error(request, f"保存失败：{exc}")
            return redirect("ledgers:settings", ledger_pk=ledger.pk)
        ledger.save()
        changed = {k: (old[k], getattr(ledger, k)) for k in old if old[k] != getattr(ledger, k)}
        audit_log(
            actor=request.user, ledger=ledger, action="ledger_update", object_type="ledger",
            object_id=ledger.pk, summary="更新账本设置", changes=changed,
        )
        messages.success(request, "账本设置已保存。")
        return redirect("ledgers:settings", ledger_pk=ledger.pk)
    return render(
        request,
        "ledgers/settings.html",
        {
            "ledger": ledger,
            "tz_choices": _TZ_CHOICES,
            "currency_choices": ["CNY", "USD", "EUR", "JPY", "HKD", "TWD", "SGD", "GBP"],
            "months": list(range(1, 13)),
        },
    )


_TZ_CHOICES = [
    "Asia/Shanghai", "Asia/Taipei", "Asia/Hong_Kong", "Asia/Singapore",
    "Asia/Tokyo", "UTC", "America/Los_Angeles", "Europe/London",
]


# ---------------------------------------------------------------------------
# 成员与邀请
# ---------------------------------------------------------------------------
@login_required
@_ensure_member
def member_list(request, ledger_pk):
    if request.membership.role > PERM_MANAGE_MEMBERS:
        return render(request, "core/403.html", status=403)
    members = (
        LedgerMembership.objects.select_related("user", "invited_by")
        .filter(ledger=request.ledger, is_active=True)
        .order_by("role", "joined_at")
    )
    invitations = LedgerInvitation.objects.filter(ledger=request.ledger).order_by("-created_at")
    return render(
        request,
        "ledgers/members.html",
        {"ledger": request.ledger, "members": members, "invitations": invitations, "role_choices": ROLE_CHOICES},
    )


@login_required
@_ensure_member
@require_POST
def member_role_change(request, ledger_pk, membership_pk):
    if request.membership.role > PERM_MANAGE_MEMBERS:
        return render(request, "core/403.html", status=403)
    target = get_object_or_404(
        LedgerMembership, pk=membership_pk, ledger=request.ledger, is_active=True
    )
    new_role = int(request.POST.get("role", ROLE_EDITOR))
    if not any(value == new_role for value, _ in ROLE_CHOICES):
        messages.error(request, "无效的角色。")
        return redirect("ledgers:members", ledger_pk=ledger_pk)
    if target.user_id == request.ledger.owner_id and new_role != ROLE_OWNER:
        messages.error(request, "不能降低所有者的角色。")
        return redirect("ledgers:members", ledger_pk=ledger_pk)
    if target.user_id == request.ledger.owner_id:
        messages.error(request, "所有者角色不可变更。")
        return redirect("ledgers:members", ledger_pk=ledger_pk)
    old_role = target.role
    target.role = new_role
    target.save(update_fields=["role", "updated_at"])
    audit_log(
        actor=request.user, ledger=request.ledger, action="member_role", object_type="membership",
        object_id=target.pk, summary=f"{target.user.effective_display_name} 角色变更",
        changes={"role": [old_role, new_role]},
    )
    messages.success(request, f"已更新 {target.user.effective_display_name} 的角色。")
    return redirect("ledgers:members", ledger_pk=ledger_pk)


@login_required
@_ensure_member
@require_POST
def member_deactivate(request, ledger_pk, membership_pk):
    if request.membership.role > PERM_MANAGE_MEMBERS:
        return render(request, "core/403.html", status=403)
    target = get_object_or_404(
        LedgerMembership, pk=membership_pk, ledger=request.ledger, is_active=True
    )
    if target.user_id == request.ledger.owner_id:
        messages.error(request, "不能停用所有者。")
        return redirect("ledgers:members", ledger_pk=ledger_pk)
    target.is_active = False
    target.save(update_fields=["is_active", "updated_at"])
    audit_log(
        actor=request.user, ledger=request.ledger, action="member_remove", object_type="membership",
        object_id=target.pk, summary=f"停用成员 {target.user.effective_display_name}",
    )
    messages.success(request, "成员已停用。")
    return redirect("ledgers:members", ledger_pk=ledger_pk)


@login_required
@_ensure_member
@require_POST
def owner_transfer(request, ledger_pk, membership_pk):
    if request.ledger.owner_id != request.user.id:
        messages.error(request, "只有所有者可以转移所有权。")
        return redirect("ledgers:members", ledger_pk=ledger_pk)
    try:
        target_pk = int(request.POST.get("target_membership", membership_pk))
    except (TypeError, ValueError):
        target_pk = membership_pk
    target = get_object_or_404(
        LedgerMembership, pk=target_pk, ledger=request.ledger, is_active=True
    )
    if target.user_id == request.user.id:
        messages.error(request, "不能转移给自己。")
        return redirect("ledgers:members", ledger_pk=ledger_pk)
    old_owner = request.ledger.owner
    request.ledger.owner = target.user
    request.ledger.save(update_fields=["owner", "updated_at"])
    target.role = ROLE_OWNER
    target.save(update_fields=["role", "updated_at"])
    current = LedgerMembership.objects.get(ledger=request.ledger, user=old_owner)
    current.role = ROLE_ADMIN
    current.save(update_fields=["role", "updated_at"])
    audit_log(
        actor=request.user, ledger=request.ledger, action="owner_transfer", object_type="ledger",
        object_id=request.ledger.pk, summary=f"所有权转移给 {target.user.effective_display_name}",
    )
    messages.success(request, f"所有权已转移给 {target.user.effective_display_name}。")
    return redirect("ledgers:members", ledger_pk=ledger_pk)


@login_required
@_ensure_member
@require_POST
def invitation_create(request, ledger_pk):
    if request.membership.role > PERM_MANAGE_MEMBERS:
        return render(request, "core/403.html", status=403)
    try:
        role = int(request.POST.get("role", ROLE_EDITOR))
    except ValueError:
        role = ROLE_EDITOR
    days = 7
    try:
        days = max(1, min(int(request.POST.get("expires_in_days", "7")), 90))
    except ValueError:
        pass
    inv = LedgerInvitation.objects.create(
        ledger=request.ledger,
        role=role,
        created_by=request.user,
        expires_at=timezone.now() + timezone.timedelta(days=days),
        target_username=request.POST.get("target_username", "").strip(),
        target_email=request.POST.get("target_email", "").strip(),
    )
    audit_log(
        actor=request.user, ledger=request.ledger, action="member_add", object_type="invitation",
        object_id=inv.pk, summary="创建邀请链接",
    )
    messages.success(request, "邀请链接已创建，复制给要加入的成员。")
    return redirect("ledgers:members", ledger_pk=ledger_pk)


@login_required
@require_POST
def invitation_revoke(request, invitation_pk):
    inv = get_object_or_404(LedgerInvitation, pk=invitation_pk)
    membership = LedgerMembership.objects.filter(user=request.user, ledger=inv.ledger, is_active=True).first()
    if membership is None or membership.role > PERM_MANAGE_MEMBERS:
        return render(request, "core/403.html", status=403)
    inv.delete()
    messages.success(request, "邀请已撤销。")
    return redirect("ledgers:members", ledger_pk=inv.ledger_id)


@login_required
def invitation_accept(request, token):
    """用户登录后通过链接加入账本。"""
    inv = get_object_or_404(LedgerInvitation, token=token)
    if inv.target_username and inv.target_username != request.user.username:
        return render(request, "ledgers/invitation_invalid.html", {"reason": "此邀请指定了其他用户名。"})
    if inv.target_email and inv.target_email != request.user.email:
        return render(request, "ledgers/invitation_invalid.html", {"reason": "此邀请指定了其他邮箱。"})
    if not inv.is_usable():
        return render(request, "ledgers/invitation_invalid.html", {"reason": "邀请已过期或已被使用。"})
    ledger = inv.ledger
    with db_transaction.atomic():
        membership, created = LedgerMembership.objects.get_or_create(
            ledger=ledger,
            user=request.user,
            defaults={"role": inv.role, "invited_by": inv.created_by},
        )
        if not created and not membership.is_active:
            membership.is_active = True
            membership.role = inv.role
            membership.save(update_fields=["is_active", "role", "updated_at"])
        inv.accepted_at = timezone.now()
        inv.accepted_by = request.user
        inv.save(update_fields=["accepted_at", "accepted_by", "updated_at"])
    audit_log(
        actor=request.user, ledger=ledger, action="member_add", object_type="membership",
        object_id=membership.pk, summary=f"{request.user.effective_display_name} 通过邀请加入",
    )
    request.session["current_ledger_id"] = ledger.pk
    messages.success(request, f"已加入账本「{ledger.name}」。")
    return redirect("ledgers:dashboard", ledger_pk=ledger.pk)
