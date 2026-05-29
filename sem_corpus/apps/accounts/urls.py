from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from sem_corpus.apps.accounts.views import DashboardView, HighlightListView, RegistrationView

app_name = "accounts"

urlpatterns = [
    path("register/", RegistrationView.as_view(), name="register"),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path(
        "password/change/",
        auth_views.PasswordChangeView.as_view(
            template_name="accounts/password_change.html",
            success_url=reverse_lazy("accounts:password-change-done"),
        ),
        name="password-change",
    ),
    path(
        "password/change/done/",
        auth_views.PasswordChangeDoneView.as_view(template_name="accounts/password_change_done.html"),
        name="password-change-done",
    ),
    path("highlights/", HighlightListView.as_view(), name="highlights"),
]
