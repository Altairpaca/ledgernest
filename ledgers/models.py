"""账本、成员关系与邀请模型。"""
import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import (
    ROLE_CHOICES,
    ROLE_EDITOR,
    ROLE_OWNER,
    BaseModel,
    SoftDeleteModel,
)


class Ledger(SoftDeleteModel):
    """账本：所有业务对象的归属根。"""

    name = models.CharField("名称", max_length=64)
    description = models.CharField("描述", max_length=255, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_ledgers", verbose_name="所有者"
    )
    base_currency = models.CharField("基础货币", max_length=8, default=settings.DEFAULT_CURRENCY)
    timezone = models.CharField("时区", max_length=64, default=settings.TIME_ZONE)
    fiscal_year_start_month = models.PositiveSmallIntegerField("财年起始月份", default=1)
    archived_at = models.DateTimeField("归档时间", null=True, blank=True)

    class Meta:
        verbose_name = "账本"
        verbose_name_plural = "账本"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["owner", "archived_at"])]

    def __str__(self):
        return self.name

    def clean(self):
        if not 1 <= self.fiscal_year_start_month <= 12:
            raise ValidationError({"fiscal_year_start_month": "财年起始月份必须是 1-12 之间的数字。"})

    def archive(self):
        self.archived_at = timezone.now()
        self.save(update_fields=["archived_at", "updated_at"])

    def unarchive(self):
        self.archived_at = None
        self.save(update_fields=["archived_at", "updated_at"])

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    def effective_timezone(self):
        from zoneinfo import ZoneInfo

        try:
            return ZoneInfo(self.timezone)
        except Exception:
            return ZoneInfo(settings.TIME_ZONE)


class LedgerMembership(BaseModel):
    """用户与账本的多对多关系。"""

    ledger = models.ForeignKey(Ledger, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ledger_memberships"
    )
    role = models.PositiveSmallIntegerField("角色", choices=ROLE_CHOICES, default=ROLE_EDITOR)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="邀请人",
    )
    joined_at = models.DateTimeField("加入时间", auto_now_add=True)
    is_active = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "账本成员"
        verbose_name_plural = "账本成员"
        unique_together = [("ledger", "user")]
        indexes = [models.Index(fields=["user", "is_active"])]

    def __str__(self):
        return f"{self.ledger.name} - {self.user}"


class LedgerInvitation(BaseModel):
    """邀请链接/令牌：管理员创建后复制给 Tailnet 内其他用户。"""

    ledger = models.ForeignKey(Ledger, on_delete=models.CASCADE, related_name="invitations")
    target_username = models.CharField("目标用户名", max_length=64, blank=True)
    target_email = models.EmailField("目标邮箱", blank=True)
    role = models.PositiveSmallIntegerField("默认角色", choices=ROLE_CHOICES, default=ROLE_EDITOR)
    token = models.CharField("令牌", max_length=64, unique=True, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+", verbose_name="创建人"
    )
    expires_at = models.DateTimeField("过期时间", null=True, blank=True)
    accepted_at = models.DateTimeField("接受时间", null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="接受人",
    )

    class Meta:
        verbose_name = "账本邀请"
        verbose_name_plural = "账本邀请"
        indexes = [models.Index(fields=["token"])]

    def __str__(self):
        return f"邀请加入 {self.ledger.name}"

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    @property
    def is_expired(self) -> bool:
        from django.utils import timezone

        return self.expires_at is not None and self.expires_at < timezone.now()

    def is_usable(self) -> bool:
        return self.accepted_at is None and not self.is_expired
