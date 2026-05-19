from django.urls import path

from sem_corpus.apps.accounts.views import DashboardView, HighlightListView, RegistrationView

app_name = "accounts"

urlpatterns = [
    path("register/", RegistrationView.as_view(), name="register"),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("highlights/", HighlightListView.as_view(), name="highlights"),
]
