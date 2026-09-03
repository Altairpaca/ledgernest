"""账户相关视图：登录、退出、注册、个人设置、修改密码。"""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView as DjangoLoginView
from django.shortcuts import redirect, render
from django.urls import reverse_lazy

from .forms import LoginForm, PasswordChangeFormZh, RegisterForm
from .models import User


class LoginView(DjangoLoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["registration_open"] = settings.REGISTRATION_MODE == "open"
        return ctx


def logout_view(request):
    logout(request)
    return redirect("accounts:login")


def register_view(request):
    mode = settings.REGISTRATION_MODE
    if mode == "closed":
        return render(request, "accounts/register_closed.html", status=403)
    if mode == "admin" and not (request.user.is_authenticated and request.user.is_staff):
        return render(request, "accounts/register_closed.html", status=403)
    if request.user.is_authenticated:
        return redirect("ledgers:index")
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"欢迎加入账巢，{user.effective_display_name}！")
            return redirect("ledgers:index")
    else:
        form = RegisterForm()
    return render(request, "accounts/register.html", {"form": form})


@login_required
def settings_view(request):
    user = request.user
    if request.method == "POST":
        display_name = request.POST.get("display_name", "").strip()
        locale = request.POST.get("locale", "zh-hans")
        timezone = request.POST.get("timezone", "").strip() or "Asia/Taipei"
        user.display_name = display_name
        user.locale = locale
        user.timezone = timezone
        user.save(update_fields=["display_name", "locale", "timezone"])
        messages.success(request, "个人设置已保存。")
        return redirect("accounts:settings")
    return render(
        request,
        "accounts/settings.html",
        {
            "user": user,
            "tz_choices": _TIMEZONE_CHOICES,
            "locale_choices": [("zh-hans", "简体中文"), ("en", "English")],
        },
    )


_TIMEZONE_CHOICES = [
    ("Asia/Shanghai", "Asia/Shanghai（中国标准时间）"),
    ("Asia/Taipei", "Asia/Taipei（台北）"),
    ("Asia/Hong_Kong", "Asia/Hong_Kong（香港）"),
    ("Asia/Singapore", "Asia/Singapore（新加坡）"),
    ("Asia/Tokyo", "Asia/Tokyo（东京）"),
    ("UTC", "UTC"),
    ("America/Los_Angeles", "America/Los_Angeles"),
    ("Europe/London", "Europe/London"),
]


@login_required
def password_change_view(request):
    form = PasswordChangeFormZh(user=request.user, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, "密码已修改。")
        return redirect("accounts:settings")
    return render(request, "accounts/password_change.html", {"form": form})


@login_required
def admin_create_user_view(request):
    """管理员创建用户（REGISTRATION_MODE=admin 时使用）。"""
    if not request.user.is_staff:
        return render(request, "core/403.html", status=403)
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        display_name = request.POST.get("display_name", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        if not username or not password:
            messages.error(request, "用户名和密码不能为空。")
            return redirect("accounts:admin_create_user")
        if User.objects.filter(username=username).exists():
            messages.error(request, f"用户名 {username} 已存在。")
            return redirect("accounts:admin_create_user")
        User.objects.create_user(
            username=username, display_name=display_name, email=email, password=password
        )
        messages.success(request, f"用户 {username} 已创建。")
        return redirect("accounts:admin_create_user")
    return render(request, "accounts/admin_create_user.html")
