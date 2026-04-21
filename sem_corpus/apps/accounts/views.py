from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views.generic import FormView, TemplateView

from sem_corpus.apps.accounts.forms import RegistrationForm
from sem_corpus.apps.accounts.models import UserActivity
from sem_corpus.apps.corpus.models import SavedQuery, SavedSubcorpus


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
        context["recent_activity"] = UserActivity.objects.filter(user=user)[:12]
        return context
