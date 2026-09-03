from django.urls import path

from . import views

app_name = "imports"

urlpatterns = [
    path("import/", views.import_view, name="import"),
    path("import/preview/", views.import_preview, name="preview"),
    path("import/confirm/", views.import_confirm, name="confirm"),
    path("import/template.xlsx", views.import_template, name="template"),
    path("export/", views.export_view, name="export"),
    path("export/transactions/", views.export_transactions, name="export_transactions"),
    path("export/report/", views.export_report, name="export_report"),
    path("backup/download/", views.backup_download, name="backup"),
]
