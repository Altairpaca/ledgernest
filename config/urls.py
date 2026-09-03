"""LedgerNest 根 URL 配置。"""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("", include("ledgers.urls")),
    path("l/<int:ledger_pk>/", include("transactions.urls")),
    path("l/<int:ledger_pk>/reports/", include("reports.urls")),
    path("l/<int:ledger_pk>/", include("imports_exports.urls")),
    path("favicon.ico", RedirectView.as_view(url="/static/img/favicon.svg", permanent=True)),
]

handler403 = "core.views.handler403"
handler404 = "core.views.handler404"
handler500 = "core.views.handler500"

if settings.DEBUG:
    from django.conf.urls.static import static

    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
