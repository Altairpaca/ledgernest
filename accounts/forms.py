from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm
from django.forms import CharField, EmailField, PasswordInput, TextInput

from .models import User


class LoginForm(AuthenticationForm):
    username = CharField(
        label="用户名或邮箱",
        widget=TextInput(attrs={"autocomplete": "username", "autofocus": True, "inputmode": "text"}),
    )
    password = CharField(
        label="密码",
        widget=PasswordInput(attrs={"autocomplete": "current-password"}),
    )


class RegisterForm(UserCreationForm):
    email = EmailField(label="邮箱", required=False)

    class Meta:
        model = User
        fields = ("username", "display_name", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "用户名"
        self.fields["display_name"].label = "显示名称"
        self.fields["username"].help_text = "必填。字母、数字及 @/./+/-/_。"
        self.fields["password1"].label = "密码"
        self.fields["password2"].label = "确认密码"
        self.fields["password1"].help_text = "至少 6 位，不能过于常见。"

    def save(self, commit=True):
        user = super().save(commit=False)
        if commit:
            user.save()
        return user


class PasswordChangeFormZh(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].label = "当前密码"
        self.fields["new_password1"].label = "新密码"
        self.fields["new_password2"].label = "确认新密码"
