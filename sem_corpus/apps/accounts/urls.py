from django.urls import path

from sem_corpus.apps.accounts.views import DashboardView, RegistrationView

app_name = "accounts"

urlpatterns = [
    path("register/", RegistrationView.as_view(), name="register"),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
]
