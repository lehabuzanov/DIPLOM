from __future__ import annotations

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models import Sum
from django.urls import reverse
from urllib.parse import urlencode

from sem_corpus.apps.core.models import TimestampedModel


def payload_to_querystring(payload: dict | None) -> str:
    if not payload:
        return ""
    serialized: dict[str, str | list[str]] = {}
    for key, value in payload.items():
        if value in ("", None, []):
            continue
        if isinstance(value, (list, tuple)):
            serialized[key] = [str(item) for item in value if item not in ("", None)]
        else:
            serialized[key] = str(value)
    return urlencode(serialized, doseq=True)


class PublishedArticleQuerySet(models.QuerySet):
    def published(self):
        return self.filter(is_published=True)


class Journal(TimestampedModel):
    title = models.CharField("полное название", max_length=255)
    short_title = models.CharField("краткое название", max_length=160)
    issn_print = models.CharField("ISSN (print)", max_length=32, blank=True)
    issn_online = models.CharField("ISSN (online)", max_length=32, blank=True)
    publisher = models.CharField("издатель", max_length=255, blank=True)
    description = models.TextField("описание", blank=True)
    site_url = models.URLField("сайт журнала", blank=True)
    integration_hint = models.CharField("вариант интеграции", max_length=255, blank=True)
    is_active = models.BooleanField("активный", default=True)

    class Meta:
        verbose_name = "журнал"
        verbose_name_plural = "журналы"

    def __str__(self) -> str:
        return self.short_title


class Issue(TimestampedModel):
    journal = models.ForeignKey(Journal, on_delete=models.CASCADE, related_name="issues", verbose_name="журнал")
    year = models.PositiveIntegerField("год")
    volume = models.CharField("том", max_length=32)
    number = models.CharField("номер", max_length=32)
    title = models.CharField("заголовок выпуска", max_length=255, blank=True)
    publication_date = models.DateField("дата публикации", null=True, blank=True)
    source_url = models.URLField("URL выпуска", blank=True)
    note = models.TextField("примечание", blank=True)

    class Meta:
        verbose_name = "выпуск"
        verbose_name_plural = "выпуски"
        ordering = ["-year", "-publication_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["journal", "year", "volume", "number"],
                name="unique_issue_per_journal",
            )
        ]

    def __str__(self) -> str:
        return f"{self.journal.short_title}, {self.year}, т. {self.volume}, № {self.number}"


class Section(TimestampedModel):
    journal = models.ForeignKey(
        Journal,
        on_delete=models.CASCADE,
        related_name="sections",
        verbose_name="журнал",
    )
    name = models.CharField("название", max_length=255)
    slug = models.SlugField("код", max_length=140)
    description = models.TextField("описание", blank=True)
    sort_order = models.PositiveIntegerField("порядок", default=0)

    class Meta:
        verbose_name = "раздел"
        verbose_name_plural = "разделы"
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["journal", "slug"], name="unique_section_slug_per_journal")
        ]

    def __str__(self) -> str:
        return self.name


class Affiliation(TimestampedModel):
    name = models.CharField("название", max_length=255, unique=True)
    city = models.CharField("город", max_length=128, blank=True)
    country = models.CharField("страна", max_length=128, blank=True)
    website = models.URLField("сайт", blank=True)

    class Meta:
        verbose_name = "аффилиация"
        verbose_name_plural = "аффилиации"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Author(TimestampedModel):
    first_name = models.CharField("имя", max_length=120)
    last_name = models.CharField("фамилия", max_length=120)
    middle_name = models.CharField("отчество", max_length=120, blank=True)
    slug = models.SlugField("код", max_length=180, unique=True)
    orcid = models.CharField("ORCID", max_length=32, blank=True)
    email = models.EmailField("электронная почта", blank=True)
    affiliations = models.ManyToManyField(Affiliation, related_name="authors", blank=True, verbose_name="аффилиации")

    class Meta:
        verbose_name = "автор"
        verbose_name_plural = "авторы"
        ordering = ["last_name", "first_name", "middle_name"]

    def __str__(self) -> str:
        return self.full_name

    @property
    def full_name(self) -> str:
        parts = [self.last_name, self.first_name, self.middle_name]
        return " ".join(part for part in parts if part)


class Keyword(TimestampedModel):
    name = models.CharField("ключевое слово", max_length=120)
    normalized = models.CharField("нормализованное значение", max_length=120)
    language = models.CharField("язык", max_length=16, default="ru")

    class Meta:
        verbose_name = "ключевое слово"
        verbose_name_plural = "ключевые слова"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["normalized", "language"], name="unique_keyword_per_language")
        ]

    def __str__(self) -> str:
        return self.name


class Article(TimestampedModel):
    LANGUAGE_RU = "ru"
    LANGUAGE_EN = "en"
    LANGUAGE_BI = "ru-en"
    LANGUAGE_CHOICES = [
        (LANGUAGE_RU, "Русский"),
        (LANGUAGE_EN, "Английский"),
        (LANGUAGE_BI, "Русский / Английский"),
    ]

    journal = models.ForeignKey(Journal, on_delete=models.CASCADE, related_name="articles", verbose_name="журнал")
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="articles", verbose_name="выпуск")
    section = models.ForeignKey(
        Section,
        on_delete=models.SET_NULL,
        related_name="articles",
        verbose_name="раздел",
        null=True,
        blank=True,
    )
    title = models.CharField("название статьи", max_length=500)
    slug = models.SlugField("код статьи", max_length=255, unique=True)
    subtitle = models.CharField("подзаголовок", max_length=255, blank=True)
    language = models.CharField("язык публикации", max_length=16, choices=LANGUAGE_CHOICES, default=LANGUAGE_RU)
    pages = models.CharField("страницы", max_length=64, blank=True)
    doi = models.CharField("DOI", max_length=120, blank=True)
    original_url = models.URLField("URL оригинала", blank=True)
    abstract = models.TextField("аннотация", blank=True)
    import_source = models.CharField("источник импорта", max_length=255, blank=True)
    source_identifier = models.CharField("внешний идентификатор", max_length=255, blank=True)
    is_published = models.BooleanField("опубликовано", default=True)
    keywords = models.ManyToManyField(Keyword, related_name="articles", blank=True, verbose_name="ключевые слова")
    authors = models.ManyToManyField(Author, through="ArticleAuthor", related_name="articles", verbose_name="авторы")

    objects = PublishedArticleQuerySet.as_manager()

    class Meta:
        verbose_name = "статья"
        verbose_name_plural = "статьи"
        ordering = ["-issue__year", "title"]
        indexes = [
            models.Index(fields=["language"]),
            models.Index(fields=["doi"]),
            models.Index(fields=["slug"]),
        ]

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self):
        return reverse("corpus:article-detail", kwargs={"slug": self.slug})

    @property
    def author_line(self) -> str:
        ordered = self.article_authors.select_related("author").order_by("order")
        return ", ".join(item.author.full_name for item in ordered)


class ArticleAuthor(TimestampedModel):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="article_authors", verbose_name="статья")
    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="article_links", verbose_name="автор")
    affiliation = models.ForeignKey(
        Affiliation,
        on_delete=models.SET_NULL,
        related_name="article_authors",
        verbose_name="аффилиация",
        null=True,
        blank=True,
    )
    order = models.PositiveIntegerField("порядок автора", default=1)
    display_name = models.CharField("отображаемое имя", max_length=255, blank=True)

    class Meta:
        verbose_name = "автор статьи"
        verbose_name_plural = "авторы статьи"
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["article", "author", "order"], name="unique_author_order_per_article")
        ]

    def __str__(self) -> str:
        return self.display_name or self.author.full_name


class ArticleFile(TimestampedModel):
    KIND_PDF = "pdf"
    KIND_DOCX = "docx"
    KIND_TXT = "txt"
    KIND_OTHER = "other"
    FILE_KIND_CHOICES = [
        (KIND_PDF, "PDF"),
        (KIND_DOCX, "DOCX"),
        (KIND_TXT, "TXT"),
        (KIND_OTHER, "Другое"),
    ]

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="files", verbose_name="статья")
    file = models.FileField("файл", upload_to="articles/files/", blank=True)
    file_kind = models.CharField("тип файла", max_length=16, choices=FILE_KIND_CHOICES, default=KIND_PDF)
    original_filename = models.CharField("исходное имя файла", max_length=255, blank=True)
    mime_type = models.CharField("MIME-тип", max_length=120, blank=True)
    external_url = models.URLField("внешний URL", blank=True)
    checksum = models.CharField("контрольная сумма", max_length=128, blank=True)

    class Meta:
        verbose_name = "файл статьи"
        verbose_name_plural = "файлы статей"
        ordering = ["article", "file_kind"]

    def __str__(self) -> str:
        return self.original_filename or self.file.name or f"Файл {self.article}"


class ArticleText(TimestampedModel):
    article = models.OneToOneField(Article, on_delete=models.CASCADE, related_name="text", verbose_name="статья")
    title_text = models.TextField("заголовок", blank=True)
    abstract_text = models.TextField("аннотация", blank=True)
    keywords_text = models.TextField("ключевые слова", blank=True)
    body_text = models.TextField("основной текст", blank=True)
    references_text = models.TextField("список литературы", blank=True)
    cleaned_text = models.TextField("очищенный текст", blank=True)
    token_count = models.PositiveIntegerField("число токенов", default=0)
    lemma_count = models.PositiveIntegerField("число лемм", default=0)
    search_vector = SearchVectorField("поисковый вектор", null=True)

    class Meta:
        verbose_name = "текст статьи"
        verbose_name_plural = "тексты статей"
        indexes = [GinIndex(fields=["search_vector"])]

    def __str__(self) -> str:
        return f"Текст статьи: {self.article.title}"


class Lemma(TimestampedModel):
    text = models.CharField("лемма", max_length=120)
    normalized = models.CharField("нормализованное значение", max_length=120)
    language = models.CharField("язык", max_length=16, default="ru")
    part_of_speech = models.CharField("часть речи", max_length=32, blank=True)

    class Meta:
        verbose_name = "лемма"
        verbose_name_plural = "леммы"
        ordering = ["normalized"]
        constraints = [
            models.UniqueConstraint(
                fields=["normalized", "language", "part_of_speech"],
                name="unique_lemma_per_language_pos",
            )
        ]

    def __str__(self) -> str:
        return self.normalized


class ArticleToken(TimestampedModel):
    SECTION_TITLE = "title"
    SECTION_ABSTRACT = "abstract"
    SECTION_KEYWORDS = "keywords"
    SECTION_BODY = "body"
    SECTION_REFERENCES = "references"
    SECTION_CHOICES = [
        (SECTION_TITLE, "Заголовок"),
        (SECTION_ABSTRACT, "Аннотация"),
        (SECTION_KEYWORDS, "Ключевые слова"),
        (SECTION_BODY, "Основной текст"),
        (SECTION_REFERENCES, "Литература"),
    ]

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="tokens", verbose_name="статья")
    article_text = models.ForeignKey(
        ArticleText,
        on_delete=models.CASCADE,
        related_name="tokens",
        verbose_name="текст статьи",
    )
    lemma = models.ForeignKey(
        Lemma,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tokens",
        verbose_name="лемма",
    )
    token = models.CharField("токен", max_length=120)
    normalized = models.CharField("нормализованная форма", max_length=120, blank=True)
    morph_tag = models.CharField("морфологическая информация", max_length=128, blank=True)
    position = models.PositiveIntegerField("позиция")
    sentence_index = models.PositiveIntegerField("номер предложения", default=0)
    char_start = models.PositiveIntegerField("символ начала", default=0)
    char_end = models.PositiveIntegerField("символ конца", default=0)
    source_section = models.CharField("часть текста", max_length=32, choices=SECTION_CHOICES, default=SECTION_BODY)
    is_alpha = models.BooleanField("буквенный токен", default=False)

    class Meta:
        verbose_name = "токен статьи"
        verbose_name_plural = "токены статьи"
        ordering = ["article_id", "position"]
        indexes = [
            models.Index(fields=["article", "position"]),
            models.Index(fields=["normalized"]),
            models.Index(fields=["source_section"]),
        ]

    def __str__(self) -> str:
        return f"{self.token} ({self.article_id}:{self.position})"


class SavedQuery(TimestampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_queries",
        verbose_name="пользователь",
    )
    name = models.CharField("название", max_length=255)
    description = models.TextField("описание", blank=True)
    query_payload = models.JSONField("параметры запроса", default=dict)
    last_result_count = models.PositiveIntegerField("последнее число результатов", default=0)

    class Meta:
        verbose_name = "сохраненный запрос"
        verbose_name_plural = "сохраненные запросы"
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.name

    def get_search_url(self) -> str:
        base_url = reverse("corpus:search")
        querystring = payload_to_querystring(self.query_payload)
        suffix = f"{querystring}&saved_query={self.pk}" if querystring else f"saved_query={self.pk}"
        return f"{base_url}?{suffix}"


class SavedSubcorpus(TimestampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_subcorpora",
        verbose_name="пользователь",
    )
    name = models.CharField("название", max_length=255)
    description = models.TextField("описание", blank=True)
    filter_payload = models.JSONField("фильтры", default=dict, blank=True)
    is_public = models.BooleanField("публичный", default=False)
    article_count = models.PositiveIntegerField("число статей", default=0)
    token_count = models.PositiveIntegerField("число токенов", default=0)
    articles = models.ManyToManyField(
        Article,
        through="SavedSubcorpusArticle",
        related_name="saved_subcorpora",
        verbose_name="статьи",
    )

    class Meta:
        verbose_name = "сохраненный подкорпус"
        verbose_name_plural = "сохраненные подкорпуса"
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.name

    def refresh_membership(self):
        from sem_corpus.apps.corpus.services import resolve_articles_for_saved_payload

        filtered_articles = resolve_articles_for_saved_payload(self.filter_payload)
        SavedSubcorpusArticle.objects.filter(subcorpus=self, source=SavedSubcorpusArticle.SOURCE_FILTER).delete()
        SavedSubcorpusArticle.objects.bulk_create(
            [
                SavedSubcorpusArticle(
                    subcorpus=self,
                    article=article,
                    source=SavedSubcorpusArticle.SOURCE_FILTER,
                )
                for article in filtered_articles
            ],
            ignore_conflicts=True,
        )
        self.article_count = self.articles.count()
        self.token_count = (
            self.articles.select_related("text").aggregate(total=Sum("text__token_count")).get("total") or 0
        )
        self.save(update_fields=["article_count", "token_count", "updated_at"])

    @property
    def has_filter_payload(self) -> bool:
        return any(value not in ("", None, []) for value in (self.filter_payload or {}).values())

    def get_source_search_url(self) -> str:
        base_url = reverse("corpus:search")
        querystring = payload_to_querystring(self.filter_payload)
        suffix = f"{querystring}&subcorpus={self.pk}" if querystring else f"subcorpus={self.pk}"
        return f"{base_url}?{suffix}"


class SavedSubcorpusArticle(TimestampedModel):
    SOURCE_FILTER = "filter"
    SOURCE_MANUAL = "manual"
    SOURCE_CHOICES = [
        (SOURCE_FILTER, "По фильтру"),
        (SOURCE_MANUAL, "Добавлено вручную"),
    ]

    subcorpus = models.ForeignKey(
        SavedSubcorpus,
        on_delete=models.CASCADE,
        related_name="subcorpus_articles",
        verbose_name="подкорпус",
    )
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="subcorpus_links", verbose_name="статья")
    source = models.CharField("источник", max_length=16, choices=SOURCE_CHOICES, default=SOURCE_FILTER)

    class Meta:
        verbose_name = "статья в подкорпусе"
        verbose_name_plural = "статьи в подкорпусах"
        constraints = [
            models.UniqueConstraint(fields=["subcorpus", "article"], name="unique_article_in_subcorpus")
        ]

    def __str__(self) -> str:
        return f"{self.subcorpus.name}: {self.article.title}"


class SearchHistory(TimestampedModel):
    SEARCH_FULLTEXT = "fulltext"
    SEARCH_LEMMA = "lemma"
    SEARCH_WORDFORM = "wordform"
    SEARCH_PHRASE = "phrase"
    SEARCH_METADATA = "metadata"
    SEARCH_TYPE_CHOICES = [
        (SEARCH_FULLTEXT, "Полнотекстовый поиск"),
        (SEARCH_LEMMA, "Поиск по лемме"),
        (SEARCH_WORDFORM, "Поиск по словоформе"),
        (SEARCH_PHRASE, "Поиск по фразе"),
        (SEARCH_METADATA, "Поиск по метаданным"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="search_history",
        verbose_name="пользователь",
        null=True,
        blank=True,
    )
    query_text = models.CharField("строка поиска", max_length=255, blank=True)
    search_type = models.CharField("тип поиска", max_length=16, choices=SEARCH_TYPE_CHOICES)
    filters = models.JSONField("фильтры", default=dict, blank=True)
    result_count = models.PositiveIntegerField("число результатов", default=0)

    class Meta:
        verbose_name = "история поиска"
        verbose_name_plural = "история поиска"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_search_type_display()}: {self.query_text or 'без строки'}"
