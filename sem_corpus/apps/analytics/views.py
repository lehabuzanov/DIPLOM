from django.db.models import Count
from django.views.generic import TemplateView

from sem_corpus.apps.analytics.forms import AnalyticsForm
from sem_corpus.apps.corpus.models import Article, SavedSubcorpus, Section
from sem_corpus.apps.corpus.services import compare_subcorpora, get_bigram_data, get_frequency_data


class AnalyticsDashboardView(TemplateView):
    template_name = "analytics/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = AnalyticsForm(self.request.GET or None, user=self.request.user)
        base_articles = Article.objects.published().select_related("text", "issue", "section")
        frequency_rows = []
        bigram_rows = []
        comparison_rows = []

        if form.is_bound and form.is_valid():
            mode = form.cleaned_data.get("mode") or "lemma"
            selected_subcorpus = form.cleaned_data.get("subcorpus")
            left_subcorpus = form.cleaned_data.get("left_subcorpus")
            right_subcorpus = form.cleaned_data.get("right_subcorpus")
            target_articles = selected_subcorpus.articles.all() if selected_subcorpus else base_articles
            frequency_rows = get_frequency_data(target_articles, mode=mode)
            bigram_rows = get_bigram_data(target_articles)
            if left_subcorpus and right_subcorpus:
                comparison_rows = compare_subcorpora(left_subcorpus, right_subcorpus)

        context["form"] = form
        context["frequency_rows"] = frequency_rows
        context["bigram_rows"] = bigram_rows
        context["comparison_rows"] = comparison_rows
        context["articles_per_year"] = list(
            base_articles.values("issue__year").annotate(total=Count("id")).order_by("issue__year")
        )
        context["articles_per_section"] = list(
            Section.objects.annotate(total=Count("articles")).values("name", "total").order_by("-total")
        )
        context["public_subcorpora"] = SavedSubcorpus.objects.filter(is_public=True)[:6]
        return context
