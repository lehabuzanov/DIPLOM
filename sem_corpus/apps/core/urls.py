from django.urls import path

from sem_corpus.apps.core.views import AboutView, GuideView, HomeView

app_name = "core"

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("about/", AboutView.as_view(), name="about"),
    path("guide/", GuideView.as_view(), name="guide"),
]
