from django import forms
from django.db.models import Q

from sem_corpus.apps.corpus.models import SavedSubcorpus


class AnalyticsForm(forms.Form):
    MODE_CHOICES = [
        ("lemma", "Леммы"),
        ("word", "Словоформы"),
    ]

    subcorpus = forms.ModelChoiceField(label="Подкорпус", queryset=SavedSubcorpus.objects.none(), required=False)
    mode = forms.ChoiceField(label="Тип частотного списка", choices=MODE_CHOICES, required=False)
    left_subcorpus = forms.ModelChoiceField(
        label="Подкорпус A", queryset=SavedSubcorpus.objects.none(), required=False
    )
    right_subcorpus = forms.ModelChoiceField(
        label="Подкорпус B", queryset=SavedSubcorpus.objects.none(), required=False
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        queryset = SavedSubcorpus.objects.filter(is_public=True)
        if user and user.is_authenticated:
            queryset = SavedSubcorpus.objects.filter(Q(user=user) | Q(is_public=True)).distinct()
        self.fields["subcorpus"].queryset = queryset
        self.fields["left_subcorpus"].queryset = queryset
        self.fields["right_subcorpus"].queryset = queryset
        self.fields["mode"].initial = "lemma"
