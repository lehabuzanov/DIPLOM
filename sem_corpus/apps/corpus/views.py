from __future__ import annotations

import hashlib
import json
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.text import slugify
from django.views.generic import DetailView, FormView, ListView, TemplateView, View
from razdel import sentenize

from sem_corpus.apps.accounts.utils import user_can_edit_corpus, user_can_use_personal_tools
from sem_corpus.apps.corpus.forms import (
    AddToSubcorpusForm,
    EditorArticleUploadForm,
    SaveQueryForm,
    SavedQueryEditForm,
    SavedSubcorpusForm,
    SearchForm,
    SubcorpusArticleAddForm,
)
from sem_corpus.apps.corpus.models import (
    Affiliation,
    Article,
    ArticleAuthor,
    ArticleFile,
    ArticleHighlight,
    ArticleText,
    Author,
    CityLocation,
    Issue,
    Journal,
    SavedQuery,
    SavedSubcorpus,
    SavedSubcorpusArticle,
    SearchHistory,
    Section,
    payload_to_querystring,
)
from sem_corpus.apps.corpus.geo import assign_affiliation_geography, normalize_city_name
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
    serialize_filter_values,
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


SUBCORPUS_LAST_REMOVED_SESSION_KEY = "last_removed_subcorpus_article"


def build_subcorpus_filter_payload(cleaned_data: dict) -> dict:
    payload = serialize_filter_values(cleaned_data)
    if not payload.get("text_query"):
        payload.pop("search_mode", None)
    return {
        key: value
        for key, value in payload.items()
        if key not in {"page", "saved_query", "subcorpus"} and value not in ("", None, [])
    }


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
            assign_affiliation_geography(affiliation)
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


class PersonalToolsRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return user_can_use_personal_tools(self.request.user)


class UserOwnedObjectMixin(PersonalToolsRequiredMixin):
    model = None

    def get_object(self):
        return get_object_or_404(self.model, pk=self.kwargs["pk"], user=self.request.user)


class IssueListView(ListView):
    template_name = "corpus/issue_list.html"
    context_object_name = "issues"
    paginate_by = 12

    def get_queryset(self):
        return (
            Issue.objects.select_related("journal")
            .annotate(
                article_total=Count("articles", distinct=True),
            )
            .order_by("-year", "-publication_date", "-id")
        )


class IssueDetailView(DetailView):
    template_name = "corpus/issue_detail.html"
    context_object_name = "issue"

    def get_queryset(self):
        return Issue.objects.select_related("journal").prefetch_related(
            "articles__section",
            "articles__article_authors__author",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        articles = list(self.object.articles.all().order_by("section__sort_order", "section__name", "title"))
        article_total = len(articles)
        author_ids = set()
        for article in articles:
            for author_link in article.article_authors.all():
                author_ids.add(author_link.author_id)

        context["article_total"] = article_total
        context["author_total"] = len(author_ids)
        context["articles"] = articles
        return context


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
        city_links = []
        seen_city_ids = set()
        author_city_rows = ArticleAuthor.objects.filter(
            article=article,
            affiliation__city_location__isnull=False,
        ).select_related("affiliation__city_location")
        for row in author_city_rows:
            city = row.affiliation.city_location
            if city.pk in seen_city_ids:
                continue
            seen_city_ids.add(city.pk)
            city_links.append(city)
        context["article_text"] = getattr(article, "text", None)
        context["article_cities"] = city_links
        context["related_articles"] = (
            Article.objects.published()
            .filter(section=article.section)
            .exclude(pk=article.pk)
            .select_related("issue", "section")[:4]
        )
        if user_can_use_personal_tools(self.request.user):
            context["add_to_subcorpus_form"] = AddToSubcorpusForm(user=self.request.user)
        return context


def resolve_city_filter(raw_value: str) -> CityLocation | None:
    value = normalize_city_name(raw_value)
    if not value:
        return None
    return (
        CityLocation.objects.filter(normalized_name=value).first()
        or CityLocation.objects.filter(display_name__iexact=raw_value.strip()).first()
        or CityLocation.objects.filter(normalized_name__icontains=value).order_by("display_name").first()
    )


class GeographyDashboardView(TemplateView):
    template_name = "corpus/geography.html"

    ACTIVITY_LEVELS = [
        {"level": "single", "label": "1 статья", "color": "#2f9e67", "min": 1, "max": 1},
        {"level": "low", "label": "2-4 статьи", "color": "#6aa84f", "min": 2, "max": 4},
        {"level": "medium", "label": "5-9 статей", "color": "#d69e2e", "min": 5, "max": 9},
        {"level": "high", "label": "10-24 статьи", "color": "#e36b2c", "min": 10, "max": 24},
        {"level": "very-high", "label": "25-99 статей", "color": "#c43d4b", "min": 25, "max": 99},
        {"level": "leader", "label": "100+ статей", "color": "#6f1d46", "min": 100, "max": None},
    ]

    @classmethod
    def activity_style(cls, article_count: int) -> dict[str, str]:
        for level in cls.ACTIVITY_LEVELS:
            if article_count >= level["min"] and (level["max"] is None or article_count <= level["max"]):
                return {"level": level["level"], "label": level["label"], "color": level["color"]}
        return {"level": "single", "label": "1 статья", "color": "#2f9e67"}

    @staticmethod
    def marker_shape(country: str) -> str:
        return "circle" if (country or "").strip().casefold() == "россия" else "diamond"

    def build_data(self):
        year_values = list(
            ArticleAuthor.objects.filter(
                article__is_published=True,
                affiliation__city_location__isnull=False,
            )
            .order_by("-article__issue__year")
            .values_list("article__issue__year", flat=True)
            .distinct()
        )
        selected_year = (self.request.GET.get("year") or "").strip()
        if selected_year and selected_year not in {str(year) for year in year_values}:
            selected_year = ""

        selected_city = resolve_city_filter(self.request.GET.get("city", ""))
        base_queryset = ArticleAuthor.objects.filter(
            article__is_published=True,
            affiliation__city_location__isnull=False,
        ).select_related(
            "article",
            "article__issue",
            "author",
            "affiliation",
            "affiliation__city_location",
        )
        if selected_year:
            base_queryset = base_queryset.filter(article__issue__year=int(selected_year))
        if selected_city:
            base_queryset = base_queryset.filter(affiliation__city_location=selected_city)

        city_rows = list(
            base_queryset.values(
                "affiliation__city_location_id",
                "affiliation__city_location__display_name",
                "affiliation__city_location__region",
                "affiliation__city_location__country",
                "affiliation__city_location__latitude",
                "affiliation__city_location__longitude",
            )
            .annotate(
                article_count=Count("article", distinct=True),
                author_count=Count("author", distinct=True),
                affiliation_count=Count("affiliation", distinct=True),
            )
            .order_by("-article_count", "-author_count", "affiliation__city_location__display_name")
        )
        rows = [
            {
                "id": row["affiliation__city_location_id"],
                "display_name": row["affiliation__city_location__display_name"],
                "region": row["affiliation__city_location__region"],
                "country": row["affiliation__city_location__country"],
                "latitude": float(row["affiliation__city_location__latitude"]),
                "longitude": float(row["affiliation__city_location__longitude"]),
                "article_count": row["article_count"],
                "author_count": row["author_count"],
                "affiliation_count": row["affiliation_count"],
            }
            for row in city_rows
        ]
        map_points = [
            {
                "id": row["id"],
                "display_name": row["display_name"],
                "region": row["region"],
                "country": row["country"],
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
                "article_count": row["article_count"],
                "author_count": row["author_count"],
                "affiliation_count": row["affiliation_count"],
                **self.activity_style(row["article_count"]),
                "shape": self.marker_shape(row["country"]),
            }
            for row in rows
        ]
        country_rows = list(
            base_queryset.values("affiliation__city_location__country")
            .annotate(
                city_count=Count("affiliation__city_location", distinct=True),
                author_count=Count("author", distinct=True),
                article_count=Count("article", distinct=True),
            )
            .order_by("-article_count", "-author_count", "affiliation__city_location__country")
        )
        country_rows = [
            {
                "country": row["affiliation__city_location__country"],
                "city_count": row["city_count"],
                "author_count": row["author_count"],
                "article_count": row["article_count"],
            }
            for row in country_rows
        ]
        activity_rows = []
        for level in self.ACTIVITY_LEVELS:
            level_cities = [
                row for row in rows if row["article_count"] >= level["min"] and (level["max"] is None or row["article_count"] <= level["max"])
            ]
            activity_rows.append(
                {
                    "level": level["level"],
                    "label": level["label"],
                    "color": level["color"],
                    "city_count": len(level_cities),
                    "article_count": sum(row["article_count"] for row in level_cities),
                }
            )
        article_rows = list(
            base_queryset.values(
                "article_id",
                "article__title",
                "article__slug",
                "article__issue__year",
                "article__issue__volume",
                "article__issue__number",
            )
            .annotate(author_count=Count("author", distinct=True))
            .order_by("-article__issue__year", "article__title")
        )
        timeline_rows = list(
            ArticleAuthor.objects.filter(
                article__is_published=True,
                affiliation__city_location=selected_city,
            )
            .values("article__issue__year")
            .annotate(article_count=Count("article", distinct=True), author_count=Count("author", distinct=True))
            .order_by("article__issue__year")
        ) if selected_city else []

        selected_city_payload = None
        if selected_city:
            selected_city_queryset = ArticleAuthor.objects.filter(
                article__is_published=True,
                affiliation__city_location=selected_city,
            )
            selected_city_years = list(
                selected_city_queryset.order_by("-article__issue__year")
                .values_list("article__issue__year", flat=True)
                .distinct()
            )
            selected_city_payload = {
                "id": selected_city.pk,
                "display_name": selected_city.display_name,
                "region": selected_city.region,
                "country": selected_city.country,
                "latitude": float(selected_city.latitude),
                "longitude": float(selected_city.longitude),
                "available_years": selected_city_years,
                "article_count": selected_city_queryset.values("article_id").distinct().count(),
                "author_count": selected_city_queryset.values("author_id").distinct().count(),
                "affiliation_count": selected_city_queryset.values("affiliation_id").distinct().count(),
            }
            if selected_year and not rows:
                map_points.append(
                    {
                        "id": selected_city.pk,
                        "display_name": selected_city.display_name,
                        "region": selected_city.region,
                        "country": selected_city.country,
                        "latitude": float(selected_city.latitude),
                        "longitude": float(selected_city.longitude),
                        "article_count": 0,
                        "author_count": 0,
                        "affiliation_count": 0,
                        "level": "no-data",
                        "label": "нет статей в выбранном году",
                        "color": "#73808c",
                        "shape": self.marker_shape(selected_city.country),
                        "is_empty": True,
                    }
                )
        country_palette = ["#1f66ff", "#4d7f9f", "#2f9e67", "#d69e2e", "#e36b2c", "#c43d4b", "#6f1d46", "#73808c"]
        chart_payload = {
            "labels": [row["country"] for row in country_rows],
            "cities": [row["city_count"] for row in country_rows],
            "authors": [row["author_count"] for row in country_rows],
            "articles": [row["article_count"] for row in country_rows],
            "colors": [country_palette[index % len(country_palette)] for index, _row in enumerate(country_rows)],
        }
        timeline_payload = {
            "labels": [str(row["article__issue__year"]) for row in timeline_rows],
            "articles": [row["article_count"] for row in timeline_rows],
            "authors": [row["author_count"] for row in timeline_rows],
        }
        return {
            "year_values": year_values,
            "selected_year": selected_year,
            "selected_city": selected_city,
            "selected_city_payload": selected_city_payload,
            "city_rows": rows,
            "country_rows": country_rows,
            "activity_rows": activity_rows,
            "map_points": map_points,
            "article_rows": article_rows,
            "timeline_rows": timeline_rows,
            "city_total": len(rows),
            "country_total": len(country_rows),
            "author_total": base_queryset.values("author_id").distinct().count(),
            "article_total": base_queryset.values("article_id").distinct().count(),
            "top_city": rows[0] if rows else None,
            "chart_data": chart_payload,
            "timeline_data": timeline_payload,
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.build_data())
        context["map_payload"] = json.dumps(context["map_points"], ensure_ascii=False)
        context["city_payload"] = json.dumps(context["city_rows"], ensure_ascii=False)
        context["chart_payload"] = json.dumps(context["chart_data"], ensure_ascii=False)
        context["country_payload"] = json.dumps(context["country_rows"], ensure_ascii=False)
        context["activity_payload"] = json.dumps(context["activity_rows"], ensure_ascii=False)
        context["selected_city_payload_json"] = json.dumps(context["selected_city_payload"], ensure_ascii=False)
        context["timeline_payload"] = json.dumps(context["timeline_data"], ensure_ascii=False)
        return context


class GeographyDataView(GeographyDashboardView, View):
    def get(self, request, *args, **kwargs):
        self.request = request
        data = self.build_data()
        return JsonResponse(
            {
                "selected_year": data["selected_year"],
                "selected_city": data["selected_city_payload"],
                "city_rows": data["city_rows"],
                "country_rows": data["country_rows"],
                "activity_rows": data["activity_rows"],
                "map_points": data["map_points"],
                "article_rows": data["article_rows"],
                "city_total": data["city_total"],
                "country_total": data["country_total"],
                "author_total": data["author_total"],
                "article_total": data["article_total"],
                "top_city": data["top_city"],
                "chart": data["chart_data"],
                "timeline": data["timeline_data"],
            }
        )


def split_article_chunks(body_text: str, *, max_chars: int = 1200) -> list[dict[str, int | str]]:
    source = body_text or ""
    chunks: list[dict[str, int | str]] = []
    cursor = 0

    def append_range(start: int, end: int) -> None:
        if end > start:
            chunks.append({"text": source[start:end], "start": start, "end": end})

    def append_long_range(start: int, end: int) -> None:
        chunk_start = start
        while end - chunk_start > max_chars:
            candidate_end = min(chunk_start + max_chars, end)
            cut = source.rfind(" ", chunk_start, candidate_end + 1)
            if cut <= chunk_start:
                cut = candidate_end
            append_range(chunk_start, cut)
            chunk_start = cut
            while chunk_start < end and source[chunk_start].isspace():
                chunk_start += 1
        append_range(chunk_start, end)

    for raw_paragraph in source.split("\n\n"):
        paragraph_start = source.find(raw_paragraph, cursor)
        cursor = paragraph_start + len(raw_paragraph) + 2
        if not raw_paragraph.strip():
            continue

        left_trim = len(raw_paragraph) - len(raw_paragraph.lstrip())
        right_trim = len(raw_paragraph.rstrip())
        paragraph_start += left_trim
        paragraph_end = paragraph_start + right_trim - left_trim
        paragraph = source[paragraph_start:paragraph_end]

        if len(paragraph) <= max_chars:
            append_range(paragraph_start, paragraph_end)
            continue

        current_start: int | None = None
        current_end: int | None = None
        for sentence in sentenize(paragraph):
            sentence_start = paragraph_start + sentence.start
            sentence_end = paragraph_start + sentence.stop
            if sentence_end <= sentence_start:
                continue
            if sentence_end - sentence_start > max_chars:
                if current_start is not None and current_end is not None:
                    append_range(current_start, current_end)
                    current_start = None
                    current_end = None
                append_long_range(sentence_start, sentence_end)
                continue

            if current_start is None:
                current_start = sentence_start
                current_end = sentence_end
                continue

            if sentence_end - current_start > max_chars:
                append_range(current_start, current_end or sentence_start)
                current_start = sentence_start
                current_end = sentence_end
            else:
                current_end = sentence_end

        if current_start is not None and current_end is not None:
            append_range(current_start, current_end)

    return chunks


class ArticleTextDataView(View):
    DEFAULT_LIMIT = 8
    MAX_LIMIT = 24

    def get(self, request, slug, *args, **kwargs):
        article = get_object_or_404(
            Article.objects.published().select_related("text"),
            slug=slug,
        )
        article_text = getattr(article, "text", None)
        chunks = split_article_chunks(article_text.body_text if article_text else "")

        try:
            offset = max(int(request.GET.get("offset", 0)), 0)
        except (TypeError, ValueError):
            offset = 0
        try:
            limit = int(request.GET.get("limit", self.DEFAULT_LIMIT))
        except (TypeError, ValueError):
            limit = self.DEFAULT_LIMIT
        limit = min(max(limit, 4), self.MAX_LIMIT)

        rows = chunks[offset : offset + limit]
        return JsonResponse(
            {
                "chunks": rows,
                "total": len(chunks),
                "offset": offset,
                "limit": limit,
                "has_more": offset + limit < len(chunks),
            }
        )


class ArticleHighlightDataView(View):
    MAX_SELECTION_LENGTH = 1600

    def get_article(self, slug: str) -> Article:
        return get_object_or_404(Article.objects.published().select_related("text"), slug=slug)

    @staticmethod
    def serialize_highlight(highlight: ArticleHighlight) -> dict[str, int | str]:
        return {
            "id": highlight.pk,
            "start": highlight.char_start,
            "end": highlight.char_end,
            "text": highlight.selected_text,
            "note": highlight.note_text,
        }

    def get(self, request, slug, *args, **kwargs):
        article = self.get_article(slug)
        if not user_can_use_personal_tools(request.user):
            return JsonResponse({"items": []})
        highlights = ArticleHighlight.objects.filter(user=request.user, article=article)
        return JsonResponse({"items": [self.serialize_highlight(item) for item in highlights]})

    def post(self, request, slug, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Требуется вход в систему."}, status=403)
        if not user_can_use_personal_tools(request.user):
            return JsonResponse({"error": "Недостаточно прав для сохранения пометок."}, status=403)

        article = self.get_article(slug)
        article_text = getattr(article, "text", None)
        body_text = article_text.body_text if article_text else ""
        try:
            payload = json.loads(request.body.decode("utf-8"))
            start = int(payload.get("start"))
            end = int(payload.get("end"))
        except (json.JSONDecodeError, TypeError, ValueError):
            return JsonResponse({"error": "Некорректные координаты пометки."}, status=400)

        start = max(start, 0)
        end = min(end, len(body_text))
        selected_text = body_text[start:end]
        leading = len(selected_text) - len(selected_text.lstrip())
        trailing = len(selected_text) - len(selected_text.rstrip())
        start += leading
        end -= trailing
        selected_text = body_text[start:end]

        if end <= start or not selected_text.strip():
            return JsonResponse({"error": "Выделите фрагмент текста."}, status=400)
        if len(selected_text) > self.MAX_SELECTION_LENGTH:
            return JsonResponse({"error": "Пометка слишком длинная. Выберите более короткий фрагмент."}, status=400)
        if ArticleHighlight.objects.filter(
            user=request.user,
            article=article,
            char_start__lt=end,
            char_end__gt=start,
        ).exists():
            return JsonResponse({"error": "Этот фрагмент уже пересекается с существующей пометкой."}, status=409)

        highlight = ArticleHighlight.objects.create(
            user=request.user,
            article=article,
            char_start=start,
            char_end=end,
            selected_text=selected_text,
        )
        return JsonResponse(self.serialize_highlight(highlight), status=201)


class ArticleHighlightDeleteView(PersonalToolsRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk, *args, **kwargs):
        highlight = get_object_or_404(ArticleHighlight, pk=pk, user=request.user)
        highlight.delete()
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"deleted": True})
        messages.success(request, "Пометка удалена.")
        return redirect("accounts:highlights")


class ArticleHighlightUpdateView(PersonalToolsRequiredMixin, View):
    MAX_NOTE_LENGTH = 1200
    http_method_names = ["post"]

    def post(self, request, pk, *args, **kwargs):
        highlight = get_object_or_404(ArticleHighlight, pk=pk, user=request.user)
        note_text = (request.POST.get("note_text") or "").strip()
        if len(note_text) > self.MAX_NOTE_LENGTH:
            messages.error(request, "Комментарий слишком длинный.")
            return redirect("accounts:highlights")
        highlight.note_text = note_text
        highlight.save(update_fields=["note_text", "updated_at"])
        messages.success(request, "Комментарий к пометке обновлен.")
        return redirect("accounts:highlights")


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
        if user_can_use_personal_tools(self.request.user):
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


class SuggestionView(View):
    DEFAULT_LIMIT = 20
    MAX_LIMIT = 400

    @staticmethod
    def article_sort_key(title: str):
        normalized = (title or "").strip()
        first_alpha = next((char for char in normalized if char.isalpha()), "")
        if "\u0400" <= first_alpha <= "\u04ff":
            script_rank = 0
        elif "A" <= first_alpha.upper() <= "Z":
            script_rank = 1
        else:
            script_rank = 2
        return script_rank, normalized.casefold()

    def get_values(self, kind: str, query: str):
        if kind == "articles":
            queryset = Article.objects.published()
            if query:
                queryset = queryset.filter(title__icontains=query)
            titles = list(queryset.values_list("title", flat=True))
            titles.sort(key=self.article_sort_key)
            return titles[: self.limit]

        if kind == "cities":
            queryset = (
                CityLocation.objects.filter(affiliations__article_authors__article__is_published=True)
                .distinct()
                .order_by("display_name")
            )
            if query:
                queryset = queryset.filter(display_name__icontains=query)
            return list(queryset.values_list("display_name", flat=True)[: self.limit])

        if kind == "volumes":
            queryset = Issue.objects.order_by("volume").values_list("volume", flat=True).distinct()
        elif kind == "issues":
            queryset = Issue.objects.order_by("number").values_list("number", flat=True).distinct()
        else:
            raise Http404("Unknown suggestion source.")

        values = [value for value in queryset if value]
        if query:
            normalized_query = query.casefold()
            values = [value for value in values if normalized_query in value.casefold()]
        return values[: self.limit]

    def get(self, request, kind, *args, **kwargs):
        default_limit = self.MAX_LIMIT if kind == "articles" and not (request.GET.get("q") or "").strip() else self.DEFAULT_LIMIT
        try:
            requested_limit = int(request.GET.get("limit", default_limit))
        except (TypeError, ValueError):
            requested_limit = default_limit
        self.limit = min(max(requested_limit, 1), self.MAX_LIMIT)
        query = (request.GET.get("q") or "").strip()
        return JsonResponse({"items": self.get_values(kind, query)})


class SaveQueryView(PersonalToolsRequiredMixin, FormView):
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
            messages.success(self.request, "Сохраненный запрос обновлен.")
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


class SavedQueryListView(PersonalToolsRequiredMixin, ListView):
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
        messages.success(self.request, "Параметры сохраненного запроса обновлены.")
        return redirect("corpus:saved-query-list")


class SavedQueryDeleteView(UserOwnedObjectMixin, View):
    model = SavedQuery
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        query = self.get_object()
        query_name = query.name
        query.delete()
        messages.success(request, f"Запрос «{query_name}» удален.")
        return redirect("corpus:saved-query-list")


class SavedSubcorpusListView(PersonalToolsRequiredMixin, ListView):
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


class SavedSubcorpusCreateView(PersonalToolsRequiredMixin, FormView):
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


class SavedSubcorpusDetailView(PersonalToolsRequiredMixin, DetailView):
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
        subcorpus = self.object
        context["filter_summary"] = describe_query_payload(subcorpus.filter_payload)
        context["add_article_form"] = SubcorpusArticleAddForm(subcorpus=subcorpus)
        context["article_links"] = (
            subcorpus.subcorpus_articles.select_related("article", "article__issue", "article__section")
            .prefetch_related("article__article_authors__author")
            .order_by("article__issue__year", "article__title", "id")
        )
        removed_payload = self.request.session.get(SUBCORPUS_LAST_REMOVED_SESSION_KEY) or {}
        removed_article = None
        if removed_payload.get("subcorpus_id") == subcorpus.pk:
            removed_article = Article.objects.filter(pk=removed_payload.get("article_id"), is_published=True).first()
        context["removed_article"] = removed_article
        return context


class SavedSubcorpusFilterUpdateView(SavedSubcorpusDetailView):
    model = SavedSubcorpus
    template_name = "corpus/subcorpus_filters.html"
    http_method_names = ["get", "post"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = SearchForm(initial=self.object.filter_payload or {})
        return context

    def post(self, request, *args, **kwargs):
        subcorpus = self.get_object()
        form = SearchForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Проверьте условия отбора: часть значений заполнена некорректно.")
            return redirect("corpus:subcorpus-detail", pk=subcorpus.pk)

        subcorpus.filter_payload = build_subcorpus_filter_payload(form.cleaned_data)
        subcorpus.save(update_fields=["filter_payload", "updated_at"])
        subcorpus.refresh_membership()
        messages.success(request, "Фильтры применены, состав подкорпуса обновлен.")
        return redirect("corpus:subcorpus-detail", pk=subcorpus.pk)


class SavedSubcorpusArticleAddView(UserOwnedObjectMixin, View):
    model = SavedSubcorpus
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        subcorpus = self.get_object()
        form = SubcorpusArticleAddForm(request.POST, subcorpus=subcorpus)
        if not form.is_valid():
            messages.error(request, "Выберите статью, которой еще нет в этом подкорпусе.")
            return redirect("corpus:subcorpus-detail", pk=subcorpus.pk)

        article = form.cleaned_data["article"]
        add_article_to_subcorpus(subcorpus, article)
        request.session.pop(SUBCORPUS_LAST_REMOVED_SESSION_KEY, None)
        messages.success(request, f"Статья «{article.title}» добавлена в подкорпус.")
        return redirect("corpus:subcorpus-detail", pk=subcorpus.pk)


class SavedSubcorpusArticleRemoveView(UserOwnedObjectMixin, View):
    model = SavedSubcorpus
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        subcorpus = self.get_object()
        link = get_object_or_404(
            SavedSubcorpusArticle.objects.select_related("article"),
            subcorpus=subcorpus,
            article_id=kwargs["article_pk"],
        )
        removed_payload = {
            "subcorpus_id": subcorpus.pk,
            "article_id": link.article_id,
            "source": link.source,
        }
        article_title = link.article.title
        link.delete()
        refresh_subcorpus_totals(subcorpus)
        request.session[SUBCORPUS_LAST_REMOVED_SESSION_KEY] = removed_payload
        request.session.modified = True
        messages.success(request, f"Статья «{article_title}» убрана только из этого подкорпуса.")
        return redirect("corpus:subcorpus-detail", pk=subcorpus.pk)


class SavedSubcorpusArticleRestoreView(UserOwnedObjectMixin, View):
    model = SavedSubcorpus
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        subcorpus = self.get_object()
        removed_payload = request.session.get(SUBCORPUS_LAST_REMOVED_SESSION_KEY) or {}
        if removed_payload.get("subcorpus_id") != subcorpus.pk:
            messages.error(request, "Нет статьи для возврата в этот подкорпус.")
            return redirect("corpus:subcorpus-detail", pk=subcorpus.pk)

        article = get_object_or_404(Article.objects.published(), pk=removed_payload.get("article_id"))
        SavedSubcorpusArticle.objects.get_or_create(
            subcorpus=subcorpus,
            article=article,
            defaults={"source": removed_payload.get("source") or SavedSubcorpusArticle.SOURCE_MANUAL},
        )
        refresh_subcorpus_totals(subcorpus)
        request.session.pop(SUBCORPUS_LAST_REMOVED_SESSION_KEY, None)
        messages.success(request, f"Статья «{article.title}» возвращена в подкорпус.")
        return redirect("corpus:subcorpus-detail", pk=subcorpus.pk)


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


class SavedSubcorpusRefreshView(UserOwnedObjectMixin, View):
    model = SavedSubcorpus
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        subcorpus = self.get_object()
        subcorpus.refresh_membership()
        messages.success(request, "Состав подкорпуса обновлен по сохраненным фильтрам.")
        return redirect("corpus:subcorpus-detail", pk=subcorpus.pk)


class SavedSubcorpusDeleteView(UserOwnedObjectMixin, View):
    model = SavedSubcorpus
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        subcorpus = self.get_object()
        subcorpus_name = subcorpus.name
        subcorpus.delete()
        messages.success(request, f"Подкорпус «{subcorpus_name}» удален.")
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


class AddArticleToSubcorpusView(PersonalToolsRequiredMixin, FormView):
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
