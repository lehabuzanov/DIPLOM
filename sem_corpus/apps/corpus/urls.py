from django.urls import path

from sem_corpus.apps.corpus.views import (
    AddArticleToSubcorpusView,
    ArticleDetailView,
    ArticleListView,
    EditorArticleUploadView,
    ExportSearchResultsView,
    IssueListView,
    SaveQueryView,
    SavedSubcorpusCreateView,
    SavedSubcorpusDetailView,
    SavedSubcorpusListView,
    SearchView,
)

app_name = "corpus"

urlpatterns = [
    path("issues/", IssueListView.as_view(), name="issue-list"),
    path("articles/", ArticleListView.as_view(), name="article-list"),
    path("articles/upload/", EditorArticleUploadView.as_view(), name="editor-upload"),
    path("articles/<slug:slug>/", ArticleDetailView.as_view(), name="article-detail"),
    path("articles/<int:pk>/add-to-subcorpus/", AddArticleToSubcorpusView.as_view(), name="article-add-to-subcorpus"),
    path("search/", SearchView.as_view(), name="search"),
    path("search/export/csv/", ExportSearchResultsView.as_view(), name="search-export-csv"),
    path("search/save/", SaveQueryView.as_view(), name="save-query"),
    path("subcorpora/", SavedSubcorpusListView.as_view(), name="subcorpus-list"),
    path("subcorpora/new/", SavedSubcorpusCreateView.as_view(), name="subcorpus-create"),
    path("subcorpora/<int:pk>/", SavedSubcorpusDetailView.as_view(), name="subcorpus-detail"),
]
