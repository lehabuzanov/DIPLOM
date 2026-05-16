from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter, defaultdict
from functools import lru_cache

from django.contrib.postgres.search import SearchHeadline, SearchQuery, SearchRank, SearchVector
from django.db import transaction
from django.db.models import F, Q, Sum
from pymorphy3 import MorphAnalyzer
from razdel import sentenize, tokenize

try:
    from simplemma import lemmatize as simplemma_lemmatize
except ImportError:  # pragma: no cover - optional dependency fallback
    simplemma_lemmatize = None

from sem_corpus.apps.accounts.models import UserActivity
from sem_corpus.apps.corpus.models import (
    Article,
    ArticleText,
    ArticleToken,
    Author,
    Keyword,
    Lemma,
    SavedSubcorpus,
    SavedSubcorpusArticle,
    SavedQuery,
    SearchHistory,
    Section,
)

INTERNAL_QUERY_KEYS = {"saved_query", "subcorpus", "page"}
ANALYTICS_FILTER_CURATED = "curated"
ANALYTICS_FILTER_ALL = "all"

ANALYTICS_FILTER_CHOICES = [
    (ANALYTICS_FILTER_CURATED, "Очищенный"),
    (ANALYTICS_FILTER_ALL, "Полный"),
]

ANALYTICS_FILTER_HELP = {
    ANALYTICS_FILTER_CURATED: (
        "Скрывает английский шум, DOI/EDN, слишком короткие формы, цифры и "
        "библиографические хвосты."
    ),
    ANALYTICS_FILTER_ALL: "Показывает все найденные токены и сочетания без дополнительной фильтрации.",
}

FREQUENCY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "com",
    "doi",
    "edn",
    "et",
    "for",
    "from",
    "has",
    "have",
    "http",
    "https",
    "in",
    "into",
    "is",
    "issn",
    "it",
    "of",
    "on",
    "or",
    "org",
    "our",
    "russ",
    "rus",
    "that",
    "the",
    "these",
    "this",
    "those",
    "to",
    "was",
    "we",
    "were",
    "with",
    "ал",
    "без",
    "бы",
    "быть",
    "весь",
    "для",
    "до",
    "его",
    "ее",
    "если",
    "же",
    "за",
    "из",
    "или",
    "их",
    "источник",
    "как",
    "кто",
    "ли",
    "мочь",
    "на",
    "над",
    "не",
    "нет",
    "но",
    "о",
    "об",
    "он",
    "она",
    "они",
    "от",
    "по",
    "под",
    "при",
    "раздел",
    "с",
    "составить",
    "со",
    "так",
    "такой",
    "тот",
    "то",
    "у",
    "являться",
    "ключевой",
    "дата",
    "обращение",
    "ссылка",
    "автор",
    "что",
    "это",
}

FREQUENCY_BLOCKED_PREFIXES = ("10.", "doi", "edn", "issn", "http", "www", "fig", "table")
LATIN_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z-]*$")
CYRILLIC_TOKEN_RE = re.compile(r"^[\u0400-\u052F-]+$")
HEADER_NOISE_RE = re.compile(
    r"^(?:issn\b|©|удк\b|doi\b|грнти\b|образец цитирования\b|for citation\b|keywords?\b|получен[ао]?\b)",
    flags=re.IGNORECASE,
)
ALL_CAPS_LINE_RE = re.compile(r"^[A-ZА-ЯЁ0-9][A-ZА-ЯЁ0-9 .,:;()\"'«»/-]{4,}$")
PAGE_NUMBER_RE = re.compile(r"^\d{1,3}$")
AFFILIATION_HINT_RE = re.compile(
    r"(университет|академия|институт|россия|ижевск|санкт-петербург|доцент|профессор|магистрант|аспирант)",
    flags=re.IGNORECASE,
)
HISTORICAL_CYRILLIC_MAP = str.maketrans(
    {
        "\u0463": "\u0435",
        "\u0462": "\u0415",
        "\u0456": "\u0438",
        "\u0406": "\u0418",
        "\u0473": "\u0444",
        "\u0472": "\u0424",
        "\u0475": "\u0438",
        "\u0474": "\u0418",
        "\u046b": "\u0443",
        "\u046a": "\u0423",
        "\u046d": "\u044e",
        "\u046c": "\u042e",
        "\u0467": "\u044f",
        "\u0466": "\u042f",
        "\u0469": "\u044f",
        "\u0468": "\u042f",
        "\u046f": "\u043a\u0441",
        "\u046e": "\u041a\u0441",
        "\u0471": "\u043f\u0441",
        "\u0470": "\u041f\u0441",
        "\u047f": "\u043e",
        "\u047e": "\u041e",
        "\u0481": "\u043e",
        "\u0480": "\u041e",
    }
)
HISTORICAL_CYRILLIC_CHARS = frozenset(HISTORICAL_CYRILLIC_MAP)


@lru_cache(maxsize=1)
def get_morph_analyzer() -> MorphAnalyzer:
    return MorphAnalyzer()


def normalize_historical_cyrillic(token_value: str) -> str:
    return (token_value or "").translate(HISTORICAL_CYRILLIC_MAP)


def normalize_whitespace(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def detect_token_language(token_value: str, article_language: str = "ru") -> str:
    if LATIN_TOKEN_RE.fullmatch(token_value or ""):
        return "en"
    if CYRILLIC_TOKEN_RE.fullmatch(token_value or ""):
        if any(char in HISTORICAL_CYRILLIC_CHARS for char in (token_value or "")):
            return "cu"
        return "ru"
    return article_language or "ru"


@lru_cache(maxsize=50000)
def analyze_english_token(token_value: str) -> tuple[str, str, str]:
    normalized = (token_value or "").lower()
    if simplemma_lemmatize is not None:
        lemma = simplemma_lemmatize(normalized, lang="en")
    else:  # pragma: no cover - fallback if optional dependency is unavailable
        lemma = normalized
    return lemma or normalized, "LATIN", "LATIN"


@lru_cache(maxsize=50000)
def analyze_alpha_token(token_value: str, language_hint: str = "ru") -> tuple[str, str, str, str]:
    token_language = detect_token_language(token_value, language_hint)
    if token_language == "en":
        normal_form, part_of_speech, morph_tag = analyze_english_token(token_value)
        return normal_form, part_of_speech, morph_tag, token_language

    normalized_value = normalize_historical_cyrillic(token_value.lower())
    parse = get_morph_analyzer().parse(normalized_value)[0]
    morph_tag = str(parse.tag)
    if token_language == "cu":
        morph_tag = f"HISTORIC|{morph_tag}"
    return parse.normal_form, str(parse.tag.POS or ""), morph_tag, token_language


@lru_cache(maxsize=50000)
def get_or_create_lemma_id(normalized: str, language: str, part_of_speech: str) -> int:
    lemma, _ = Lemma.objects.get_or_create(
        normalized=normalized,
        language=language,
        part_of_speech=part_of_speech,
        defaults={"text": normalized},
    )
    return lemma.pk


def normalize_query_token(value: str) -> tuple[str, str]:
    token_value = (value or "").strip().lower()
    if not token_value:
        return "", ""
    normalized_form = normalize_historical_cyrillic(token_value)
    if LATIN_TOKEN_RE.fullmatch(normalized_form):
        lemma, _pos, _tag = analyze_english_token(normalized_form)
        return normalized_form, lemma
    normal_form, _pos, _tag, _language = analyze_alpha_token(normalized_form)
    return normalized_form, normal_form


def _looks_like_metadata_paragraph(paragraph: str) -> bool:
    normalized = normalize_whitespace(paragraph)
    lowered = normalized.lower()
    if not normalized:
        return True
    if PAGE_NUMBER_RE.fullmatch(normalized):
        return True
    if HEADER_NOISE_RE.match(lowered):
        return True
    if len(normalized) <= 12 and normalized.isdigit():
        return True
    if ALL_CAPS_LINE_RE.fullmatch(normalized) and len(normalized) < 180:
        return True
    if re.match(r"^раздел\s+\d+", lowered):
        return True
    if len(normalized.split()) <= 24 and lowered.count(".") >= 3 and AFFILIATION_HINT_RE.search(lowered):
        return True
    return False


def _is_predominantly_latin(paragraph: str) -> bool:
    letters = [char for char in paragraph if char.isalpha()]
    if len(letters) < 30:
        return False
    latin_letters = sum(1 for char in letters if "a" <= char.lower() <= "z")
    return (latin_letters / len(letters)) >= 0.55


def _build_paragraphs(raw_text: str) -> list[str]:
    paragraphs: list[str] = []
    buffer: list[str] = []
    for raw_line in raw_text.splitlines():
        line = normalize_whitespace(raw_line.replace("\u00ad", "").replace("", " "))
        if not line:
            if buffer:
                paragraphs.append(" ".join(buffer).strip())
                buffer = []
            continue
        buffer.append(line)
    if buffer:
        paragraphs.append(" ".join(buffer).strip())
    return paragraphs


def _drop_duplicate_leading_paragraphs(paragraphs: list[str], title: str, abstract_text: str) -> list[str]:
    if not paragraphs:
        return []

    title_probe = normalize_whitespace(title).lower()
    abstract_probe = normalize_whitespace(abstract_text).lower()
    abstract_length = len(abstract_probe)
    paragraph_count = len(paragraphs)

    cleaned: list[str] = []
    for index, paragraph in enumerate(paragraphs):
        lowered = normalize_whitespace(paragraph).lower()
        if not lowered:
            continue
        if index < 5 and title_probe and lowered == title_probe:
            continue
        if (
            paragraph_count > 1
            and index < 8
            and abstract_probe
            and lowered.startswith(abstract_probe[: min(len(abstract_probe), 140)])
            and len(lowered) <= max(abstract_length + 240, int(abstract_length * 1.35))
        ):
            continue
        cleaned.append(paragraph)
    return cleaned


def _find_title_anchor(lines: list[str], title: str) -> tuple[int, int]:
    normalized_title = normalize_whitespace(title).lower()
    if not normalized_title:
        return -1, -1

    title_words = normalized_title.split()
    if not title_words:
        return -1, -1

    short_probe = " ".join(title_words[: min(len(title_words), 6)])
    for start_index in range(len(lines)):
        for window_size in range(1, 5):
            window = normalize_whitespace(" ".join(lines[start_index : start_index + window_size])).lower()
            if not window:
                continue
            if normalized_title in window or (short_probe and short_probe in window):
                return start_index, start_index + window_size - 1
    return -1, -1


def clean_article_body_text(
    body_text: str,
    *,
    title: str = "",
    abstract_text: str = "",
    keywords_text: str = "",
    language: str = "ru",
) -> str:
    if not body_text:
        return ""

    text = body_text.replace("\r", "\n").replace("\u00ad", "")
    text = re.sub(r"(?<=[A-Za-zА-Яа-яЁё])-\s*\n\s*(?=[A-Za-zА-Яа-яЁё])", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    abstract_words = normalize_whitespace(abstract_text).lower().split()
    abstract_probe = " ".join(abstract_words[:6])
    abstract_fragment = " ".join(abstract_words[:3])
    normalized_lines = [normalize_whitespace(raw_line.replace("", " ")) for raw_line in text.splitlines()]
    anchor_index = -1
    intro_index = -1
    for index, line in enumerate(normalized_lines):
        if line.lower() in {"введение", "introduction"}:
            intro_index = index
            break
    if abstract_fragment:
        for index, line in enumerate(normalized_lines):
            if abstract_fragment in line.lower():
                anchor_index = index
                break
    if anchor_index < 0 and abstract_probe:
        for index in range(len(normalized_lines)):
            window = normalize_whitespace(" ".join(normalized_lines[index : index + 3])).lower()
            if abstract_probe and abstract_probe in window:
                anchor_index = index
                break

    content_started = False
    kept_lines: list[str] = []
    current_paragraph: list[str] = []

    def flush_paragraph() -> None:
        nonlocal current_paragraph
        if current_paragraph:
            kept_lines.append(" ".join(current_paragraph).strip())
            current_paragraph = []

    for index, line in enumerate(normalized_lines):
        lowered = line.lower()

        if not line:
            flush_paragraph()
            continue

        marker_line = lowered.startswith(
            (
                "keywords:",
                "ключевые слова:",
                "for citation",
                "образец цитирования",
                "получена",
                "получено",
                "references",
                "литература",
                "список литературы",
            )
        )
        if marker_line:
            if content_started:
                flush_paragraph()
                break
            continue

        if HEADER_NOISE_RE.match(lowered) or PAGE_NUMBER_RE.fullmatch(line) or re.match(r"^раздел\s+\d+", lowered):
            continue
        if re.match(r"^\d+[.)]?\s", line) and "url:" in lowered and "дата обращения" in lowered:
            continue

        if not content_started:
            if intro_index >= 0 and index < intro_index:
                continue
            if intro_index >= 0 and index == intro_index:
                content_started = True
                current_paragraph = []
                continue
            if anchor_index >= 0 and index < anchor_index:
                continue
            if anchor_index >= 0 and index == anchor_index:
                content_started = True
                current_paragraph.append(line)
                continue
            if ALL_CAPS_LINE_RE.fullmatch(line):
                continue
            if AFFILIATION_HINT_RE.search(lowered) and len(line.split()) <= 12:
                continue
            if line.count(".") >= 2 and len(line.split()) <= 8:
                continue
            if len(line.split()) >= 8 and any(char.islower() for char in line):
                content_started = True
            else:
                continue

        if language != "en" and _is_predominantly_latin(line):
            flush_paragraph()
            break
        current_paragraph.append(line)

    flush_paragraph()

    paragraphs = _drop_duplicate_leading_paragraphs(kept_lines, title, abstract_text)
    while paragraphs and _looks_like_metadata_paragraph(paragraphs[0]):
        paragraphs.pop(0)
    while paragraphs and _looks_like_metadata_paragraph(paragraphs[-1]):
        paragraphs.pop()

    result = "\n\n".join(paragraphs).strip()
    result = re.sub(r"\s+([,.;:!?])", r"\1", result)
    result = re.sub(r"([(\[{])\s+", r"\1", result)
    result = re.sub(r"\s+([)\]}])", r"\1", result)
    return result


def clean_article_body_text(
    body_text: str,
    *,
    title: str = "",
    abstract_text: str = "",
    keywords_text: str = "",
    language: str = "ru",
) -> str:
    if not body_text:
        return ""

    text = body_text.replace("\r", "\n").replace("\u00ad", "")
    text = re.sub(r"(?<=[A-Za-zА-Яа-яЁё])-\s*\n\s*(?=[A-Za-zА-Яа-яЁё])", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    abstract_words = normalize_whitespace(abstract_text).lower().split()
    abstract_probe = " ".join(abstract_words[:6])
    abstract_fragment = " ".join(abstract_words[:3])
    normalized_lines = [normalize_whitespace(raw_line.replace("пЂ ", " ")) for raw_line in text.splitlines()]
    title_index, title_end_index = _find_title_anchor(normalized_lines, title)

    anchor_index = -1
    intro_index = -1
    for index, line in enumerate(normalized_lines):
        if line.lower() in {"введение", "introduction"}:
            intro_index = index
            break

    if abstract_fragment:
        for index, line in enumerate(normalized_lines):
            if abstract_fragment in line.lower():
                anchor_index = index
                break
    if anchor_index < 0 and abstract_probe:
        for index in range(len(normalized_lines)):
            window = normalize_whitespace(" ".join(normalized_lines[index : index + 3])).lower()
            if abstract_probe and abstract_probe in window:
                anchor_index = index
                break
    if anchor_index >= 0:
        anchor_is_too_deep = anchor_index > min(60, max(len(normalized_lines) // 3, 18))
        if anchor_is_too_deep or (title_index >= 0 and anchor_index < title_index):
            anchor_index = -1

    content_started = False
    kept_lines: list[str] = []
    current_paragraph: list[str] = []
    collected_cyrillic = 0

    def flush_paragraph() -> None:
        nonlocal current_paragraph
        if current_paragraph:
            kept_lines.append(" ".join(current_paragraph).strip())
            current_paragraph = []

    for index, line in enumerate(normalized_lines):
        lowered = line.lower()

        if not line:
            flush_paragraph()
            continue

        marker_line = lowered.startswith(
            (
                "keywords:",
                "ключевые слова:",
                "for citation",
                "образец цитирования",
                "получена",
                "получено",
                "references",
                "литература",
                "список литературы",
            )
        )
        if marker_line:
            if content_started:
                flush_paragraph()
                break
            continue

        if HEADER_NOISE_RE.match(lowered) or PAGE_NUMBER_RE.fullmatch(line) or re.match(r"^раздел\s+\d+", lowered):
            continue
        if re.match(r"^\d+[.)]?\s", line) and "url:" in lowered and "дата обращения" in lowered:
            continue

        if not content_started:
            if title_index >= 0 and index <= title_end_index:
                continue
            if intro_index >= 0 and index < intro_index:
                continue
            if intro_index >= 0 and index == intro_index:
                content_started = True
                current_paragraph = []
                continue
            if anchor_index >= 0 and index < anchor_index:
                continue
            if anchor_index >= 0 and index == anchor_index:
                content_started = True
                current_paragraph.append(line)
                continue
            if ALL_CAPS_LINE_RE.fullmatch(line):
                continue
            if AFFILIATION_HINT_RE.search(lowered) and len(line.split()) <= 12:
                continue
            if line.count(".") >= 2 and len(line.split()) <= 8:
                continue
            if title_index >= 0 and any(char.islower() for char in line):
                content_started = True
            elif len(line.split()) >= 8 and any(char.islower() for char in line):
                content_started = True
            else:
                continue

        if language != "en" and _is_predominantly_latin(line) and collected_cyrillic >= 80:
            flush_paragraph()
            break
        collected_cyrillic += sum(1 for char in line if "\u0400" <= char <= "\u052f")
        current_paragraph.append(line)

    flush_paragraph()

    paragraphs = _drop_duplicate_leading_paragraphs(kept_lines, title, abstract_text)
    while paragraphs and _looks_like_metadata_paragraph(paragraphs[0]):
        paragraphs.pop(0)
    while paragraphs and _looks_like_metadata_paragraph(paragraphs[-1]):
        paragraphs.pop()

    result = "\n\n".join(paragraphs).strip()
    result = re.sub(r"\s+([,.;:!?])", r"\1", result)
    result = re.sub(r"([(\[{])\s+", r"\1", result)
    result = re.sub(r"\s+([)\]}])", r"\1", result)
    return result


def flatten_article_text(article_text: ArticleText) -> str:
    body_text = (article_text.body_text or "").strip()
    parts = [article_text.title_text, article_text.abstract_text]
    if article_text.keywords_text:
        parts.append(article_text.keywords_text)
    if body_text:
        parts.append(body_text)
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


@transaction.atomic
def rebuild_article_index(article: Article) -> None:
    if not hasattr(article, "text"):
        return

    article_text = article.text
    article_text.body_text = (article_text.body_text or "").strip()
    article_text.cleaned_text = flatten_article_text(article_text)
    sentences = list(sentenize(article_text.cleaned_text))
    sentence_pointer = 0
    article.tokens.all().delete()

    tokens_to_create = []
    position = 0
    alpha_lemma_values = set()
    section_map = [
        ("title_text", ArticleToken.SECTION_TITLE),
        ("abstract_text", ArticleToken.SECTION_ABSTRACT),
        ("keywords_text", ArticleToken.SECTION_KEYWORDS),
        ("body_text", ArticleToken.SECTION_BODY),
    ]

    section_offsets: dict[str, tuple[int, int]] = {}
    cursor = 0
    for field_name, _label in section_map:
        value = getattr(article_text, field_name) or ""
        if value:
            section_offsets[field_name] = (cursor, cursor + len(value))
            cursor += len(value) + 2

    def resolve_section(char_start: int) -> str:
        for field_name, label in section_map:
            start_stop = section_offsets.get(field_name)
            if not start_stop:
                continue
            start, stop = start_stop
            if start <= char_start <= stop:
                return label
        return ArticleToken.SECTION_BODY

    for token_obj in tokenize(article_text.cleaned_text):
        token_value = token_obj.text.strip()
        if not token_value:
            continue
        if len(token_value) > 120:
            continue
        while sentence_pointer < len(sentences) and token_obj.start >= sentences[sentence_pointer].stop:
            sentence_pointer += 1
        sentence_index = sentence_pointer
        is_alpha = token_value.isalpha()
        normalized = token_value.lower()
        lemma_id = None
        morph_tag = ""
        if is_alpha:
            normal_form, part_of_speech, morph_tag, token_language = analyze_alpha_token(normalized, article.language)
            normalized = normalize_historical_cyrillic(normalized)
            if len(normalized) > 120 or len(normal_form) > 120 or len(morph_tag) > 128:
                continue
            lemma_id = get_or_create_lemma_id(normal_form, token_language, part_of_speech)
            alpha_lemma_values.add(normal_form)
        elif len(normalized) > 120:
            continue

        tokens_to_create.append(
            ArticleToken(
                article=article,
                article_text=article_text,
                lemma_id=lemma_id,
                token=token_value,
                normalized=normalized,
                morph_tag=morph_tag,
                position=position,
                sentence_index=sentence_index,
                char_start=token_obj.start,
                char_end=token_obj.stop,
                source_section=resolve_section(token_obj.start),
                is_alpha=is_alpha,
            )
        )
        position += 1

    ArticleToken.objects.bulk_create(tokens_to_create, batch_size=500)
    ArticleText.objects.filter(pk=article_text.pk).update(
        body_text=article_text.body_text,
        cleaned_text=article_text.cleaned_text,
        token_count=len(tokens_to_create),
        lemma_count=len(alpha_lemma_values),
        search_vector=(
            SearchVector("title_text", weight="A", config="russian")
            + SearchVector("title_text", weight="A", config="english")
            + SearchVector("abstract_text", weight="B", config="russian")
            + SearchVector("abstract_text", weight="B", config="english")
            + SearchVector("keywords_text", weight="B", config="russian")
            + SearchVector("keywords_text", weight="B", config="english")
            + SearchVector("body_text", weight="C", config="russian")
            + SearchVector("body_text", weight="C", config="english")
        ),
    )


def serialize_querydict(data) -> str:
    raw_items = data.lists() if hasattr(data, "lists") else data.items()
    cleaned: dict[str, object] = {}
    for key, value in raw_items:
        if isinstance(value, (list, tuple)):
            values = [item for item in value if item not in ("", None, [])]
            if not values:
                continue
            cleaned[key] = values if len(values) > 1 else values[0]
        elif value not in ("", None, []):
            cleaned[key] = value
    return json.dumps(sanitize_saved_payload(cleaned), ensure_ascii=False)


def deserialize_payload(payload: str | dict | None) -> dict:
    if not payload:
        return {}
    if isinstance(payload, dict):
        return payload
    return json.loads(payload)


def sanitize_saved_payload(payload: str | dict | None) -> dict:
    payload_data = deserialize_payload(payload)
    return {
        key: value
        for key, value in payload_data.items()
        if key not in INTERNAL_QUERY_KEYS and value not in (None, "", [])
    }


def serialize_filter_values(payload: dict) -> dict:
    serializable = {}
    for key, value in payload.items():
        if key in INTERNAL_QUERY_KEYS or value in (None, "", []):
            continue
        serializable[key] = value.pk if hasattr(value, "pk") else value
    return serializable


def apply_article_filters(queryset, filters):
    payload = deserialize_payload(filters)
    if year_from := payload.get("year_from"):
        queryset = queryset.filter(issue__year__gte=year_from)
    if year_to := payload.get("year_to"):
        queryset = queryset.filter(issue__year__lte=year_to)
    if volume := payload.get("volume"):
        queryset = queryset.filter(issue__volume__iexact=volume)
    if issue_number := payload.get("issue_number"):
        queryset = queryset.filter(issue__number__iexact=issue_number)
    if section := payload.get("section"):
        queryset = queryset.filter(section_id=getattr(section, "id", section))
    if author := payload.get("author"):
        queryset = queryset.filter(authors__id=getattr(author, "id", author))
    if language := payload.get("language"):
        queryset = queryset.filter(language=language)
    if keyword := payload.get("keyword"):
        queryset = queryset.filter(keywords__normalized__icontains=str(keyword).lower())
    if title := payload.get("title"):
        queryset = queryset.filter(title__icontains=title)
    return queryset.distinct()


def resolve_articles_for_saved_payload(payload: str | dict | None):
    payload_data = sanitize_saved_payload(payload)
    base_queryset = Article.objects.published().select_related("text", "issue", "section", "journal").prefetch_related(
        "article_authors__author",
        "keywords",
    )
    if payload_data.get("text_query"):
        from sem_corpus.apps.corpus.forms import SearchForm

        search_form = SearchForm(payload_data)
        if not search_form.is_valid():
            return []
        return [row["article"] for row in search_articles(search_form, user=None, record_history=False)]
    return list(apply_article_filters(base_queryset, payload_data).distinct())


def describe_query_payload(payload: str | dict | None) -> list[str]:
    payload_data = sanitize_saved_payload(payload)
    summary: list[str] = []
    if text_query := payload_data.get("text_query"):
        mode = payload_data.get("search_mode") or SearchHistory.SEARCH_FULLTEXT
        summary.append(f"Запрос: {text_query} ({mode})")
    if title := payload_data.get("title"):
        summary.append(f"Название: {title}")
    year_from = payload_data.get("year_from")
    year_to = payload_data.get("year_to")
    if year_from or year_to:
        if year_from and year_to:
            summary.append(f"Годы: {year_from}-{year_to}")
        elif year_from:
            summary.append(f"Год от: {year_from}")
        else:
            summary.append(f"Год до: {year_to}")
    if volume := payload_data.get("volume"):
        summary.append(f"Том: {volume}")
    if issue_number := payload_data.get("issue_number"):
        summary.append(f"Номер: {issue_number}")
    if section_id := payload_data.get("section"):
        section = Section.objects.filter(pk=section_id).values_list("name", flat=True).first()
        if section:
            summary.append(f"Раздел: {section}")
    if author_id := payload_data.get("author"):
        author = Author.objects.filter(pk=author_id).first()
        if author:
            summary.append(f"Автор: {author.full_name}")
    if language := payload_data.get("language"):
        language_label = dict(Article.LANGUAGE_CHOICES).get(language, language)
        summary.append(f"Язык: {language_label}")
    if keyword := payload_data.get("keyword"):
        summary.append(f"Ключевое слово: {keyword}")
    return summary


def build_token_context(article: Article, position: int, radius: int = 7) -> str:
    tokens = list(
        article.tokens.filter(position__gte=max(position - radius, 0), position__lte=position + radius).order_by("position")
    )
    left = " ".join(token.token for token in tokens if token.position < position)
    hit = next((token.token for token in tokens if token.position == position), "")
    right = " ".join(token.token for token in tokens if token.position > position)
    return f"{left} <mark>{hit}</mark> {right}".strip()


def record_user_activity(user, activity_type: str, title: str, payload: dict | None = None) -> None:
    if user and user.is_authenticated:
        UserActivity.objects.create(
            user=user,
            activity_type=activity_type,
            title=title,
            payload=payload or {},
        )


def _resolve_search_config(query_text: str) -> str:
    if re.fullmatch(r"[A-Za-z][A-Za-z\s-]*", query_text or ""):
        return "english"
    return "russian"


def search_articles(form, user=None, *, record_history: bool = True):
    cleaned = form.cleaned_data
    queryset = Article.objects.published().select_related("issue", "section", "journal", "text").prefetch_related(
        "article_authors__author",
        "keywords",
    )
    queryset = apply_article_filters(queryset, cleaned)
    query_text = (cleaned.get("text_query") or "").strip()
    search_mode = cleaned.get("search_mode") or SearchHistory.SEARCH_FULLTEXT
    results = []

    if not query_text:
        result_articles = list(queryset[:50])
        results = [{"article": article, "contexts": [], "hit_count": 0} for article in result_articles]
    elif search_mode in {SearchHistory.SEARCH_FULLTEXT, SearchHistory.SEARCH_PHRASE}:
        search_config = _resolve_search_config(query_text)
        search_query = SearchQuery(
            query_text,
            search_type="phrase" if search_mode == SearchHistory.SEARCH_PHRASE else "websearch",
            config=search_config,
        )
        text_queryset = (
            ArticleText.objects.filter(article__in=queryset)
            .annotate(
                rank=SearchRank(F("search_vector"), search_query),
                snippet=SearchHeadline(
                    "cleaned_text",
                    search_query,
                    config=search_config,
                    start_sel="<mark>",
                    stop_sel="</mark>",
                    max_fragments=3,
                    max_words=28,
                    min_words=10,
                ),
            )
            .filter(search_vector=search_query)
            .select_related("article", "article__issue", "article__section", "article__journal")
            .order_by("-rank")
        )
        for article_text in text_queryset[:100]:
            results.append(
                {
                    "article": article_text.article,
                    "contexts": [article_text.snippet],
                    "hit_count": 1,
                    "rank": round(float(article_text.rank), 3),
                }
            )
    else:
        normalized, lemma_form = normalize_query_token(query_text)
        token_filter = Q(normalized=normalized)
        if search_mode == SearchHistory.SEARCH_LEMMA:
            token_filter = Q(lemma__normalized=lemma_form)
        token_rows = list(
            ArticleToken.objects.filter(article__in=queryset, is_alpha=True)
            .filter(token_filter)
            .select_related("article", "lemma", "article__issue", "article__section", "article__journal")
            .order_by("article_id", "position")[:300]
        )
        grouped = defaultdict(list)
        hit_counts = Counter()
        for token_obj in token_rows:
            grouped[token_obj.article_id].append(token_obj)
            hit_counts[token_obj.article_id] += 1
        for article_id, hits in grouped.items():
            article = hits[0].article
            contexts = [build_token_context(article, hit.position) for hit in hits[:5]]
            results.append(
                {
                    "article": article,
                    "contexts": contexts,
                    "hit_count": hit_counts[article_id],
                }
            )

    if record_history:
        SearchHistory.objects.create(
            user=user if user and user.is_authenticated else None,
            query_text=query_text,
            search_type=search_mode if query_text else SearchHistory.SEARCH_METADATA,
            filters=serialize_filter_values(cleaned),
            result_count=len(results),
        )
        if user and user.is_authenticated:
            record_user_activity(
                user,
                UserActivity.SEARCH,
                "Выполнен поиск по корпусу",
                {"query": query_text, "mode": search_mode, "result_count": len(results)},
            )
    return results


def save_query(user, name: str, description: str, payload: str, result_count: int = 0) -> SavedQuery:
    query = SavedQuery.objects.create(
        user=user,
        name=name,
        description=description,
        query_payload=sanitize_saved_payload(payload),
        last_result_count=result_count,
    )
    record_user_activity(
        user,
        UserActivity.SEARCH,
        "Сохранен поисковый запрос",
        {"query_id": query.id, "name": name},
    )
    return query


def update_saved_query(query: SavedQuery, name: str, description: str, payload: str, result_count: int = 0) -> SavedQuery:
    query.name = name
    query.description = description
    query.query_payload = sanitize_saved_payload(payload)
    query.last_result_count = result_count
    query.save(update_fields=["name", "description", "query_payload", "last_result_count", "updated_at"])
    return query


def refresh_subcorpus_totals(subcorpus: SavedSubcorpus) -> None:
    subcorpus.article_count = subcorpus.articles.count()
    subcorpus.token_count = subcorpus.articles.aggregate(total=Sum("text__token_count")).get("total") or 0
    subcorpus.save(update_fields=["article_count", "token_count", "updated_at"])


def build_subcorpus(user, name: str, description: str, payload: str, is_public: bool = False) -> SavedSubcorpus:
    payload_data = sanitize_saved_payload(payload)
    subcorpus = SavedSubcorpus.objects.create(
        user=user,
        name=name,
        description=description,
        filter_payload=payload_data,
        is_public=is_public,
    )
    if payload_data.get("text_query"):
        from sem_corpus.apps.corpus.forms import SearchForm

        search_form = SearchForm(payload_data)
        if search_form.is_valid():
            articles = [row["article"] for row in search_articles(search_form, user=None, record_history=False)]
            SavedSubcorpusArticle.objects.bulk_create(
                [
                    SavedSubcorpusArticle(
                        subcorpus=subcorpus,
                        article=article,
                        source=SavedSubcorpusArticle.SOURCE_FILTER,
                    )
                    for article in articles
                ],
                ignore_conflicts=True,
            )
            refresh_subcorpus_totals(subcorpus)
        else:
            subcorpus.refresh_membership()
    else:
        subcorpus.refresh_membership()
    record_user_activity(
        user,
        UserActivity.SUBCORPUS,
        "Сформирован подкорпус",
        {"subcorpus_id": subcorpus.id, "name": subcorpus.name},
    )
    return subcorpus


def update_saved_subcorpus(
    subcorpus: SavedSubcorpus,
    *,
    name: str,
    description: str,
    payload: str,
    is_public: bool,
) -> SavedSubcorpus:
    subcorpus.name = name
    subcorpus.description = description
    subcorpus.is_public = is_public
    subcorpus.filter_payload = sanitize_saved_payload(payload)
    subcorpus.save(update_fields=["name", "description", "is_public", "filter_payload", "updated_at"])
    subcorpus.refresh_membership()
    return subcorpus


def add_article_to_subcorpus(subcorpus: SavedSubcorpus, article: Article) -> None:
    SavedSubcorpusArticle.objects.get_or_create(
        subcorpus=subcorpus,
        article=article,
        defaults={"source": SavedSubcorpusArticle.SOURCE_MANUAL},
    )
    refresh_subcorpus_totals(subcorpus)


def is_meaningful_frequency_label(label: str, filter_mode: str = ANALYTICS_FILTER_CURATED) -> bool:
    if not label:
        return False
    normalized = normalize_whitespace(label).lower()
    if not normalized:
        return False
    if filter_mode == ANALYTICS_FILTER_ALL:
        return True
    if len(normalized) < 3:
        return False
    if normalized in FREQUENCY_STOPWORDS:
        return False
    if any(normalized.startswith(prefix) for prefix in FREQUENCY_BLOCKED_PREFIXES):
        return False
    if any(char.isdigit() for char in normalized):
        return False
    if LATIN_TOKEN_RE.fullmatch(normalized):
        return False
    if not normalized.replace("-", "").isalpha():
        return False
    return True


def get_frequency_counts(articles_queryset, mode: str = "lemma", filter_mode: str = ANALYTICS_FILTER_CURATED):
    if mode == "word":
        rows = (
            ArticleToken.objects.filter(article__in=articles_queryset, is_alpha=True)
            .exclude(source_section=ArticleToken.SECTION_REFERENCES)
            .values_list("normalized", flat=True)
        )
    else:
        rows = (
            ArticleToken.objects.filter(article__in=articles_queryset, lemma__isnull=False)
            .exclude(source_section=ArticleToken.SECTION_REFERENCES)
            .values_list("lemma__normalized", flat=True)
        )

    counter = Counter()
    for value in rows.iterator(chunk_size=4000):
        if is_meaningful_frequency_label(value, filter_mode=filter_mode):
            counter[value] += 1
    return dict(counter)


def get_frequency_data(
    articles_queryset,
    mode: str = "lemma",
    limit: int = 25,
    filter_mode: str = ANALYTICS_FILTER_CURATED,
):
    frequency_map = get_frequency_counts(articles_queryset, mode=mode, filter_mode=filter_mode)
    rows = [{"label": label, "count": count} for label, count in frequency_map.items()]
    rows.sort(key=lambda item: (-item["count"], item["label"]))
    return rows[:limit]


def get_bigram_data(
    articles_queryset,
    limit: int = 20,
    filter_mode: str = ANALYTICS_FILTER_CURATED,
):
    counter = Counter()
    previous_token: dict[int, str | None] = {}
    token_rows = (
        ArticleToken.objects.filter(article__in=articles_queryset, is_alpha=True)
        .exclude(source_section=ArticleToken.SECTION_REFERENCES)
        .select_related("lemma")
        .order_by("article_id", "position")
        .iterator(chunk_size=2500)
    )
    for token in token_rows:
        label = token.lemma.normalized if token.lemma_id else token.normalized
        if not is_meaningful_frequency_label(label, filter_mode=filter_mode):
            previous_token[token.article_id] = None
            continue
        prior = previous_token.get(token.article_id)
        if prior:
            counter[f"{prior} {label}"] += 1
        previous_token[token.article_id] = label
    return [{"label": label, "count": count} for label, count in counter.most_common(limit)]


def compare_frequency_sets(
    left_articles,
    right_articles,
    mode: str = "lemma",
    limit: int = 15,
    filter_mode: str = ANALYTICS_FILTER_CURATED,
):
    left_freq = get_frequency_counts(left_articles, mode=mode, filter_mode=filter_mode)
    right_freq = get_frequency_counts(right_articles, mode=mode, filter_mode=filter_mode)
    all_keys = set(left_freq) | set(right_freq)
    rows = []
    for key in all_keys:
        left_count = left_freq.get(key, 0)
        right_count = right_freq.get(key, 0)
        rows.append(
            {
                "label": key,
                "left_count": left_count,
                "right_count": right_count,
                "delta": left_count - right_count,
            }
        )
    rows.sort(key=lambda item: abs(item["delta"]), reverse=True)
    return rows[:limit]


def compare_subcorpora(
    left_subcorpus: SavedSubcorpus,
    right_subcorpus: SavedSubcorpus,
    mode: str = "lemma",
    limit: int = 15,
    filter_mode: str = ANALYTICS_FILTER_CURATED,
):
    return compare_frequency_sets(
        left_subcorpus.articles.all(),
        right_subcorpus.articles.all(),
        mode=mode,
        limit=limit,
        filter_mode=filter_mode,
    )


def export_rows_csv(rows, header_label: str, value_key: str = "count") -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([header_label, "Частота"])
    for row in rows:
        writer.writerow([row["label"], row[value_key]])
    return buffer.getvalue()


def export_comparison_rows_csv(rows) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Единица", "Материал A", "Материал B", "Разница"])
    for row in rows:
        writer.writerow([row["label"], row["left_count"], row["right_count"], row["delta"]])
    return buffer.getvalue()


def export_search_results_csv(results):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Название статьи", "Авторы", "Год", "Раздел", "Количество совпадений", "Контекст"])
    for row in results:
        writer.writerow(
            [
                row["article"].title,
                row["article"].author_line,
                row["article"].issue.year,
                row["article"].section.name if row["article"].section else "",
                row.get("hit_count", 0),
                " | ".join(row.get("contexts", [])),
            ]
        )
    return buffer.getvalue()


def sync_keywords_for_article(article: Article, keyword_string: str):
    values = [item.strip() for item in (keyword_string or "").split(",") if item.strip()]
    keyword_objects = []
    for value in values:
        keyword, _ = Keyword.objects.get_or_create(
            normalized=value.lower(),
            language=article.language,
            defaults={"name": value},
        )
        keyword_objects.append(keyword)
    article.keywords.set(keyword_objects)
