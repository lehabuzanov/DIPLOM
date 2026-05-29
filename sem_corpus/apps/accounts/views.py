from collections import OrderedDict

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import redirect
from django.views.generic import FormView, TemplateView

from sem_corpus.apps.accounts.forms import RegistrationForm
from sem_corpus.apps.accounts.models import UserActivity
from sem_corpus.apps.accounts.utils import repair_legacy_mojibake, user_can_use_personal_tools
from sem_corpus.apps.corpus.models import ArticleHighlight, SavedQuery, SavedSubcorpus
from sem_corpus.apps.corpus.services import describe_query_payload


class RegistrationView(FormView):
    template_name = "accounts/register.html"
    form_class = RegistrationForm

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        UserActivity.objects.create(
            user=user,
            activity_type=UserActivity.LOGIN,
            title="Создана учетная запись",
            payload={"username": user.username},
        )
        messages.success(self.request, "Регистрация завершена. Личный кабинет готов к работе.")
        return redirect("accounts:dashboard")


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context["saved_queries"] = SavedQuery.objects.filter(user=user)[:10]
        context["saved_subcorpora"] = SavedSubcorpus.objects.filter(user=user)[:10]
        context["highlight_count"] = ArticleHighlight.objects.filter(user=user).count()
        context["highlight_article_count"] = (
            ArticleHighlight.objects.filter(user=user).values("article_id").distinct().count()
        )
        for query in context["saved_queries"]:
            query.summary_items = describe_query_payload(query.query_payload)
        for subcorpus in context["saved_subcorpora"]:
            subcorpus.summary_items = describe_query_payload(subcorpus.filter_payload)
        context["recent_activity"] = UserActivity.objects.filter(user=user)[:12]
        for item in context["recent_activity"]:
            item.display_title = repair_legacy_mojibake(item.title)
        return context


class PersonalToolsRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return user_can_use_personal_tools(self.request.user)


class HighlightListView(PersonalToolsRequiredMixin, TemplateView):
    template_name = "accounts/highlight_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        highlights = (
            ArticleHighlight.objects.filter(user=self.request.user)
            .select_related("article", "article__issue")
            .order_by("article__title", "char_start", "id")
        )
        grouped: OrderedDict[int, dict] = OrderedDict()
        for highlight in highlights:
            bucket = grouped.setdefault(
                highlight.article_id,
                {
                    "article": highlight.article,
                    "highlights": [],
                },
            )
            bucket["highlights"].append(highlight)
        context["highlight_groups"] = list(grouped.values())
        context["highlight_count"] = highlights.count()
        return context
