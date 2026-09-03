"""账本、成员、邀请与权限边界测试。"""
from django.urls import reverse

from audit.models import AuditLog
from core.models import ROLE_ADMIN, ROLE_EDITOR, ROLE_OWNER, ROLE_VIEWER
from ledgers.models import Ledger, LedgerInvitation, LedgerMembership


def test_ledger_create(client_user):
    resp = client_user.post(reverse("ledgers:create"), {"name": "新账本", "base_currency": "CNY"})
    assert resp.status_code == 302
    ledger = Ledger.objects.get(name="新账本")
    assert ledger.owner.username == "alice"
    assert LedgerMembership.objects.filter(ledger=ledger, user__username="alice", role=ROLE_OWNER).exists()


def test_ledger_switch(client_user, ledger):
    resp = client_user.post(reverse("ledgers:switch", args=[ledger.pk]))
    assert resp.status_code == 302
    session_ledger = client_user.session["current_ledger_id"]
    assert session_ledger == ledger.pk


def test_invitation_accept_flow(db, ledger, bob):
    inv = LedgerInvitation.objects.create(ledger=ledger, role=ROLE_EDITOR, expires_at=None)
    c = __import__("django.test", fromlist=["Client"]).Client()
    c.force_login(bob)
    resp = c.post(reverse("ledgers:invitation_accept", args=[inv.token]))
    assert resp.status_code == 302
    m = LedgerMembership.objects.get(ledger=ledger, user=bob)
    assert m.role == ROLE_EDITOR
    inv.refresh_from_db()
    assert inv.accepted_at is not None


def test_invitation_reuse_blocked(db, ledger, bob, carol):
    inv = LedgerInvitation.objects.create(ledger=ledger, role=ROLE_EDITOR, expires_at=None)
    c = __import__("django.test", fromlist=["Client"]).Client()
    c.force_login(bob)
    c.post(reverse("ledgers:invitation_accept", args=[inv.token]))
    c2 = __import__("django.test", fromlist=["Client"]).Client()
    c2.force_login(carol)
    resp = c2.post(reverse("ledgers:invitation_accept", args=[inv.token]))
    assert resp.status_code == 200  # invitation_invalid 页
    assert not LedgerMembership.objects.filter(ledger=ledger, user=carol).exists()


def test_invitation_target_username_mismatch(db, ledger, bob):
    inv = LedgerInvitation.objects.create(ledger=ledger, role=ROLE_EDITOR, target_username="someone_else")
    c = __import__("django.test", fromlist=["Client"]).Client()
    c.force_login(bob)
    resp = c.post(reverse("ledgers:invitation_accept", args=[inv.token]))
    assert resp.status_code == 200
    assert not LedgerMembership.objects.filter(ledger=ledger, user=bob).exists()


def test_non_member_cannot_access_ledger(client_user, other_ledger):
    resp = client_user.get(reverse("ledgers:dashboard", args=[other_ledger.pk]))
    assert resp.status_code == 404


def test_non_member_cannot_read_transactions(client_user, other_ledger):
    resp = client_user.get(reverse("transactions:list", args=[other_ledger.pk]))
    assert resp.status_code == 404


def test_viewer_cannot_edit(client_carol, ledger, viewer_membership, account_cash):
    resp = client_carol.post(
        reverse("transactions:quick_add", args=[ledger.pk]),
        {
            "type": "expense", "date": "2026-08-01", "amount": "10", "currency": "CNY",
            "exchange_rate": "1", "from_account": str(account_cash.pk),
        },
    )
    assert resp.status_code == 403


def test_editor_can_edit(client_bob, ledger, editor_membership, account_cash):
    resp = client_bob.post(
        reverse("transactions:quick_add", args=[ledger.pk]),
        {
            "type": "expense", "date": "2026-08-01", "amount": "10", "currency": "CNY",
            "exchange_rate": "1", "from_account": str(account_cash.pk),
        },
    )
    assert resp.status_code == 302


def test_viewer_cannot_manage_members(client_carol, ledger, viewer_membership):
    resp = client_carol.get(reverse("ledgers:members", args=[ledger.pk]))
    assert resp.status_code == 403


def test_admin_can_manage_members(db, ledger, bob, carol):
    add = __import__("ledgers.models", fromlist=["LedgerMembership"]).LedgerMembership.objects.create
    add(ledger=ledger, user=bob, role=ROLE_ADMIN)
    add(ledger=ledger, user=carol, role=ROLE_EDITOR)
    c = __import__("django.test", fromlist=["Client"]).Client()
    c.force_login(bob)
    carol_m = LedgerMembership.objects.get(ledger=ledger, user=carol)
    resp = c.post(reverse("ledgers:member_role", args=[ledger.pk, carol_m.pk]), {"role": "40"})
    assert resp.status_code == 302
    assert LedgerMembership.objects.get(ledger=ledger, user=carol).role == ROLE_VIEWER


def test_cannot_demote_owner(db, ledger, bob):
    LedgerMembership.objects.create(ledger=ledger, user=bob, role=ROLE_ADMIN)
    c = __import__("django.test", fromlist=["Client"]).Client()
    c.force_login(bob)
    owner_m = LedgerMembership.objects.get(ledger=ledger, role=ROLE_OWNER)
    resp = c.post(reverse("ledgers:member_role", args=[ledger.pk, owner_m.pk]), {"role": "30"})
    assert resp.status_code == 302
    assert LedgerMembership.objects.get(pk=owner_m.pk).role == ROLE_OWNER


def test_owner_transfer(db, ledger, bob):
    m = LedgerMembership.objects.create(ledger=ledger, user=bob, role=ROLE_EDITOR)
    c = __import__("django.test", fromlist=["Client"]).Client()
    c.force_login(bob)
    # 非所有者不能转移
    c.post(reverse("ledgers:owner_transfer", args=[ledger.pk, 0]), {"target_membership": str(m.pk)})
    ledger.refresh_from_db()
    assert ledger.owner.username == "alice"
    # 所有者转移
    c2 = __import__("django.test", fromlist=["Client"]).Client()
    c2.force_login(ledger.owner)
    c2.post(reverse("ledgers:owner_transfer", args=[ledger.pk, 0]), {"target_membership": str(m.pk)})
    ledger.refresh_from_db()
    assert ledger.owner_id == bob.id
    assert LedgerMembership.objects.get(ledger=ledger, user=bob).role == ROLE_OWNER
    assert LedgerMembership.objects.get(ledger=ledger, user__username="alice").role == ROLE_ADMIN


def test_ledger_archive_requires_owner(db, ledger, bob):
    LedgerMembership.objects.create(ledger=ledger, user=bob, role=ROLE_ADMIN)
    c = __import__("django.test", fromlist=["Client"]).Client()
    c.force_login(bob)
    c.post(reverse("ledgers:archive", args=[ledger.pk]))
    ledger.refresh_from_db()
    assert ledger.archived_at is None  # admin 不能归档
    c2 = __import__("django.test", fromlist=["Client"]).Client()
    c2.force_login(ledger.owner)
    c2.post(reverse("ledgers:archive", args=[ledger.pk]))
    ledger.refresh_from_db()
    assert ledger.archived_at is not None


def test_member_changes_audited(client_user, ledger, bob):
    LedgerMembership.objects.create(ledger=ledger, user=bob, role=ROLE_EDITOR)
    m = LedgerMembership.objects.get(ledger=ledger, user=bob)
    client_user.post(reverse("ledgers:member_role", args=[ledger.pk, m.pk]), {"role": "40"})
    assert AuditLog.objects.filter(ledger=ledger, action="member_role").exists()
