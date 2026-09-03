"""认证与账户测试。"""
from django.test import Client
from django.urls import reverse

from accounts.models import User


def test_login_flow(db):
    User.objects.create_user("alice", password="pass1234")
    c = Client()
    ok = c.login(username="alice", password="pass1234")
    assert ok
    resp = c.get(reverse("ledgers:index"))
    assert resp.status_code == 302  # 未创建账本时跳转账本列表


def test_login_wrong_password(db):
    User.objects.create_user("alice", password="pass1234")
    c = Client()
    assert not c.login(username="alice", password="wrong")


def test_register_open_mode(db, settings):
    settings.REGISTRATION_MODE = "open"
    c = Client()
    resp = c.post(
        reverse("accounts:register"),
        {"username": "newuser", "password1": "N3w-Pass-2026x", "password2": "N3w-Pass-2026x", "display_name": "新人"},
    )
    assert resp.status_code == 302
    assert User.objects.filter(username="newuser").exists()


def test_register_closed_mode(db, settings):
    settings.REGISTRATION_MODE = "closed"
    c = Client()
    resp = c.post(
        reverse("accounts:register"),
        {"username": "newuser", "password1": "N3w-Pass-2026x", "password2": "N3w-Pass-2026x"},
    )
    assert resp.status_code == 403
    assert not User.objects.filter(username="newuser").exists()


def test_password_change(client_user):
    resp = client_user.post(
        reverse("accounts:password_change"),
        {"old_password": "pass1234", "new_password1": "newpass99", "new_password2": "newpass99"},
    )
    assert resp.status_code == 302
    assert client_user.login(username="alice", password="newpass99")


def test_settings_update(client_user):
    resp = client_user.post(
        reverse("accounts:settings"),
        {"display_name": "新名字", "locale": "zh-hans", "timezone": "Asia/Shanghai"},
    )
    assert resp.status_code == 302
    user = User.objects.get(username="alice")
    assert user.display_name == "新名字"
    assert user.timezone == "Asia/Shanghai"


def test_unauthenticated_redirects_to_login(db):
    c = Client()
    resp = c.get(reverse("ledgers:list"))
    assert resp.status_code == 302
    assert reverse("accounts:login") in resp.url
