"""当前账本上下文中间件：从 session 中恢复当前账本，供全局使用。"""
from django.utils.deprecation import MiddlewareMixin


class LedgerContextMiddleware(MiddlewareMixin):
    """将 request.ledger / request.membership 注入请求（可能为 None）。

    具体账本 URL（/l/<pk>/...）由 ledgers.views._ensure_member 校验并设置，
    本中间件只负责从 session 恢复“最近使用的账本”，供重定向使用。
    """

    def process_request(self, request):
        request.ledger = None
        request.membership = None
        ledger_id = request.session.get("current_ledger_id")
        if ledger_id and request.user.is_authenticated:
            from ledgers.models import LedgerMembership

            membership = (
                LedgerMembership.objects.select_related("ledger")
                .filter(user=request.user, ledger_id=ledger_id, is_active=True)
                .first()
            )
            if membership:
                request.ledger = membership.ledger
                request.membership = membership
            else:
                request.session.pop("current_ledger_id", None)


ledger_context_middleware = LedgerContextMiddleware
