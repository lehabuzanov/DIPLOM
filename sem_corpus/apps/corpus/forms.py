import zipfile
from pathlib import Path

from django import forms
from django.conf import settings

from sem_corpus.apps.corpus.models import Article, Author, SavedQuery, SavedSubcorpus
from sem_corpus.apps.corpus.pdf_extraction import validate_pdf_payload


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
    title = forms.CharField(
        label="Название статьи",
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "js-suggest-input",
                "data-suggest-url": "/corpus/suggest/articles/",
                "data-suggest-placeholder": "Найти статью",
                "autocomplete": "off",
            }
        ),
    )
    year_from = forms.IntegerField(label="Год от", required=False)
    year_to = forms.IntegerField(label="Год до", required=False)
    volume = forms.CharField(
        label="Том",
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "js-suggest-input",
                "data-suggest-url": "/corpus/suggest/volumes/",
                "data-suggest-placeholder": "Выберите или введите том",
                "autocomplete": "off",
            }
        ),
    )
    issue_number = forms.CharField(
        label="Номер",
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "js-suggest-input",
                "data-suggest-url": "/corpus/suggest/issues/",
                "data-suggest-placeholder": "Выберите или введите номер",
                "autocomplete": "off",
            }
        ),
    )
    author = forms.ModelChoiceField(
        label="Автор",
        queryset=Author.objects.none(),
        required=False,
        widget=forms.Select(
            attrs={
                "class": "js-author-select",
                "data-search-placeholder": "Найти автора",
            }
        ),
    )
    language = forms.ChoiceField(
        label="Язык",
        choices=[("", "Все языки"), *Article.LANGUAGE_CHOICES],
        required=False,
    )
    keyword = forms.CharField(label="Ключевое слово", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["author"].queryset = Author.objects.all()
        self.fields["search_mode"].initial = self.SEARCH_FULLTEXT


class SavedSubcorpusForm(forms.ModelForm):
    subcorpus_id = forms.IntegerField(widget=forms.HiddenInput(), required=False)
    serialized_filters = forms.CharField(widget=forms.HiddenInput(), required=False)

    class Meta:
        model = SavedSubcorpus
        fields = ["name", "description", "is_public", "subcorpus_id", "serialized_filters"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class SaveQueryForm(forms.Form):
    query_id = forms.IntegerField(widget=forms.HiddenInput(), required=False)
    name = forms.CharField(label="Название запроса", max_length=255)
    description = forms.CharField(
        label="Описание",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    serialized_query = forms.CharField(widget=forms.HiddenInput())


class SavedQueryEditForm(forms.ModelForm):
    class Meta:
        model = SavedQuery
        fields = ["name", "description"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class AddToSubcorpusForm(forms.Form):
    subcorpus = forms.ModelChoiceField(label="Подкорпус", queryset=SavedSubcorpus.objects.none())

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user")
        super().__init__(*args, **kwargs)
        self.fields["subcorpus"].queryset = SavedSubcorpus.objects.filter(user=user)


class SubcorpusArticleChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        issue = getattr(obj, "issue", None)
        issue_label = f"{issue.year}, т. {issue.volume}, № {issue.number}" if issue else "без выпуска"
        return f"{issue_label} — {obj.title}"


class SubcorpusArticleAddForm(forms.Form):
    article = SubcorpusArticleChoiceField(label="Статья", queryset=Article.objects.none())

    def __init__(self, *args, **kwargs):
        subcorpus = kwargs.pop("subcorpus", None)
        super().__init__(*args, **kwargs)
        queryset = (
            Article.objects.published()
            .select_related("issue")
            .order_by("-issue__year", "-issue__volume", "title")
        )
        if subcorpus and subcorpus.pk:
            queryset = queryset.exclude(subcorpus_links__subcorpus=subcorpus)
        self.fields["article"].queryset = queryset
        self.fields["article"].widget.attrs.update({"class": "form-select"})


class EditorArticleUploadForm(forms.Form):
    ALLOWED_EXTENSIONS = {".pdf", ".txt", ".docx"}
    ALLOWED_CONTENT_TYPES = {
        "application/pdf",
        "text/plain",
        "application/octet-stream",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }

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

    def clean_source_file(self):
        source_file = self.cleaned_data.get("source_file")
        if not source_file:
            return source_file

        suffix = Path(source_file.name or "").suffix.lower()
        if suffix not in self.ALLOWED_EXTENSIONS:
            raise forms.ValidationError("Разрешены только файлы PDF, TXT или DOCX.")

        if source_file.size > settings.EDITOR_UPLOAD_MAX_BYTES:
            max_mb = settings.EDITOR_UPLOAD_MAX_BYTES // (1024 * 1024)
            raise forms.ValidationError(f"Файл слишком большой. Максимальный размер: {max_mb} МБ.")

        content_type = getattr(source_file, "content_type", "") or ""
        if content_type and content_type not in self.ALLOWED_CONTENT_TYPES:
            raise forms.ValidationError("Тип файла не соответствует разрешенным форматам.")

        try:
            source_file.seek(0)
            if suffix == ".pdf":
                validate_pdf_payload(source_file.read())
            elif suffix == ".docx":
                if not zipfile.is_zipfile(source_file):
                    raise forms.ValidationError("DOCX-файл поврежден или имеет неверный формат.")
                source_file.seek(0)
                with zipfile.ZipFile(source_file) as archive:
                    if "word/document.xml" not in archive.namelist():
                        raise forms.ValidationError("DOCX-файл поврежден или имеет неверную структуру.")
        except forms.ValidationError:
            raise
        except Exception as exc:
            if suffix == ".pdf":
                raise forms.ValidationError("PDF-файл не удалось прочитать. Проверьте файл и повторите загрузку.") from exc
            raise forms.ValidationError("Файл не удалось проверить. Проверьте файл и повторите загрузку.") from exc
        finally:
            try:
                source_file.seek(0)
            except (AttributeError, OSError):
                pass

        return source_file

    def clean(self):
        cleaned_data = super().clean()
        source_file = cleaned_data.get("source_file")
        body_text = (cleaned_data.get("body_text") or "").strip()
        if source_file and Path(source_file.name or "").suffix.lower() == ".docx" and not body_text:
            self.add_error(
                "body_text",
                "Для DOCX-файла вставьте текст статьи вручную: автоматическое извлечение DOCX не включено.",
            )
        return cleaned_data

    def clean_authors_text(self):
        value = (self.cleaned_data.get("authors_text") or "").strip()
        if not value:
            raise forms.ValidationError("Укажите хотя бы одного автора.")
        return value
