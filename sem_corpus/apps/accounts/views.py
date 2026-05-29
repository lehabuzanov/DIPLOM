from collections import OrderedDict

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login, update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.mail import send_mail
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.generic import FormView, TemplateView

from sem_corpus.apps.accounts.forms import RegistrationForm
from sem_corpus.apps.accounts.models import UserActivity
from sem_corpus.apps.accounts.tokens import email_activation_token
from sem_corpus.apps.accounts.utils import repair_legacy_mojibake, user_can_use_personal_tools
from sem_corpus.apps.corpus.models import ArticleHighlight, SavedQuery, SavedSubcorpus
from sem_corpus.apps.corpus.services import describe_query_payload


class RegistrationView(FormView):
    template_name = "accounts/register.html"
    form_class = RegistrationForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["email_confirmation_required"] = settings.ACCOUNTS_REQUIRE_EMAIL_CONFIRMATION
        return context

    def send_activation_email(self, user) -> None:
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = email_activation_token.make_token(user)
        activation_url = self.request.build_absolute_uri(
            reverse("accounts:activate", kwargs={"uidb64": uid, "token": token})
        )
        context = {
            "user": user,
            "activation_url": activation_url,
            "site_title": settings.CORPUS_SHORT_TITLE,
        }
        subject = render_to_string("accounts/email_activation_subject.txt", context).strip()
        body = render_to_string("accounts/email_activation_body.txt", context)
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)

    def form_valid(self, form):
        user = form.save()
        if settings.ACCOUNTS_REQUIRE_EMAIL_CONFIRMATION:
            user.is_active = False
            user.save(update_fields=["is_active"])
            self.send_activation_email(user)
            messages.success(
                self.request,
                "Регистрация принята. Проверьте почту и подтвердите адрес, чтобы войти в систему.",
            )
            return redirect("accounts:activation-sent")

        login(self.request, user)
        UserActivity.objects.create(
            user=user,
            activity_type=UserActivity.LOGIN,
            title="Создана учетная запись",
            payload={"username": user.username},
        )
        messages.success(self.request, "Регистрация завершена. Личный кабинет готов к работе.")
        return redirect("accounts:dashboard")


class ActivationSentView(TemplateView):
    template_name = "accounts/activation_sent.html"


class ActivateAccountView(TemplateView):
    template_name = "accounts/activation_invalid.html"

    def get(self, request, uidb64, token, *args, **kwargs):
        User = get_user_model()
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None

        if user is None or not email_activation_token.check_token(user, token):
            return super().get(request, *args, **kwargs)

        user.is_active = True
        user.save(update_fields=["is_active"])
        login(request, user)
        update_session_auth_hash(request, user)
        UserActivity.objects.create(
            user=user,
            activity_type=UserActivity.LOGIN,
            title="Подтверждена электронная почта",
            payload={"username": user.username},
        )
        messages.success(request, "Электронная почта подтверждена. Личный кабинет готов к работе.")
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
