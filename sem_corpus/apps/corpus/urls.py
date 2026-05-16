from django.urls import path

from sem_corpus.apps.corpus.views import (
    AddArticleToSubcorpusView,
    ArticleDetailView,
    ArticleFileAccessView,
    ArticleListView,
    EditorArticleUploadView,
    ExportSearchResultsView,
    IssueListView,
    SaveQueryView,
    SavedQueryDeleteView,
    SavedQueryListView,
    SavedQueryRunView,
    SavedQueryUpdateView,
    SavedSubcorpusCreateView,
    SavedSubcorpusDeleteView,
    SavedSubcorpusDetailView,
    SavedSubcorpusListView,
    SavedSubcorpusRefreshView,
    SavedSubcorpusUpdateView,
    SearchView,
)

app_name = "corpus"

urlpatterns = [
    path("issues/", IssueListView.as_view(), name="issue-list"),
    path("articles/", ArticleListView.as_view(), name="article-list"),
    path("articles/upload/", EditorArticleUploadView.as_view(), name="editor-upload"),
    path("articles/<slug:slug>/", ArticleDetailView.as_view(), name="article-detail"),
    path("articles/<int:pk>/add-to-subcorpus/", AddArticleToSubcorpusView.as_view(), name="article-add-to-subcorpus"),
    path("files/<int:pk>/", ArticleFileAccessView.as_view(), name="article-file"),
    path("search/", SearchView.as_view(), name="search"),
    path("search/export/csv/", ExportSearchResultsView.as_view(), name="search-export-csv"),
    path("search/save/", SaveQueryView.as_view(), name="save-query"),
    path("queries/", SavedQueryListView.as_view(), name="saved-query-list"),
    path("queries/<int:pk>/run/", SavedQueryRunView.as_view(), name="saved-query-run"),
    path("queries/<int:pk>/edit/", SavedQueryUpdateView.as_view(), name="saved-query-edit"),
    path("queries/<int:pk>/delete/", SavedQueryDeleteView.as_view(), name="saved-query-delete"),
    path("subcorpora/", SavedSubcorpusListView.as_view(), name="subcorpus-list"),
    path("subcorpora/new/", SavedSubcorpusCreateView.as_view(), name="subcorpus-create"),
    path("subcorpora/<int:pk>/", SavedSubcorpusDetailView.as_view(), name="subcorpus-detail"),
    path("subcorpora/<int:pk>/edit/", SavedSubcorpusUpdateView.as_view(), name="subcorpus-edit"),
    path("subcorpora/<int:pk>/refresh/", SavedSubcorpusRefreshView.as_view(), name="subcorpus-refresh"),
    path("subcorpora/<int:pk>/delete/", SavedSubcorpusDeleteView.as_view(), name="subcorpus-delete"),
]
