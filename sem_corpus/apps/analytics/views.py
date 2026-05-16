from django.db.models import Count, Q
from django.http import HttpResponse
from django.views.generic import TemplateView, View

from sem_corpus.apps.analytics.forms import AnalyticsForm
from sem_corpus.apps.corpus.models import Article, Author, SavedSubcorpus
from sem_corpus.apps.corpus.services import (
    ANALYTICS_FILTER_CURATED,
    ANALYTICS_FILTER_HELP,
    compare_frequency_sets,
    export_comparison_rows_csv,
    export_rows_csv,
    get_bigram_data,
    get_frequency_data,
)


class AnalyticsMixin:
    @staticmethod
    def resolve_articles(base_articles, article=None, subcorpus=None):
        if article:
            return base_articles.filter(pk=article.pk), article.title
        if subcorpus:
            return base_articles.filter(pk__in=subcorpus.articles.values("pk")), subcorpus.name
        return base_articles, "Весь корпус"

    def build_payload(self):
        form = AnalyticsForm(self.request.GET or None, user=self.request.user)
        base_articles = Article.objects.published().select_related("text", "issue", "section")
        frequency_rows = []
        bigram_rows = []
        comparison_rows = []
        comparison_note = ""
        selected_scope_label = "Весь корпус"
        comparison_scope_label = ""
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
            frequency_rows = get_frequency_data(target_articles, mode=mode, filter_mode=filter_mode)
            bigram_rows = get_bigram_data(target_articles, filter_mode=filter_mode)

            if left_article and right_article:
                left_articles, left_label = self.resolve_articles(base_articles, article=left_article)
                right_articles, right_label = self.resolve_articles(base_articles, article=right_article)
                comparison_rows = compare_frequency_sets(
                    left_articles,
                    right_articles,
                    mode=mode,
                    filter_mode=filter_mode,
                )
                comparison_scope_label = f"{left_label} ↔ {right_label}"
            elif left_subcorpus and right_subcorpus:
                left_articles, left_label = self.resolve_articles(base_articles, subcorpus=left_subcorpus)
                right_articles, right_label = self.resolve_articles(base_articles, subcorpus=right_subcorpus)
                comparison_rows = compare_frequency_sets(
                    left_articles,
                    right_articles,
                    mode=mode,
                    filter_mode=filter_mode,
                )
                comparison_scope_label = f"{left_label} ↔ {right_label}"
            elif any([left_article, right_article, left_subcorpus, right_subcorpus]):
                comparison_note = "Для сравнения выберите либо две статьи, либо два подкорпуса."
        else:
            frequency_rows = get_frequency_data(base_articles, mode=mode, filter_mode=filter_mode)
            bigram_rows = get_bigram_data(base_articles, filter_mode=filter_mode)

        return {
            "form": form,
            "base_articles": base_articles,
            "frequency_rows": frequency_rows,
            "bigram_rows": bigram_rows,
            "comparison_rows": comparison_rows,
            "comparison_note": comparison_note,
            "selected_scope_label": selected_scope_label,
            "comparison_scope_label": comparison_scope_label,
            "mode": mode,
            "filter_mode": filter_mode,
        }


class AnalyticsDashboardView(AnalyticsMixin, TemplateView):
    template_name = "analytics/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        payload = self.build_payload()
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
        payload = self.build_payload()
        export_type = request.GET.get("export") or "frequency"

        if export_type == "bigrams":
            response = HttpResponse(export_rows_csv(payload["bigram_rows"], "Сочетание"), content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = 'attachment; filename="analytics-bigrams.csv"'
            return response
        if export_type == "comparison":
            response = HttpResponse(export_comparison_rows_csv(payload["comparison_rows"]), content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = 'attachment; filename="analytics-comparison.csv"'
            return response

        response = HttpResponse(export_rows_csv(payload["frequency_rows"], "Единица"), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="analytics-frequency.csv"'
        return response
