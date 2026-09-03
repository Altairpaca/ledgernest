from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("register/", views.register_view, name="register"),
    path("settings/", views.settings_view, name="settings"),
    path("password/change/", views.password_change_view, name="password_change"),
    path("admin/create-user/", views.admin_create_user_view, name="admin_create_user"),
]
