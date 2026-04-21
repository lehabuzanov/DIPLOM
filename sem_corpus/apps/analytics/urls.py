from django.urls import path

from sem_corpus.apps.analytics.views import AnalyticsDashboardView

app_name = "analytics"

urlpatterns = [
    path("", AnalyticsDashboardView.as_view(), name="dashboard"),
]
