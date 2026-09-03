"""报表定义模型：保存报表定义而非结果。"""
from django.conf import settings
from django.db import models

from core.models import BaseModel


class ReportDefinition(BaseModel):
    """受控自定义报表定义。

    definition_json 结构见 README「报表定义结构」，由 reports.services.validate_definition
    按白名单校验后写入，禁止直接构造任意 JSON。
    """

    ledger = models.ForeignKey("ledgers.Ledger", on_delete=models.CASCADE, related_name="report_definitions")
    name = models.CharField("名称", max_length=64)
    description = models.CharField("描述", max_length=255, blank=True)
    report_type = models.CharField("报表类型", max_length=16, default="custom")
    definition_json = models.JSONField("定义", default=dict)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+", verbose_name="创建人"
    )
    is_shared = models.BooleanField("共享给成员", default=True)

    class Meta:
        verbose_name = "报表定义"
        verbose_name_plural = "报表定义"
        ordering = ["-updated_at"]

    def __str__(self):
        return self.name
