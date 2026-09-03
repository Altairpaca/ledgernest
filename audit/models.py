"""审计日志模型。"""
from django.conf import settings
from django.db import models

from core.models import BaseModel


class AuditLog(BaseModel):
    """账本级审计记录：流水增删改恢复、成员变化、设置变化、导入与批量操作。"""

    class Action(models.TextChoices):
        CREATE = "create", "创建"
        UPDATE = "update", "修改"
        DELETE = "delete", "删除"
        RESTORE = "restore", "恢复"
        MEMBER_ADD = "member_add", "添加成员"
        MEMBER_REMOVE = "member_remove", "移除成员"
        MEMBER_ROLE = "member_role", "变更角色"
        OWNER_TRANSFER = "owner_transfer", "转移所有权"
        LEDGER_UPDATE = "ledger_update", "账本设置"
        IMPORT = "import", "数据导入"
        EXPORT = "export", "数据导出"
        BULK = "bulk", "批量操作"
        OTHER = "other", "其他"

    ledger = models.ForeignKey(
        "ledgers.Ledger", on_delete=models.CASCADE, related_name="audit_logs", null=True, blank=True
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+", verbose_name="操作者"
    )
    action = models.CharField("操作", max_length=24, choices=Action.choices)
    object_type = models.CharField("对象类型", max_length=32, blank=True)
    object_id = models.CharField("对象 ID", max_length=32, blank=True)
    summary = models.CharField("摘要", max_length=255, blank=True)
    changes = models.JSONField("变更内容", default=dict, blank=True)

    class Meta:
        verbose_name = "审计日志"
        verbose_name_plural = "审计日志"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["ledger", "-created_at"]),
            models.Index(fields=["ledger", "object_type", "object_id"]),
        ]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.get_action_display()} {self.summary}"
