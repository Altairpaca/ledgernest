from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.report_index, name="index"),
    path("builtin/<str:report_key>/", views.builtin_report, name="builtin"),
    path("builtin/<str:report_key>/data.json", views.builtin_chart_data, name="builtin_data"),
    path("custom/new/", views.custom_report_build, name="custom_new"),
    path("custom/<int:report_pk>/", views.custom_report_view, name="custom_view"),
    path("custom/<int:report_pk>/edit/", views.custom_report_build, name="custom_edit"),
    path("custom/<int:report_pk>/delete/", views.custom_report_delete, name="custom_delete"),
    path("custom/<int:report_pk>/toggle-share/", views.custom_report_toggle_share, name="custom_toggle_share"),
]
