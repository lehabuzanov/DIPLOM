from __future__ import annotations

import hashlib
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.text import slugify
from django.views.generic import DetailView, FormView, ListView, TemplateView, View

from sem_corpus.apps.accounts.utils import user_can_edit_corpus
from sem_corpus.apps.corpus.forms import (
    AddToSubcorpusForm,
    EditorArticleUploadForm,
    SaveQueryForm,
    SavedQueryEditForm,
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
    SavedQuery,
    SavedSubcorpus,
    SearchHistory,
    Section,
    payload_to_querystring,
)
from sem_corpus.apps.corpus.services import (
    add_article_to_subcorpus,
    apply_article_filters,
    build_subcorpus,
    deserialize_payload,
    describe_query_payload,
    export_search_results_csv,
    refresh_subcorpus_totals,
    save_query,
    search_articles,
    serialize_querydict,
    sync_keywords_for_article,
    update_saved_query,
    update_saved_subcorpus,
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


class UserOwnedObjectMixin(LoginRequiredMixin):
    model = None

    def get_object(self):
        return get_object_or_404(self.model, pk=self.kwargs["pk"], user=self.request.user)


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
            if text_query := (self.form.cleaned_data.get("text_query") or "").strip():
                queryset = queryset.filter(
                    Q(title__icontains=text_query)
                    | Q(abstract__icontains=text_query)
                    | Q(text__cleaned_text__icontains=text_query)
                    | Q(keywords__normalized__icontains=text_query.lower())
                    | Q(article_authors__display_name__icontains=text_query)
                    | Q(article_authors__author__last_name__icontains=text_query)
                )
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
        context["article_text"] = getattr(article, "text", None)
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

    def get_saved_query(self):
        if not self.request.user.is_authenticated:
            return None
        saved_query_id = self.request.GET.get("saved_query")
        if not saved_query_id:
            return None
        return SavedQuery.objects.filter(pk=saved_query_id, user=self.request.user).first()

    def get_saved_subcorpus(self):
        if not self.request.user.is_authenticated:
            return None
        subcorpus_id = self.request.GET.get("subcorpus")
        if not subcorpus_id:
            return None
        return SavedSubcorpus.objects.filter(pk=subcorpus_id, user=self.request.user).first()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = SearchForm(self.request.GET or None)
        results = []
        saved_query = self.get_saved_query()
        saved_subcorpus = self.get_saved_subcorpus()
        if form.is_valid() and any(value for value in form.cleaned_data.values() if value not in (None, "", [])):
            results = search_articles(form, user=self.request.user)
        context["search_form"] = form
        context["results"] = results
        context["result_count"] = len(results)
        initial_name = ""
        if form.is_bound and form.is_valid():
            initial_name = form.cleaned_data.get("text_query") or "Запрос по метаданным"
        if saved_query:
            initial_name = saved_query.name
        context["save_query_form"] = SaveQueryForm(
            initial={
                "query_id": saved_query.pk if saved_query else "",
                "name": saved_query.name if saved_query else initial_name,
                "description": saved_query.description if saved_query else "",
                "serialized_query": serialize_querydict(self.request.GET),
            }
        )
        context["subcorpus_form"] = SavedSubcorpusForm(
            initial={
                "subcorpus_id": saved_subcorpus.pk if saved_subcorpus else "",
                "name": saved_subcorpus.name if saved_subcorpus else initial_name,
                "description": saved_subcorpus.description if saved_subcorpus else "",
                "is_public": saved_subcorpus.is_public if saved_subcorpus else False,
                "serialized_filters": serialize_querydict(self.request.GET),
            }
        )
        context["saved_query"] = saved_query
        context["saved_subcorpus"] = saved_subcorpus
        if self.request.user.is_authenticated:
            recent_searches = list(SearchHistory.objects.filter(user=self.request.user)[:6])
            for item in recent_searches:
                filters = dict(item.filters or {})
                if item.query_text:
                    filters["text_query"] = item.query_text
                if item.query_text and item.search_type != SearchHistory.SEARCH_METADATA:
                    filters["search_mode"] = item.search_type
                querystring = payload_to_querystring(filters)
                item.run_url = f"{self.request.path}?{querystring}" if querystring else self.request.path
            context["recent_searches"] = recent_searches
        return context


class ExportSearchResultsView(View):
    def get(self, request, *args, **kwargs):
        form = SearchForm(request.GET or None)
        if not form.is_valid():
            messages.error(request, "Невозможно экспортировать некорректный запрос.")
            return redirect("corpus:search")
        results = search_articles(form, user=request.user if request.user.is_authenticated else None, record_history=False)
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
            result_count = len(search_articles(search_form, user=self.request.user, record_history=False))
        query_id = form.cleaned_data.get("query_id")
        if query_id:
            query = get_object_or_404(SavedQuery, pk=query_id, user=self.request.user)
            update_saved_query(
                query,
                form.cleaned_data["name"],
                form.cleaned_data["description"],
                form.cleaned_data["serialized_query"],
                result_count=result_count,
            )
            messages.success(self.request, "РЎРѕС…СЂР°РЅРµРЅРЅР°СЏ РІС‹Р±РѕСЂРєР° РѕР±РЅРѕРІР»РµРЅР°.")
            return redirect("accounts:dashboard")
        save_query(
            self.request.user,
            form.cleaned_data["name"],
            form.cleaned_data["description"],
            form.cleaned_data["serialized_query"],
            result_count=result_count,
        )
        messages.success(self.request, "Запрос сохранен в личном кабинете.")
        return redirect("accounts:dashboard")


class SavedQueryListView(LoginRequiredMixin, ListView):
    template_name = "corpus/saved_query_list.html"
    context_object_name = "saved_queries"
    paginate_by = 20

    def get_queryset(self):
        return SavedQuery.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for query in context["saved_queries"]:
            query.summary_items = describe_query_payload(query.query_payload)
        return context


class SavedQueryRunView(UserOwnedObjectMixin, View):
    model = SavedQuery

    def get(self, request, *args, **kwargs):
        return redirect(self.get_object().get_search_url())


class SavedQueryUpdateView(UserOwnedObjectMixin, FormView):
    model = SavedQuery
    template_name = "corpus/saved_query_edit.html"
    form_class = SavedQueryEditForm

    def get_initial(self):
        query = self.get_object()
        return {"name": query.name, "description": query.description}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = self.get_object()
        context["saved_query"] = query
        context["query_summary"] = describe_query_payload(query.query_payload)
        return context

    def form_valid(self, form):
        query = self.get_object()
        query.name = form.cleaned_data["name"]
        query.description = form.cleaned_data["description"]
        query.save(update_fields=["name", "description", "updated_at"])
        messages.success(self.request, "РџР°СЂР°РјРµС‚СЂС‹ СЃРѕС…СЂР°РЅРµРЅРЅРѕР№ РІС‹Р±РѕСЂРєРё РѕР±РЅРѕРІР»РµРЅС‹.")
        return redirect("corpus:saved-query-list")


class SavedQueryDeleteView(UserOwnedObjectMixin, View):
    model = SavedQuery
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        query = self.get_object()
        query_name = query.name
        query.delete()
        messages.success(request, f"Р’С‹Р±РѕСЂРєР° «{query_name}» СѓРґР°Р»РµРЅР°.")
        return redirect("corpus:saved-query-list")


class SavedSubcorpusListView(LoginRequiredMixin, ListView):
    template_name = "corpus/subcorpus_list.html"
    context_object_name = "subcorpora"
    paginate_by = 20

    def get_queryset(self):
        return SavedSubcorpus.objects.filter(user=self.request.user).prefetch_related("articles")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for subcorpus in context["subcorpora"]:
            subcorpus.summary_items = describe_query_payload(subcorpus.filter_payload)
        return context


class SavedSubcorpusCreateView(LoginRequiredMixin, FormView):
    template_name = "corpus/subcorpus_create.html"
    form_class = SavedSubcorpusForm

    def get_initial(self):
        initial = super().get_initial()
        initial["serialized_filters"] = serialize_querydict(self.request.GET)
        return initial

    def form_valid(self, form):
        subcorpus_id = form.cleaned_data.get("subcorpus_id")
        if subcorpus_id:
            subcorpus = get_object_or_404(SavedSubcorpus, pk=subcorpus_id, user=self.request.user)
            update_saved_subcorpus(
                subcorpus,
                name=form.cleaned_data["name"],
                description=form.cleaned_data["description"],
                payload=form.cleaned_data.get("serialized_filters", "{}"),
                is_public=form.cleaned_data["is_public"],
            )
            messages.success(self.request, "Подкорпус обновлен и пересобран по новым условиям.")
            return redirect("corpus:subcorpus-detail", pk=subcorpus.pk)
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_summary"] = describe_query_payload(self.object.filter_payload)
        return context


class SavedSubcorpusUpdateView(UserOwnedObjectMixin, FormView):
    model = SavedSubcorpus
    template_name = "corpus/subcorpus_edit.html"
    form_class = SavedSubcorpusForm

    def get_initial(self):
        subcorpus = self.get_object()
        return {
            "subcorpus_id": subcorpus.pk,
            "name": subcorpus.name,
            "description": subcorpus.description,
            "is_public": subcorpus.is_public,
            "serialized_filters": serialize_querydict(subcorpus.filter_payload),
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        subcorpus = self.get_object()
        context["subcorpus"] = subcorpus
        context["filter_summary"] = describe_query_payload(subcorpus.filter_payload)
        return context

    def form_valid(self, form):
        subcorpus = self.get_object()
        update_saved_subcorpus(
            subcorpus,
            name=form.cleaned_data["name"],
            description=form.cleaned_data["description"],
            payload=form.cleaned_data.get("serialized_filters", "{}"),
            is_public=form.cleaned_data["is_public"],
        )
        messages.success(self.request, "Параметры подкорпуса обновлены.")
        return redirect("corpus:subcorpus-detail", pk=subcorpus.pk)
        subcorpus = self.get_object()
        subcorpus.name = form.cleaned_data["name"]
        subcorpus.description = form.cleaned_data["description"]
        subcorpus.is_public = form.cleaned_data["is_public"]
        subcorpus.save(update_fields=["name", "description", "is_public", "updated_at"])
        messages.success(self.request, "РџР°СЂР°РјРµС‚СЂС‹ РїРѕРґРєРѕСЂРїСѓСЃР° РѕР±РЅРѕРІР»РµРЅС‹.")
        return redirect("corpus:subcorpus-detail", pk=subcorpus.pk)


class SavedSubcorpusRefreshView(UserOwnedObjectMixin, View):
    model = SavedSubcorpus
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        subcorpus = self.get_object()
        subcorpus.refresh_membership()
        messages.success(request, "РЎРѕСЃС‚Р°РІ РїРѕРґРєРѕСЂРїСѓСЃР° РѕР±РЅРѕРІР»РµРЅ РїРѕ РёСЃС…РѕРґРЅС‹Рј С„РёР»СЊС‚СЂР°Рј.")
        return redirect("corpus:subcorpus-detail", pk=subcorpus.pk)


class SavedSubcorpusDeleteView(UserOwnedObjectMixin, View):
    model = SavedSubcorpus
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        subcorpus = self.get_object()
        subcorpus_name = subcorpus.name
        subcorpus.delete()
        messages.success(request, f"РџРѕРґРєРѕСЂРїСѓСЃ «{subcorpus_name}» СѓРґР°Р»РµРЅ.")
        return redirect("corpus:subcorpus-list")


class ArticleFileAccessView(View):
    def get(self, request, pk, *args, **kwargs):
        article_file = get_object_or_404(ArticleFile.objects.select_related("article"), pk=pk, article__is_published=True)
        if article_file.file and article_file.file.storage.exists(article_file.file.name):
            return FileResponse(
                article_file.file.open("rb"),
                as_attachment=False,
                filename=article_file.original_filename or Path(article_file.file.name).name,
            )
        if article_file.external_url:
            return redirect(article_file.external_url)
        if article_file.article.original_url:
            return redirect(article_file.article.original_url)
        raise Http404("Article file is unavailable.")


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
