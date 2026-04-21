from django.db.models import Count, Sum
from django.views.generic import TemplateView

from sem_corpus.apps.corpus.models import Article, Author, Issue, Section


class HomeView(TemplateView):
    template_name = "core/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        articles = Article.objects.filter(is_published=True)
        context["stats"] = {
            "issues": Issue.objects.count(),
            "articles": articles.count(),
            "authors": Author.objects.count(),
            "sections": Section.objects.count(),
            "tokens": articles.aggregate(total=Sum("text__token_count")).get("total") or 0,
        }
        context["latest_articles"] = (
            articles.select_related("issue", "section").prefetch_related("article_authors__author")[:6]
        )
        context["articles_per_year"] = list(
            articles.values("issue__year").annotate(total=Count("id")).order_by("issue__year")
        )
        context["sections_overview"] = (
            Section.objects.annotate(total=Count("articles")).filter(total__gt=0).order_by("-total", "name")[:6]
        )
        return context


class AboutView(TemplateView):
    template_name = "core/about.html"


class GuideView(TemplateView):
    template_name = "core/guide.html"
