from __future__ import annotations

import csv
import io
import json
from collections import Counter, defaultdict
from functools import lru_cache

from django.contrib.postgres.search import SearchHeadline, SearchQuery, SearchRank, SearchVector
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from razdel import sentenize, tokenize
from pymorphy3 import MorphAnalyzer

from sem_corpus.apps.accounts.models import UserActivity
from sem_corpus.apps.corpus.models import (
    Article,
    ArticleText,
    ArticleToken,
    Keyword,
    Lemma,
    SavedSubcorpus,
    SavedSubcorpusArticle,
    SavedQuery,
    SearchHistory,
)


@lru_cache(maxsize=1)
def get_morph_analyzer() -> MorphAnalyzer:
    return MorphAnalyzer()


@lru_cache(maxsize=50000)
def analyze_alpha_token(token_value: str) -> tuple[str, str, str]:
    parse = get_morph_analyzer().parse(token_value)[0]
    return parse.normal_form, str(parse.tag.POS or ""), str(parse.tag)


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
    normal_form, _pos, _tag = analyze_alpha_token(token_value)
    return token_value, normal_form


def flatten_article_text(article_text: ArticleText) -> str:
    parts = [
        article_text.title_text,
        article_text.abstract_text,
        article_text.keywords_text,
        article_text.body_text,
        article_text.references_text,
    ]
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


@transaction.atomic
def rebuild_article_index(article: Article) -> None:
    if not hasattr(article, "text"):
        return

    article_text = article.text
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
        ("references_text", ArticleToken.SECTION_REFERENCES),
    ]

    section_offsets = {}
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
        while sentence_pointer < len(sentences) and token_obj.start >= sentences[sentence_pointer].stop:
            sentence_pointer += 1
        sentence_index = sentence_pointer
        is_alpha = token_value.isalpha()
        normalized = token_value.lower()
        lemma_id = None
        morph_tag = ""
        if is_alpha:
            normal_form, part_of_speech, morph_tag = analyze_alpha_token(normalized)
            lemma_id = get_or_create_lemma_id(normal_form, article.language, part_of_speech)
            alpha_lemma_values.add(normal_form)

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
        cleaned_text=article_text.cleaned_text,
        token_count=len(tokens_to_create),
        lemma_count=len(alpha_lemma_values),
        search_vector=(
            SearchVector("title_text", weight="A", config="russian")
            + SearchVector("abstract_text", weight="B", config="russian")
            + SearchVector("keywords_text", weight="B", config="russian")
            + SearchVector("body_text", weight="C", config="russian")
            + SearchVector("references_text", weight="D", config="russian")
        )
    )


def serialize_querydict(data) -> str:
    cleaned = {key: value for key, value in data.items() if value not in ("", None, [])}
    return json.dumps(cleaned, ensure_ascii=False)


def deserialize_payload(payload: str | dict | None) -> dict:
    if not payload:
        return {}
    if isinstance(payload, dict):
        return payload
    return json.loads(payload)


def serialize_filter_values(payload: dict) -> dict:
    serializable = {}
    for key, value in payload.items():
        if value in (None, "", []):
            continue
        if hasattr(value, "pk"):
            serializable[key] = value.pk
        else:
            serializable[key] = value
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


def search_articles(form, user=None):
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
        search_query = SearchQuery(
            query_text,
            search_type="phrase" if search_mode == SearchHistory.SEARCH_PHRASE else "websearch",
            config="russian",
        )
        text_queryset = (
            ArticleText.objects.filter(article__in=queryset)
            .annotate(
                rank=SearchRank(F("search_vector"), search_query),
                snippet=SearchHeadline(
                    "cleaned_text",
                    search_query,
                    config="russian",
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
        token_queryset = (
            ArticleToken.objects.filter(article__in=queryset, is_alpha=True)
            .filter(token_filter)
            .select_related("article", "lemma", "article__issue", "article__section", "article__journal")
            .order_by("article_id", "position")
        )
        grouped = defaultdict(list)
        for token_obj in token_queryset[:300]:
            grouped[token_obj.article_id].append(token_obj)
        for article_id, hits in grouped.items():
            article = hits[0].article
            contexts = [build_token_context(article, hit.position) for hit in hits[:5]]
            results.append(
                {
                    "article": article,
                    "contexts": contexts,
                    "hit_count": token_queryset.filter(article_id=article_id).count(),
                }
            )

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
        query_payload=deserialize_payload(payload),
        last_result_count=result_count,
    )
    record_user_activity(
        user,
        UserActivity.SEARCH,
        "Сохранен поисковый запрос",
        {"query_id": query.id, "name": name},
    )
    return query


def build_subcorpus(user, name: str, description: str, payload: str, is_public: bool = False) -> SavedSubcorpus:
    payload_data = deserialize_payload(payload)
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
            articles = [row["article"] for row in search_articles(search_form, user=None)]
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
            subcorpus.article_count = subcorpus.articles.count()
            subcorpus.token_count = (
                subcorpus.articles.aggregate(total=Sum("text__token_count")).get("total") or 0
            )
            subcorpus.save(update_fields=["article_count", "token_count", "updated_at"])
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


def add_article_to_subcorpus(subcorpus: SavedSubcorpus, article: Article) -> None:
    SavedSubcorpusArticle.objects.get_or_create(
        subcorpus=subcorpus,
        article=article,
        defaults={"source": SavedSubcorpusArticle.SOURCE_MANUAL},
    )
    subcorpus.article_count = subcorpus.articles.count()
    subcorpus.token_count = subcorpus.articles.aggregate(total=Sum("text__token_count")).get("total") or 0
    subcorpus.save(update_fields=["article_count", "token_count", "updated_at"])


def get_frequency_data(articles_queryset, mode: str = "lemma", limit: int = 25):
    frequency_map = get_frequency_counts(articles_queryset, mode=mode)
    rows = [{"label": label, "count": count} for label, count in frequency_map.items()]
    rows.sort(key=lambda item: (-item["count"], item["label"]))
    return rows[:limit]


def get_frequency_counts(articles_queryset, mode: str = "lemma"):
    if mode == "word":
        rows = (
            ArticleToken.objects.filter(article__in=articles_queryset, is_alpha=True)
            .values("normalized")
            .annotate(total=Count("id"))
        )
        return {row["normalized"]: row["total"] for row in rows if row["normalized"]}

    rows = (
        ArticleToken.objects.filter(article__in=articles_queryset, lemma__isnull=False)
        .values("lemma__normalized")
        .annotate(total=Count("id"))
    )
    return {row["lemma__normalized"]: row["total"] for row in rows if row["lemma__normalized"]}


def get_bigram_data(articles_queryset, limit: int = 20):
    counter = Counter()
    previous_token = {}
    token_rows = (
        ArticleToken.objects.filter(article__in=articles_queryset, is_alpha=True)
        .select_related("lemma")
        .order_by("article_id", "position")
        .iterator(chunk_size=2000)
    )
    for token in token_rows:
        label = token.lemma.normalized if token.lemma_id else token.normalized
        if not label:
            continue
        prior = previous_token.get(token.article_id)
        if prior:
            counter[f"{prior} {label}"] += 1
        previous_token[token.article_id] = label
    return [{"label": label, "count": count} for label, count in counter.most_common(limit)]


def compare_frequency_sets(left_articles, right_articles, mode: str = "lemma", limit: int = 15):
    left_freq = get_frequency_counts(left_articles, mode=mode)
    right_freq = get_frequency_counts(right_articles, mode=mode)
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


def compare_subcorpora(left_subcorpus: SavedSubcorpus, right_subcorpus: SavedSubcorpus, mode: str = "lemma", limit: int = 15):
    return compare_frequency_sets(left_subcorpus.articles.all(), right_subcorpus.articles.all(), mode=mode, limit=limit)


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
