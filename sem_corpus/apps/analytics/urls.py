from django.urls import path

from sem_corpus.apps.analytics.views import AnalyticsDashboardView, TagCloudView

app_name = "analytics"

urlpatterns = [
    path("", AnalyticsDashboardView.as_view(), name="dashboard"),
    path("tag-cloud/", TagCloudView.as_view(), name="tag-cloud"),
]
