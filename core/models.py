"""核心基础设施：基类模型、软删除管理器、权限常量。"""
from django.db import models


class SoftDeleteQuerySet(models.QuerySet):
    """默认排除软删除记录。"""

    def delete(self):
        for obj in self:
            obj.soft_delete()
        return (len(self), {})

    def hard_delete(self):
        return super().delete()


class SoftDeleteManager(models.Manager):
    """objects = 仅未删除；all_objects = 包含已软删除。"""

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(deleted_at__isnull=True)


class AllObjectsManager(models.Manager):
    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db)


class BaseModel(models.Model):
    """所有业务模型的公共字段。"""

    created_at = models.DateTimeField("创建时间", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteModel(BaseModel):
    """支持软删除的模型：objects 默认过滤，all_objects 包含全部。"""

    deleted_at = models.DateTimeField("软删除时间", null=True, blank=True, db_index=True)

    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True

    def soft_delete(self, using=None):
        from django.utils import timezone

        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at", "updated_at"], using=using)

    def restore(self, using=None):
        self.deleted_at = None
        self.save(update_fields=["deleted_at", "updated_at"], using=using)


# ---------------------------------------------------------------------------
# 角色常量：数值越小权限越高，便于比较
# ---------------------------------------------------------------------------
ROLE_OWNER = 10
ROLE_ADMIN = 20
ROLE_EDITOR = 30
ROLE_VIEWER = 40

ROLE_CHOICES = [
    (ROLE_OWNER, "所有者"),
    (ROLE_ADMIN, "管理员"),
    (ROLE_EDITOR, "编辑者"),
    (ROLE_VIEWER, "只读"),
]

# 各操作所需的最低角色（数值 <= 该值即有权限）
PERM_MANAGE_MEMBERS = ROLE_ADMIN  # 成员管理：owner/admin
PERM_MANAGE_SETTINGS = ROLE_ADMIN  # 账本设置
PERM_EDIT_DATA = ROLE_EDITOR  # 业务数据编辑
PERM_VIEW = ROLE_VIEWER  # 只读

# 可编辑数据的角色值集合
EDIT_ROLES = (ROLE_OWNER, ROLE_ADMIN, ROLE_EDITOR)
MANAGE_ROLES = (ROLE_OWNER, ROLE_ADMIN)


def can_edit(role: int) -> bool:
    return role in EDIT_ROLES


def can_manage(role: int) -> bool:
    return role in MANAGE_ROLES


def role_label(role: int) -> str:
    for value, label in ROLE_CHOICES:
        if value == role:
            return label
    return str(role)
