from django.urls import path

from . import dashboard, views

app_name = "ledgers"

urlpatterns = [
    path("", views.index, name="index"),
    path("ledgers/", views.ledger_list, name="list"),
    path("ledgers/create/", views.ledger_create, name="create"),
    path("ledgers/<int:ledger_pk>/switch/", views.ledger_switch, name="switch"),
    path("l/<int:ledger_pk>/", dashboard.dashboard, name="dashboard"),
    path("l/<int:ledger_pk>/settings/", views.ledger_settings, name="settings"),
    path("l/<int:ledger_pk>/members/", views.member_list, name="members"),
    path("l/<int:ledger_pk>/members/<int:membership_pk>/role/", views.member_role_change, name="member_role"),
    path("l/<int:ledger_pk>/members/<int:membership_pk>/deactivate/", views.member_deactivate, name="member_deactivate"),
    path("l/<int:ledger_pk>/members/<int:membership_pk>/transfer-owner/", views.owner_transfer, name="owner_transfer"),
    path("l/<int:ledger_pk>/invitations/create/", views.invitation_create, name="invitation_create"),
    path("invitations/<int:invitation_pk>/revoke/", views.invitation_revoke, name="invitation_revoke"),
    path("l/<int:ledger_pk>/archive/", views.ledger_archive, name="archive"),
    path("l/<int:ledger_pk>/unarchive/", views.ledger_unarchive, name="unarchive"),
    path("invite/<str:token>/", views.invitation_accept, name="invitation_accept"),
]
