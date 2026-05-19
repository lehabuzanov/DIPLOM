from django.urls import path

from sem_corpus.apps.analytics.views import AnalyticsDashboardView, AnalyticsDataView, AnalyticsExportView

app_name = "analytics"

urlpatterns = [
    path("", AnalyticsDashboardView.as_view(), name="dashboard"),
    path("data/", AnalyticsDataView.as_view(), name="data"),
    path("export/csv/", AnalyticsExportView.as_view(), name="export-csv"),
]
