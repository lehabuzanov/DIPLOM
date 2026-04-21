from __future__ import annotations

import hashlib
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.text import slugify
from django.views.generic import DetailView, FormView, ListView, TemplateView, View

from sem_corpus.apps.accounts.utils import user_can_edit_corpus
from sem_corpus.apps.corpus.forms import (
    AddToSubcorpusForm,
    EditorArticleUploadForm,
    SaveQueryForm,
    SavedSubcorpusForm,
    SearchForm,
)
from sem_corpus.apps.corpus.models import (
    Affiliation,
    Article,
    ArticleAuthor,
    ArticleFile,
    ArticleText,
    Author,
    Issue,
    Journal,
    SavedSubcorpus,
    Section,
)
from sem_corpus.apps.corpus.services import (
    add_article_to_subcorpus,
    apply_article_filters,
    build_subcorpus,
    deserialize_payload,
    export_search_results_csv,
    save_query,
    search_articles,
    serialize_querydict,
    sync_keywords_for_article,
)


def normalize_person_parts(display_name: str) -> tuple[str, str, str]:
    normalized = " ".join((display_name or "").replace(".", " ").split())
    parts = normalized.split()
    if not parts:
        return "", "", ""
    if len(parts) == 1:
        return "", parts[0], ""
    if len(parts) == 2:
        return parts[1], parts[0], ""
    return parts[1], parts[0], " ".join(parts[2:])


def build_author_slug(display_name: str) -> str:
    slug = slugify(display_name)
    if slug:
        return slug
    return f"author-{hashlib.sha1(display_name.encode('utf-8')).hexdigest()[:12]}"


def build_unique_article_slug(title: str, article: Article | None = None) -> str:
    base_slug = slugify(title, allow_unicode=True) or "article"
    base_slug = base_slug[:220]
    candidate = base_slug
    suffix = 2
    queryset = Article.objects.all()
    if article and article.pk:
        queryset = queryset.exclude(pk=article.pk)
    while queryset.filter(slug=candidate).exists():
        suffix_text = f"-{suffix}"
        candidate = f"{base_slug[: 255 - len(suffix_text)]}{suffix_text}"
        suffix += 1
    return candidate


def parse_editor_authors(raw_value: str) -> list[dict[str, str]]:
    authors = []
    for raw_line in (raw_value or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "|" in line:
            display_name, affiliation = [part.strip() for part in line.split("|", 1)]
        else:
            display_name, affiliation = line, ""
        authors.append({"display_name": display_name, "affiliation": affiliation})
    return authors


def resolve_file_kind(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".pdf":
        return ArticleFile.KIND_PDF
    if suffix == ".docx":
        return ArticleFile.KIND_DOCX
    if suffix == ".txt":
        return ArticleFile.KIND_TXT
    return ArticleFile.KIND_OTHER


def create_or_update_editor_article(cleaned_data) -> Article:
    journal = Journal.objects.filter(is_active=True).order_by("id").first() or Journal.objects.create(
        title="Научный журнал «Социально-экономическое управление: теория и практика»",
        short_title="Социально-экономическое управление: теория и практика",
        publisher="ИжГТУ имени М. Т. Калашникова",
        site_url="https://izdat.istu.ru/index.php/social-economic-management",
        description="Корпус научного журнала для хранения, поиска и аналитики текстов.",
        is_active=True,
    )
    issue, _ = Issue.objects.get_or_create(
        journal=journal,
        year=cleaned_data["issue_year"],
        volume=cleaned_data["issue_volume"],
        number=cleaned_data["issue_number"],
        defaults={
            "title": cleaned_data.get("issue_title", ""),
            "publication_date": cleaned_data.get("publication_date"),
        },
    )
    issue.title = cleaned_data.get("issue_title", "")
    issue.publication_date = cleaned_data.get("publication_date")
    issue.save()

    section_name = cleaned_data["section_name"].strip()
    section, _ = Section.objects.get_or_create(
        journal=journal,
        slug=slugify(section_name, allow_unicode=True) or f"section-{journal.pk}",
        defaults={"name": section_name},
    )
    if section.name != section_name:
        section.name = section_name
        section.save(update_fields=["name", "updated_at"])

    doi = (cleaned_data.get("doi") or "").strip()
    article = None
    if doi:
        article = Article.objects.filter(doi=doi).first()
    if article is None:
        article = Article.objects.filter(title=cleaned_data["title"], issue=issue).first()
    created = article is None
    if article is None:
        article = Article(journal=journal, issue=issue, slug=build_unique_article_slug(cleaned_data["title"]))

    article.journal = journal
    article.issue = issue
    article.section = section
    article.title = cleaned_data["title"]
    article.slug = build_unique_article_slug(cleaned_data["title"], article=article)
    article.language = cleaned_data["language"]
    article.pages = cleaned_data.get("pages", "")
    article.doi = doi
    article.original_url = cleaned_data.get("original_url", "")
    article.abstract = cleaned_data.get("abstract_text", "")
    article.import_source = "editor_upload"
    article.is_published = cleaned_data.get("is_published", False)
    article.save()

    ArticleAuthor.objects.filter(article=article).delete()
    for order, author_payload in enumerate(parse_editor_authors(cleaned_data["authors_text"]), start=1):
        first_name, last_name, middle_name = normalize_person_parts(author_payload["display_name"])
        author, _ = Author.objects.get_or_create(
            slug=build_author_slug(author_payload["display_name"]),
            defaults={
                "first_name": first_name,
                "last_name": last_name,
                "middle_name": middle_name,
            },
        )
        author.first_name = first_name
        author.last_name = last_name
        author.middle_name = middle_name
        author.save()

        affiliation = None
        if author_payload["affiliation"]:
            affiliation, _ = Affiliation.objects.get_or_create(name=author_payload["affiliation"])
            author.affiliations.add(affiliation)

        ArticleAuthor.objects.create(
            article=article,
            author=author,
            affiliation=affiliation,
            order=order,
            display_name=author_payload["display_name"],
        )

    ArticleText.objects.update_or_create(
        article=article,
        defaults={
            "title_text": cleaned_data["title"],
            "abstract_text": cleaned_data.get("abstract_text", ""),
            "keywords_text": cleaned_data.get("keywords_text", ""),
            "body_text": cleaned_data.get("body_text", ""),
            "references_text": cleaned_data.get("references_text", ""),
        },
    )
    sync_keywords_for_article(article, cleaned_data.get("keywords_text", ""))

    source_file = cleaned_data.get("source_file")
    if source_file:
        article_file, _ = ArticleFile.objects.get_or_create(
            article=article,
            file_kind=resolve_file_kind(source_file.name),
            defaults={"original_filename": source_file.name},
        )
        article_file.original_filename = source_file.name
        article_file.external_url = cleaned_data.get("original_url", "")
        article_file.file.save(source_file.name, source_file, save=False)
        article_file.save()

    article._editor_created = created
    return article


class EditorRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return user_can_edit_corpus(self.request.user)


class IssueListView(ListView):
    template_name = "corpus/issue_list.html"
    context_object_name = "issues"
    paginate_by = 12

    def get_queryset(self):
        return Issue.objects.select_related("journal").prefetch_related("articles").all()


class ArticleListView(ListView):
    template_name = "corpus/article_list.html"
    context_object_name = "articles"
    paginate_by = 20

    def get_queryset(self):
        self.form = SearchForm(self.request.GET or None)
        queryset = Article.objects.published().select_related("issue", "section", "journal").prefetch_related(
            "article_authors__author",
            "keywords",
        )
        if self.form.is_valid():
            queryset = apply_article_filters(queryset, self.form.cleaned_data)
            if title := self.form.cleaned_data.get("title"):
                queryset = queryset.filter(title__icontains=title)
        return queryset.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_form"] = getattr(self, "form", SearchForm())
        return context


class ArticleDetailView(DetailView):
    template_name = "corpus/article_detail.html"
    context_object_name = "article"
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_queryset(self):
        return (
            Article.objects.published()
            .select_related("issue", "section", "journal", "text")
            .prefetch_related("article_authors__author__affiliations", "keywords", "files")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        article = self.object
        context["related_articles"] = (
            Article.objects.published()
            .filter(section=article.section)
            .exclude(pk=article.pk)
            .select_related("issue", "section")[:4]
        )
        if self.request.user.is_authenticated:
            context["add_to_subcorpus_form"] = AddToSubcorpusForm(user=self.request.user)
        return context


class SearchView(TemplateView):
    template_name = "corpus/search.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = SearchForm(self.request.GET or None)
        results = []
        if form.is_valid() and any(value for value in form.cleaned_data.values() if value not in (None, "", [])):
            results = search_articles(form, user=self.request.user)
        context["search_form"] = form
        context["results"] = results
        context["result_count"] = len(results)
        initial_name = ""
        if form.is_bound and form.is_valid():
            initial_name = form.cleaned_data.get("text_query") or "Запрос по метаданным"
        context["save_query_form"] = SaveQueryForm(
            initial={
                "name": initial_name,
                "serialized_query": serialize_querydict(self.request.GET),
            }
        )
        context["subcorpus_form"] = SavedSubcorpusForm(
            initial={"serialized_filters": serialize_querydict(self.request.GET)}
        )
        return context


class ExportSearchResultsView(View):
    def get(self, request, *args, **kwargs):
        form = SearchForm(request.GET or None)
        if not form.is_valid():
            messages.error(request, "Невозможно экспортировать некорректный запрос.")
            return redirect("corpus:search")
        results = search_articles(form, user=request.user if request.user.is_authenticated else None)
        response = HttpResponse(export_search_results_csv(results), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="search-results.csv"'
        return response


class SaveQueryView(LoginRequiredMixin, FormView):
    form_class = SaveQueryForm
    http_method_names = ["post"]

    def form_valid(self, form):
        search_form = SearchForm(deserialize_payload(form.cleaned_data["serialized_query"]))
        result_count = 0
        if search_form.is_valid():
            result_count = len(search_articles(search_form, user=self.request.user))
        save_query(
            self.request.user,
            form.cleaned_data["name"],
            form.cleaned_data["description"],
            form.cleaned_data["serialized_query"],
            result_count=result_count,
        )
        messages.success(self.request, "Запрос сохранен в личном кабинете.")
        return redirect("accounts:dashboard")


class SavedSubcorpusListView(LoginRequiredMixin, ListView):
    template_name = "corpus/subcorpus_list.html"
    context_object_name = "subcorpora"
    paginate_by = 20

    def get_queryset(self):
        return SavedSubcorpus.objects.filter(user=self.request.user).prefetch_related("articles")


class SavedSubcorpusCreateView(LoginRequiredMixin, FormView):
    template_name = "corpus/subcorpus_create.html"
    form_class = SavedSubcorpusForm

    def get_initial(self):
        initial = super().get_initial()
        initial["serialized_filters"] = serialize_querydict(self.request.GET)
        return initial

    def form_valid(self, form):
        subcorpus = build_subcorpus(
            self.request.user,
            form.cleaned_data["name"],
            form.cleaned_data["description"],
            form.cleaned_data.get("serialized_filters", "{}"),
            is_public=form.cleaned_data["is_public"],
        )
        messages.success(self.request, "Подкорпус сохранен и доступен для повторного анализа.")
        return redirect("corpus:subcorpus-detail", pk=subcorpus.pk)


class SavedSubcorpusDetailView(LoginRequiredMixin, DetailView):
    template_name = "corpus/subcorpus_detail.html"
    context_object_name = "subcorpus"

    def get_queryset(self):
        return SavedSubcorpus.objects.filter(user=self.request.user).prefetch_related(
            "articles__issue",
            "articles__section",
            "articles__article_authors__author",
        )


class AddArticleToSubcorpusView(LoginRequiredMixin, FormView):
    form_class = AddToSubcorpusForm
    http_method_names = ["post"]

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        article = get_object_or_404(Article, pk=self.kwargs["pk"], is_published=True)
        subcorpus = form.cleaned_data["subcorpus"]
        add_article_to_subcorpus(subcorpus, article)
        messages.success(self.request, "Статья добавлена в выбранный подкорпус.")
        return redirect(article.get_absolute_url())


class EditorArticleUploadView(EditorRequiredMixin, FormView):
    template_name = "corpus/editor_upload.html"
    form_class = EditorArticleUploadForm

    def get_initial(self):
        initial = super().get_initial()
        initial["language"] = Article.LANGUAGE_RU
        initial["is_published"] = True
        return initial

    def form_valid(self, form):
        article = create_or_update_editor_article(form.cleaned_data)
        messages.success(
            self.request,
            "Статья добавлена в корпус." if getattr(article, "_editor_created", False) else "Статья обновлена.",
        )
        return redirect(article.get_absolute_url())
