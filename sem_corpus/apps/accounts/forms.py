from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm


User = get_user_model()


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(label="Электронная почта", required=True)
    institution = forms.CharField(label="Организация", required=False)
    first_name = forms.CharField(label="Имя", required=True)
    last_name = forms.CharField(label="Фамилия", required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email", "institution")

    def save(self, commit=True):
        user = super().save(commit=commit)
        user.email = self.cleaned_data["email"]
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        if commit:
            user.save()
            user.profile.institution = self.cleaned_data.get("institution", "")
            user.profile.save()
        return user
