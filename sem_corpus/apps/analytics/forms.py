from django import forms
from django.db.models import Q

from sem_corpus.apps.corpus.models import Article, SavedSubcorpus
from sem_corpus.apps.corpus.services import ANALYTICS_FILTER_CHOICES, ANALYTICS_FILTER_CURATED


class ArticleChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        issue = getattr(obj, "issue", None)
        if not issue:
            return obj.title
        return f"{issue.year}, т. {issue.volume}, № {issue.number} — {obj.title}"


class AnalyticsForm(forms.Form):
    MODE_CHOICES = [
        ("lemma", "Леммы"),
        ("word", "Словоформы"),
    ]

    subcorpus = forms.ModelChoiceField(
        label="Подкорпус для анализа",
        queryset=SavedSubcorpus.objects.none(),
        required=False,
    )
    article = ArticleChoiceField(
        label="Статья для анализа",
        queryset=Article.objects.none(),
        required=False,
    )
    mode = forms.ChoiceField(
        label="Тип частотного списка",
        choices=MODE_CHOICES,
        required=False,
    )
    filter_mode = forms.ChoiceField(
        label="Фильтр статистики",
        choices=ANALYTICS_FILTER_CHOICES,
        required=False,
    )
    left_article = ArticleChoiceField(label="Статья A", queryset=Article.objects.none(), required=False)
    right_article = ArticleChoiceField(label="Статья B", queryset=Article.objects.none(), required=False)
    left_subcorpus = forms.ModelChoiceField(label="Подкорпус A", queryset=SavedSubcorpus.objects.none(), required=False)
    right_subcorpus = forms.ModelChoiceField(label="Подкорпус B", queryset=SavedSubcorpus.objects.none(), required=False)

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        subcorpus_queryset = SavedSubcorpus.objects.filter(is_public=True)
        article_queryset = (
            Article.objects.published()
            .select_related("issue")
            .order_by("-issue__year", "-issue__volume", "title")
        )
        if user and user.is_authenticated:
            subcorpus_queryset = SavedSubcorpus.objects.filter(Q(user=user) | Q(is_public=True)).distinct()

        self.fields["subcorpus"].queryset = subcorpus_queryset
        self.fields["article"].queryset = article_queryset
        self.fields["left_article"].queryset = article_queryset
        self.fields["right_article"].queryset = article_queryset
        self.fields["left_subcorpus"].queryset = subcorpus_queryset
        self.fields["right_subcorpus"].queryset = subcorpus_queryset
        self.fields["mode"].initial = "lemma"
        self.fields["filter_mode"].initial = ANALYTICS_FILTER_CURATED
