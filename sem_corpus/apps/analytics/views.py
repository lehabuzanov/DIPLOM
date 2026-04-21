import re

from django.db.models import Count, Q
from django.views.generic import TemplateView

from sem_corpus.apps.analytics.forms import AnalyticsForm
from sem_corpus.apps.corpus.models import Article, Author, Keyword, SavedSubcorpus
from sem_corpus.apps.corpus.services import compare_frequency_sets, get_bigram_data, get_frequency_counts, get_frequency_data


class AnalyticsDashboardView(TemplateView):
    template_name = "analytics/dashboard.html"

    @staticmethod
    def resolve_articles(base_articles, article=None, subcorpus=None):
        if article:
            return base_articles.filter(pk=article.pk), article.title
        if subcorpus:
            return base_articles.filter(pk__in=subcorpus.articles.values("pk")), subcorpus.name
        return base_articles, "Весь корпус"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = AnalyticsForm(self.request.GET or None, user=self.request.user)
        base_articles = Article.objects.published().select_related("text", "issue", "section")
        frequency_rows = []
        bigram_rows = []
        comparison_rows = []
        bigram_note = ""
        comparison_note = ""
        selected_scope_label = "Весь корпус"
        comparison_scope_label = ""

        if form.is_bound and form.is_valid():
            mode = form.cleaned_data.get("mode") or "lemma"
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
            frequency_rows = get_frequency_data(target_articles, mode=mode)

            if selected_article or selected_subcorpus:
                bigram_rows = get_bigram_data(target_articles)
            else:
                bigram_note = "Для биграмм выберите конкретную статью или сохранённый подкорпус."

            if left_article and right_article:
                left_articles, left_label = self.resolve_articles(base_articles, article=left_article)
                right_articles, right_label = self.resolve_articles(base_articles, article=right_article)
                comparison_rows = compare_frequency_sets(left_articles, right_articles, mode=mode)
                comparison_scope_label = f"{left_label} ↔ {right_label}"
            elif left_subcorpus and right_subcorpus:
                left_articles, left_label = self.resolve_articles(base_articles, subcorpus=left_subcorpus)
                right_articles, right_label = self.resolve_articles(base_articles, subcorpus=right_subcorpus)
                comparison_rows = compare_frequency_sets(left_articles, right_articles, mode=mode)
                comparison_scope_label = f"{left_label} ↔ {right_label}"
            elif any([left_article, right_article, left_subcorpus, right_subcorpus]):
                comparison_note = "Для сравнения выберите либо две статьи, либо два подкорпуса."
        else:
            frequency_rows = get_frequency_data(base_articles, mode="lemma")
            bigram_note = "Для биграмм выберите конкретную статью или сохранённый подкорпус."

        context["form"] = form
        context["frequency_rows"] = frequency_rows
        context["bigram_rows"] = bigram_rows
        context["comparison_rows"] = comparison_rows
        context["bigram_note"] = bigram_note
        context["comparison_note"] = comparison_note
        context["selected_scope_label"] = selected_scope_label
        context["comparison_scope_label"] = comparison_scope_label
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


class TagCloudView(TemplateView):
    template_name = "analytics/tag_cloud.html"

    STOPWORDS = {
        "анализ",
        "аспект",
        "влияние",
        "вопрос",
        "данные",
        "исследование",
        "модель",
        "подход",
        "проблема",
        "процесс",
        "развитие",
        "результат",
        "система",
        "социальный",
        "теория",
        "уровень",
        "фактор",
        "экономика",
    }

    WORD_RE = re.compile(r"^[A-Za-zА-Яа-яЁё-]+$")

    def build_from_keywords(self):
        rows = (
            Keyword.objects.annotate(article_total=Count("articles", distinct=True))
            .filter(article_total__gte=2)
            .order_by("-article_total", "name")
        )
        tags = []
        for row in rows:
            label = (row.name or "").strip()
            normalized = (row.normalized or "").strip().lower()
            if " " in label or "," in label:
                continue
            if len(normalized) < 4 or normalized in self.STOPWORDS:
                continue
            if not self.WORD_RE.match(label):
                continue
            tags.append({"label": label, "count": row.article_total})
            if len(tags) >= 32:
                break
        return tags

    def build_from_lemmas(self):
        articles = Article.objects.published()
        rows = get_frequency_counts(articles, mode="lemma")
        tags = []
        for label, count in sorted(rows.items(), key=lambda item: (-item[1], item[0])):
            if len(label) < 4 or label in self.STOPWORDS:
                continue
            if not self.WORD_RE.match(label):
                continue
            if count < 20:
                continue
            tags.append({"label": label, "count": count})
            if len(tags) >= 32:
                break
        return tags

    def enrich_sizes(self, tags):
        if not tags:
            return []
        min_count = min(tag["count"] for tag in tags)
        max_count = max(tag["count"] for tag in tags)
        spread = max(max_count - min_count, 1)
        palette = ["#1748b3", "#1b56ca", "#2366e6", "#2f77ff", "#4b94ff"]
        enriched = []
        for tag in tags:
            weight = (tag["count"] - min_count) / spread
            size = 1.0 + (weight * 1.6)
            color = palette[min(int(weight * (len(palette) - 1)), len(palette) - 1)]
            enriched.append({**tag, "size": round(size, 2), "color": color})
        return enriched

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tags = self.build_from_keywords()
        source = "Ключевые слова статей"
        if len(tags) < 12:
            tags = self.build_from_lemmas()
            source = "Частотные леммы корпуса"
        context["tags"] = self.enrich_sizes(tags)
        context["cloud_source"] = source
        context["tag_total"] = len(context["tags"])
        return context
