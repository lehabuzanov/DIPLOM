from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.cache import cache

from sem_corpus.apps.accounts.models import UserProfile


User = get_user_model()


class RateLimitedAuthenticationForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "rate_limited": (
            "Слишком много неудачных попыток входа. "
            "Подождите несколько минут и попробуйте снова."
        ),
    }

    def _client_key(self) -> str:
        username = (self.data.get("username") or "").strip().lower()
        request = self.request
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "") if request else ""
        ip_address = forwarded_for.split(",", 1)[0].strip() or (request.META.get("REMOTE_ADDR", "") if request else "")
        return f"login-failures:{ip_address}:{username}"

    def clean(self):
        key = self._client_key()
        attempts = cache.get(key, 0)
        if attempts >= settings.LOGIN_RATE_LIMIT_ATTEMPTS:
            raise forms.ValidationError(
                self.error_messages["rate_limited"],
                code="rate_limited",
            )

        try:
            cleaned_data = super().clean()
        except forms.ValidationError:
            try:
                cache.incr(key)
            except ValueError:
                cache.set(key, 1, settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS)
            raise

        cache.delete(key)
        return cleaned_data


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(label="Электронная почта", required=True)
    institution = forms.CharField(label="Организация", required=False)
    first_name = forms.CharField(label="Имя", required=True)
    last_name = forms.CharField(label="Фамилия", required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email", "institution")

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Пользователь с такой электронной почтой уже зарегистрирован.")
        return email

    def save(self, commit=True):
        user = super().save(commit=commit)
        user.email = self.cleaned_data["email"]
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        if commit:
            user.save()
            profile, _created = UserProfile.objects.get_or_create(user=user)
            profile.institution = self.cleaned_data.get("institution", "")
            profile.save(update_fields=["institution", "updated_at"])
        return user
