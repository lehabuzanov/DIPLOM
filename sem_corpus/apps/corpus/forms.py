from django import forms

from sem_corpus.apps.corpus.models import Article, Author, SavedSubcorpus, Section


class SearchForm(forms.Form):
    SEARCH_FULLTEXT = "fulltext"
    SEARCH_LEMMA = "lemma"
    SEARCH_WORDFORM = "wordform"
    SEARCH_PHRASE = "phrase"
    SEARCH_MODES = [
        (SEARCH_FULLTEXT, "Полнотекстовый поиск"),
        (SEARCH_LEMMA, "Поиск по лемме"),
        (SEARCH_WORDFORM, "Поиск по словоформе"),
        (SEARCH_PHRASE, "Поиск по фразе"),
    ]

    text_query = forms.CharField(label="Поисковый запрос", required=False)
    search_mode = forms.ChoiceField(label="Режим поиска", choices=SEARCH_MODES, required=False)
    title = forms.CharField(label="Название статьи", required=False)
    year_from = forms.IntegerField(label="Год от", required=False)
    year_to = forms.IntegerField(label="Год до", required=False)
    volume = forms.CharField(label="Том", required=False)
    issue_number = forms.CharField(label="Номер", required=False)
    section = forms.ModelChoiceField(label="Раздел", queryset=Section.objects.none(), required=False)
    author = forms.ModelChoiceField(label="Автор", queryset=Author.objects.none(), required=False)
    language = forms.ChoiceField(
        label="Язык",
        choices=[("", "Все языки"), *Article.LANGUAGE_CHOICES],
        required=False,
    )
    keyword = forms.CharField(label="Ключевое слово", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["section"].queryset = Section.objects.all()
        self.fields["author"].queryset = Author.objects.all()
        self.fields["search_mode"].initial = self.SEARCH_FULLTEXT


class SavedSubcorpusForm(forms.ModelForm):
    serialized_filters = forms.CharField(widget=forms.HiddenInput(), required=False)

    class Meta:
        model = SavedSubcorpus
        fields = ["name", "description", "is_public", "serialized_filters"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class SaveQueryForm(forms.Form):
    name = forms.CharField(label="Название запроса", max_length=255)
    description = forms.CharField(
        label="Описание",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    serialized_query = forms.CharField(widget=forms.HiddenInput())


class AddToSubcorpusForm(forms.Form):
    subcorpus = forms.ModelChoiceField(label="Подкорпус", queryset=SavedSubcorpus.objects.none())

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user")
        super().__init__(*args, **kwargs)
        self.fields["subcorpus"].queryset = SavedSubcorpus.objects.filter(user=user)


class EditorArticleUploadForm(forms.Form):
    issue_year = forms.IntegerField(label="Год выпуска")
    issue_volume = forms.CharField(label="Том", max_length=32)
    issue_number = forms.CharField(label="Номер", max_length=32)
    issue_title = forms.CharField(label="Заголовок выпуска", max_length=255, required=False)
    publication_date = forms.DateField(
        label="Дата публикации",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    section_name = forms.CharField(label="Раздел журнала", max_length=255)
    title = forms.CharField(label="Название статьи", max_length=500)
    language = forms.ChoiceField(label="Язык публикации", choices=Article.LANGUAGE_CHOICES)
    authors_text = forms.CharField(
        label="Авторы и аффилиации",
        widget=forms.Textarea(
            attrs={
                "rows": 5,
                "placeholder": (
                    "Каждая строка в формате: Фамилия Имя Отчество | Организация\n"
                    "Пример: Иванов Иван Иванович | ИжГТУ имени М. Т. Калашникова"
                ),
            }
        ),
        help_text="Одна строка = один автор. Организацию можно не указывать.",
    )
    keywords_text = forms.CharField(
        label="Ключевые слова",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Через запятую"}),
    )
    abstract_text = forms.CharField(
        label="Аннотация",
        required=False,
        widget=forms.Textarea(attrs={"rows": 6}),
    )
    body_text = forms.CharField(
        label="Очищенный текст статьи",
        required=False,
        widget=forms.Textarea(attrs={"rows": 14}),
    )
    references_text = forms.CharField(
        label="Список литературы",
        required=False,
        widget=forms.Textarea(attrs={"rows": 6}),
    )
    pages = forms.CharField(label="Страницы", required=False, max_length=64)
    doi = forms.CharField(label="DOI", required=False, max_length=120)
    original_url = forms.URLField(label="URL оригинала", required=False)
    source_file = forms.FileField(label="Файл статьи", required=False)
    is_published = forms.BooleanField(label="Опубликовано", required=False, initial=True)

    def clean_authors_text(self):
        value = (self.cleaned_data.get("authors_text") or "").strip()
        if not value:
            raise forms.ValidationError("Укажите хотя бы одного автора.")
        return value
