"""审计写入辅助：统一入口，防止各视图各自复制记录逻辑。"""
from .models import AuditLog


def audit_log(
    *,
    actor=None,
    ledger=None,
    action,
    object_type="",
    object_id="",
    summary="",
    changes=None,
):
    AuditLog.objects.create(
        actor=actor,
        ledger=ledger,
        action=action,
        object_type=object_type,
        object_id=str(object_id) if object_id is not None else "",
        summary=summary[:255],
        changes=changes or {},
    )


def record_transaction_change(actor, txn, action: str, changes=None):
    """流水相关审计：type/date/amount/描述 摘要。"""
    summary = (
        f"{txn.get_type_display()} {txn.amount} {txn.currency} "
        f"({txn.date:%Y-%m-%d}{' ' + txn.description if txn.description else ''})"
    )
    audit_log(
        actor=actor,
        ledger=txn.ledger,
        action=action,
        object_type="transaction",
        object_id=txn.pk,
        summary=summary,
        changes=changes or {},
    )
