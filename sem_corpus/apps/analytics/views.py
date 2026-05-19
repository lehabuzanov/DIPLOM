from functools import lru_cache
from hashlib import sha1

from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.views.generic import TemplateView, View

from sem_corpus.apps.analytics.forms import AnalyticsForm
from sem_corpus.apps.corpus.models import Article, Author, SavedSubcorpus
from sem_corpus.apps.corpus.services import (
    ANALYTICS_FILTER_CHOICES,
    ANALYTICS_FILTER_CURATED,
    ANALYTICS_FILTER_HELP,
    compare_frequency_sets,
    export_comparison_rows_csv,
    export_rows_csv,
    get_bigram_data,
    get_frequency_data,
)


def _serialize_rows(rows):
    return tuple((row["label"], row["count"]) for row in rows)


def _deserialize_rows(rows):
    return [{"label": label, "count": count} for label, count in rows]


def _serialize_comparison_rows(rows):
    return tuple(
        (
            row["label"],
            row["left_count"],
            row["right_count"],
            row["shared_count"],
            row["total_count"],
        )
        for row in rows
    )


def _deserialize_comparison_rows(rows):
    return [
        {
            "label": label,
            "left_count": left_count,
            "right_count": right_count,
            "shared_count": shared_count,
            "total_count": total_count,
        }
        for label, left_count, right_count, shared_count, total_count in rows
    ]


def _matches_analytics_query(label: str, query: str) -> bool:
    normalized_label = (label or "").lower()
    normalized_query = (query or "").strip().lower()
    if not normalized_query:
        return True

    parts = [part for part in normalized_label.split() if part]
    if len(normalized_query) <= 2:
        return normalized_label == normalized_query or normalized_query in parts
    return any(part.startswith(normalized_query) for part in parts) or normalized_query in normalized_label


@lru_cache(maxsize=32)
def _cached_frequency_rows(article_ids, signature: str, mode: str, filter_mode: str):
    queryset = Article.objects.filter(pk__in=article_ids)
    return _serialize_rows(get_frequency_data(queryset, mode=mode, limit=None, filter_mode=filter_mode))


@lru_cache(maxsize=32)
def _cached_bigram_rows(article_ids, signature: str, filter_mode: str):
    queryset = Article.objects.filter(pk__in=article_ids)
    return _serialize_rows(get_bigram_data(queryset, limit=None, filter_mode=filter_mode))


@lru_cache(maxsize=32)
def _cached_comparison_rows(
    left_article_ids,
    left_signature: str,
    right_article_ids,
    right_signature: str,
    mode: str,
    filter_mode: str,
):
    left_queryset = Article.objects.filter(pk__in=left_article_ids)
    right_queryset = Article.objects.filter(pk__in=right_article_ids)
    return _serialize_comparison_rows(
        compare_frequency_sets(
            left_queryset,
            right_queryset,
            mode=mode,
            limit=None,
            filter_mode=filter_mode,
        )
    )


def _sort_comparison_rows(rows, sort_mode: str):
    if sort_mode == "shared_asc":
        return sorted(rows, key=lambda row: (row["shared_count"], row["total_count"], row["label"]))
    if sort_mode == "left_desc":
        return sorted(rows, key=lambda row: (-row["left_count"], -row["shared_count"], row["label"]))
    if sort_mode == "right_desc":
        return sorted(rows, key=lambda row: (-row["right_count"], -row["shared_count"], row["label"]))
    if sort_mode == "alpha":
        return sorted(rows, key=lambda row: row["label"])
    return sorted(rows, key=lambda row: (-row["shared_count"], -row["total_count"], row["label"]))


class AnalyticsMixin:
    @staticmethod
    def resolve_articles(base_articles, article=None, subcorpus=None):
        if article:
            return base_articles.filter(pk=article.pk), article.title
        if subcorpus:
            return base_articles.filter(pk__in=subcorpus.articles.values("pk")), subcorpus.name
        return base_articles, "Весь корпус"

    def build_payload(self, *, include_lists: bool = True, dataset: str = "all"):
        form = AnalyticsForm(self.request.GET or None, user=self.request.user)
        base_articles = Article.objects.published().select_related("text", "issue", "section")
        frequency_rows = []
        bigram_rows = []
        comparison_rows = []
        comparison_note = ""
        selected_scope_label = "Весь корпус"
        comparison_scope_label = ""
        comparison_ready = False
        mode = "lemma"
        filter_mode = ANALYTICS_FILTER_CURATED

        if form.is_bound and form.is_valid():
            mode = form.cleaned_data.get("mode") or "lemma"
            filter_mode = form.cleaned_data.get("filter_mode") or ANALYTICS_FILTER_CURATED
            selected_subcorpus = form.cleaned_data.get("subcorpus")
            selected_article = form.cleaned_data.get("article")
            left_article = form.cleaned_data.get("left_article")
            right_article = form.cleaned_data.get("right_article")
            left_subcorpus = form.cleaned_data.get("left_subcorpus")
            right_subcorpus = form.cleaned_data.get("right_subcorpus")

            target_articles, selected_scope_label = self.resolve_articles(
                base_articles,
                article=selected_article,
                subcorpus=selected_subcorpus,
            )

            comparison_pair = self.resolve_comparison_pair(
                base_articles,
                left_article=left_article,
                right_article=right_article,
                left_subcorpus=left_subcorpus,
                right_subcorpus=right_subcorpus,
            )
            if not selected_article and not selected_subcorpus and comparison_pair:
                left_articles, right_articles, _left_label, _right_label = comparison_pair
                target_articles = (left_articles | right_articles).distinct()
                selected_scope_label = "Материалы сравнения"

            if include_lists and dataset in {"all", "frequency"}:
                frequency_rows = get_frequency_data(target_articles, mode=mode, limit=None, filter_mode=filter_mode)
            if include_lists and dataset in {"all", "bigrams"}:
                bigram_rows = get_bigram_data(target_articles, limit=None, filter_mode=filter_mode)

            if comparison_pair:
                _left_articles, _right_articles, left_label, right_label = comparison_pair
                comparison_ready = True
                comparison_scope_label = f"{left_label} ↔ {right_label}"
            elif any([left_article, right_article, left_subcorpus, right_subcorpus]):
                comparison_note = "Для сравнения выберите либо две статьи, либо два подкорпуса."
        else:
            if include_lists and dataset in {"all", "frequency"}:
                frequency_rows = get_frequency_data(base_articles, mode=mode, limit=None, filter_mode=filter_mode)
            if include_lists and dataset in {"all", "bigrams"}:
                bigram_rows = get_bigram_data(base_articles, limit=None, filter_mode=filter_mode)

        return {
            "form": form,
            "base_articles": base_articles,
            "frequency_rows": frequency_rows,
            "bigram_rows": bigram_rows,
            "comparison_rows": comparison_rows,
            "comparison_note": comparison_note,
            "selected_scope_label": selected_scope_label,
            "filter_mode_label": dict(ANALYTICS_FILTER_CHOICES).get(filter_mode, filter_mode),
            "comparison_scope_label": comparison_scope_label,
            "comparison_ready": comparison_ready,
            "mode": mode,
            "filter_mode": filter_mode,
            "frequency_total": len(frequency_rows),
            "bigram_total": len(bigram_rows),
        }

    @staticmethod
    def build_article_signature(articles_queryset):
        rows = list(articles_queryset.values_list("pk", "updated_at").order_by("pk"))
        article_ids = tuple(row[0] for row in rows)
        signature_source = "|".join(
            f"{article_id}:{updated_at.isoformat() if updated_at else ''}" for article_id, updated_at in rows
        )
        signature = sha1(signature_source.encode("utf-8")).hexdigest()
        return article_ids, signature

    def resolve_comparison_pair(
        self,
        base_articles,
        *,
        left_article=None,
        right_article=None,
        left_subcorpus=None,
        right_subcorpus=None,
    ):
        if left_article and right_article:
            left_articles, left_label = self.resolve_articles(base_articles, article=left_article)
            right_articles, right_label = self.resolve_articles(base_articles, article=right_article)
            return left_articles, right_articles, left_label, right_label
        if left_subcorpus and right_subcorpus:
            left_articles, left_label = self.resolve_articles(base_articles, subcorpus=left_subcorpus)
            right_articles, right_label = self.resolve_articles(base_articles, subcorpus=right_subcorpus)
            return left_articles, right_articles, left_label, right_label
        return None

    def get_dataset_rows(self, articles_queryset, *, dataset: str, mode: str, filter_mode: str):
        article_ids, signature = self.build_article_signature(articles_queryset)
        if not article_ids:
            return []
        if dataset == "bigrams":
            return _deserialize_rows(_cached_bigram_rows(article_ids, signature, filter_mode))
        return _deserialize_rows(_cached_frequency_rows(article_ids, signature, mode, filter_mode))

    def get_comparison_dataset_rows(self, left_articles, right_articles, *, mode: str, filter_mode: str):
        left_ids, left_signature = self.build_article_signature(left_articles)
        right_ids, right_signature = self.build_article_signature(right_articles)
        if not left_ids or not right_ids:
            return []
        return _deserialize_comparison_rows(
            _cached_comparison_rows(
                left_ids,
                left_signature,
                right_ids,
                right_signature,
                mode,
                filter_mode,
            )
        )


class AnalyticsDashboardView(AnalyticsMixin, TemplateView):
    template_name = "analytics/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        payload = self.build_payload(include_lists=False)
        base_articles = payload["base_articles"]

        context.update(payload)
        context["filter_help_text"] = ANALYTICS_FILTER_HELP.get(payload["filter_mode"], "")
        context["articles_per_year"] = list(
            base_articles.values("issue__year").annotate(total=Count("id")).order_by("issue__year")
        )
        context["top_authors"] = [
            {"label": author.full_name, "total": author.total}
            for author in Author.objects.annotate(
                total=Count("articles", filter=Q(articles__is_published=True), distinct=True)
            )
            .filter(total__gt=0)
            .order_by("-total", "last_name", "first_name", "middle_name")[:10]
        ]
        context["public_subcorpora"] = SavedSubcorpus.objects.filter(is_public=True)[:6]
        return context


class AnalyticsExportView(AnalyticsMixin, View):
    def get(self, request, *args, **kwargs):
        export_type = request.GET.get("export") or "frequency"
        payload = self.build_payload(include_lists=False)
        selected_subcorpus = payload["form"].cleaned_data.get("subcorpus") if payload["form"].is_bound and payload["form"].is_valid() else None
        selected_article = payload["form"].cleaned_data.get("article") if payload["form"].is_bound and payload["form"].is_valid() else None
        target_articles, _label = self.resolve_articles(
            payload["base_articles"],
            article=selected_article,
            subcorpus=selected_subcorpus,
        )

        if export_type == "bigrams":
            bigram_rows = self.get_dataset_rows(
                target_articles,
                dataset="bigrams",
                mode=payload["mode"],
                filter_mode=payload["filter_mode"],
            )
            response = HttpResponse(export_rows_csv(bigram_rows, "Сочетание"), content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = 'attachment; filename="analytics-bigrams.csv"'
            return response
        if export_type == "comparison":
            comparison_pair = None
            if payload["form"].is_bound and payload["form"].is_valid():
                comparison_pair = self.resolve_comparison_pair(
                    payload["base_articles"],
                    left_article=payload["form"].cleaned_data.get("left_article"),
                    right_article=payload["form"].cleaned_data.get("right_article"),
                    left_subcorpus=payload["form"].cleaned_data.get("left_subcorpus"),
                    right_subcorpus=payload["form"].cleaned_data.get("right_subcorpus"),
                )
            comparison_rows = []
            if comparison_pair:
                left_articles, right_articles, _left_label, _right_label = comparison_pair
                comparison_rows = _sort_comparison_rows(
                    self.get_comparison_dataset_rows(
                        left_articles,
                        right_articles,
                        mode=payload["mode"],
                        filter_mode=payload["filter_mode"],
                    ),
                    request.GET.get("sort") or "shared_desc",
                )
            response = HttpResponse(export_comparison_rows_csv(comparison_rows), content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = 'attachment; filename="analytics-comparison.csv"'
            return response

        frequency_rows = self.get_dataset_rows(
            target_articles,
            dataset="frequency",
            mode=payload["mode"],
            filter_mode=payload["filter_mode"],
        )
        response = HttpResponse(export_rows_csv(frequency_rows, "Единица"), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="analytics-frequency.csv"'
        return response


class AnalyticsDataView(AnalyticsMixin, View):
    DEFAULT_LIMIT = 35
    MAX_LIMIT = 160

    def get(self, request, *args, **kwargs):
        dataset = request.GET.get("dataset") or "frequency"
        payload = self.build_payload(include_lists=False)
        query = (request.GET.get("q") or "").strip().lower()
        sort_mode = request.GET.get("sort") or "shared_desc"

        try:
            offset = max(int(request.GET.get("offset", 0)), 0)
        except (TypeError, ValueError):
            offset = 0
        try:
            limit = int(request.GET.get("limit", self.DEFAULT_LIMIT))
        except (TypeError, ValueError):
            limit = self.DEFAULT_LIMIT
        limit = min(max(limit, 20), self.MAX_LIMIT)

        form_is_ready = payload["form"].is_bound and payload["form"].is_valid()
        selected_subcorpus = payload["form"].cleaned_data.get("subcorpus") if form_is_ready else None
        selected_article = payload["form"].cleaned_data.get("article") if form_is_ready else None

        comparison_pair = None
        if form_is_ready:
            comparison_pair = self.resolve_comparison_pair(
                payload["base_articles"],
                left_article=payload["form"].cleaned_data.get("left_article"),
                right_article=payload["form"].cleaned_data.get("right_article"),
                left_subcorpus=payload["form"].cleaned_data.get("left_subcorpus"),
                right_subcorpus=payload["form"].cleaned_data.get("right_subcorpus"),
            )

        if dataset == "comparison":
            rows = []
            if comparison_pair:
                left_articles, right_articles, _left_label, _right_label = comparison_pair
                rows = _sort_comparison_rows(
                    self.get_comparison_dataset_rows(
                        left_articles,
                        right_articles,
                        mode=payload["mode"],
                        filter_mode=payload["filter_mode"],
                    ),
                    sort_mode,
                )
        else:
            target_articles, _label = self.resolve_articles(
                payload["base_articles"],
                article=selected_article,
                subcorpus=selected_subcorpus,
            )
            if not selected_article and not selected_subcorpus and comparison_pair:
                left_articles, right_articles, _left_label, _right_label = comparison_pair
                target_articles = (left_articles | right_articles).distinct()
            rows = self.get_dataset_rows(
                target_articles,
                dataset=dataset,
                mode=payload["mode"],
                filter_mode=payload["filter_mode"],
            )
        if query:
            rows = [row for row in rows if _matches_analytics_query(row["label"], query)]

        sliced_rows = rows[offset : offset + limit]
        return JsonResponse(
            {
                "rows": sliced_rows,
                "total": len(rows),
                "offset": offset,
                "limit": limit,
                "has_more": offset + limit < len(rows),
            }
        )
