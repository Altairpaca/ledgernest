"""模板上下文：当前账本与成员角色。"""
from core.models import role_label


def ledger_context(request):
    return {
        "current_ledger": getattr(request, "ledger", None),
        "membership_role": getattr(getattr(request, "membership", None), "role", None),
        "role_label": role_label,
    }
