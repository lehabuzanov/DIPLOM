from django.urls import path

from sem_corpus.apps.analytics.views import AnalyticsDashboardView, AnalyticsExportView

app_name = "analytics"

urlpatterns = [
    path("", AnalyticsDashboardView.as_view(), name="dashboard"),
    path("export/csv/", AnalyticsExportView.as_view(), name="export-csv"),
]
