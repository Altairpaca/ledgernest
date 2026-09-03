from django.urls import path

from . import views

app_name = "transactions"

urlpatterns = [
    path("new/", views.quick_add, name="quick_add"),
    path("new/<int:txn_pk>/done/", views.quick_add_done, name="quick_add_done"),
    path("transactions/", views.transaction_list, name="list"),
    path("calendar/", views.calendar_view, name="calendar"),
    path("transactions/<int:txn_pk>/", views.transaction_detail, name="detail"),
    path("transactions/<int:txn_pk>/edit/", views.transaction_edit, name="edit"),
    path("transactions/<int:txn_pk>/delete/", views.transaction_delete, name="delete"),
    path("transactions/<int:txn_pk>/restore/", views.transaction_restore, name="restore"),
    path("transactions/<int:txn_pk>/duplicate/", views.transaction_duplicate, name="duplicate"),
    path("accounts/", views.account_list, name="accounts"),
    path("accounts/new/", views.account_edit, name="account_new"),
    path("accounts/<int:account_pk>/edit/", views.account_edit, name="account_edit"),
    path("accounts/<int:account_pk>/toggle/", views.account_toggle, name="account_toggle"),
    path("categories/", views.category_list, name="categories"),
    path("categories/new/", views.category_edit, name="category_new"),
    path("categories/<int:category_pk>/edit/", views.category_edit, name="category_edit"),
    path("categories/<int:category_pk>/toggle/", views.category_toggle, name="category_toggle"),
    path("tags/", views.tag_list, name="tags"),
    path("tags/new/", views.tag_edit, name="tag_new"),
    path("tags/<int:tag_pk>/edit/", views.tag_edit, name="tag_edit"),
    path("tags/<int:tag_pk>/delete/", views.tag_delete, name="tag_delete"),
    path("budgets/", views.budget_list, name="budgets"),
    path("budgets/new/", views.budget_edit, name="budget_new"),
    path("budgets/<int:budget_pk>/edit/", views.budget_edit, name="budget_edit"),
    path("budgets/<int:budget_pk>/delete/", views.budget_delete, name="budget_delete"),
    path("ajax/categories/", views.ajax_categories, name="ajax_categories"),
]
