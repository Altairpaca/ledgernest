"""自定义用户模型：用户名登录 + 显示名称 + 语言时区。"""
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """本地账户。

    第一阶段不实现邮箱验证/找回密码/OAuth/2FA；保留 email、is_active 字段
    供后续扩展。语言与时区为用户偏好，用于账本默认值与显示。
    """

    display_name = models.CharField("显示名称", max_length=64, blank=True)
    locale = models.CharField(
        "语言", max_length=16, blank=True, default="zh-hans", choices=[("zh-hans", "简体中文"), ("en", "English")]
    )
    timezone = models.CharField("时区", max_length=64, blank=True, default="Asia/Taipei")

    class Meta:
        verbose_name = "用户"
        verbose_name_plural = "用户"

    def __str__(self):
        return self.display_name or self.username

    @property
    def effective_display_name(self) -> str:
        return self.display_name or self.username
