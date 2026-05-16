from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from django.core.files.base import ContentFile
from django.utils.text import slugify
from pypdf import PdfReader

from sem_corpus.apps.corpus.models import (
    Affiliation,
    Article,
    ArticleAuthor,
    ArticleFile,
    ArticleText,
    Author,
    Issue,
    Journal,
    Section,
)
from sem_corpus.apps.corpus.services import clean_article_body_text, sync_keywords_for_article


USER_AGENT = (
    "SEMCorpusSync/1.0 (+https://izdat.istu.ru/index.php/social-economic-management; "
    "academic corpus sync)"
)


@dataclass(slots=True)
class SyncCounters:
    issues_seen: int = 0
    articles_seen: int = 0
    articles_created: int = 0
    articles_updated: int = 0
    pdf_downloaded: int = 0
    pdf_failed: int = 0


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "ru,en;q=0.9",
        }
    )
    return session


def normalize_whitespace(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def normalize_multiline_text(value: str | None) -> str:
    if not value:
        return ""
    text = value.replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def safe_slug(value: str, fallback_prefix: str) -> str:
    slug = slugify(value, allow_unicode=True)
    if slug:
        return slug
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    return f"{fallback_prefix}-{digest}"


def extract_numeric_id(pattern: str, value: str) -> str:
    match = re.search(pattern, value)
    if not match:
        raise ValueError(f"Unable to parse identifier from {value!r}")
    return match.group(1)


def extract_article_id(article_url: str) -> str:
    return extract_numeric_id(r"/article/view/(\d+)", article_url)


def parse_person_name(display_name: str) -> tuple[str, str, str]:
    cleaned = normalize_whitespace(display_name.replace(".", " "))
    parts = cleaned.split()
    if not parts:
        return "", "", ""
    if len(parts) == 1:
        return parts[0], "", ""
    if len(parts) == 2:
        return parts[1], parts[0], ""
    return parts[-1], parts[0], " ".join(parts[1:-1])


def parse_iso_date(value: str | None):
    normalized = normalize_whitespace(value)
    if not normalized:
        return None
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue
    return None


def parse_issue_heading(raw_heading: str) -> dict[str, Any]:
    heading = normalize_whitespace(raw_heading)
    match = re.search(
        r"(?:Том|Т\.)\s*(?P<volume>[\w.-]+)\s*(?:№|N)\s*(?P<number>[\w.-]+)\s*\((?P<year>\d{4})\)",
        heading,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError(f"Unable to parse issue heading: {heading}")
    return {
        "volume": match.group("volume"),
        "number": match.group("number"),
        "year": int(match.group("year")),
        "title": heading,
    }


def fetch_soup(session: requests.Session, url: str) -> BeautifulSoup:
    response = session.get(url, timeout=60)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def collect_meta_values(soup: BeautifulSoup) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for tag in soup.find_all("meta"):
        key = tag.get("name") or tag.get("property")
        if not key:
            continue
        content = normalize_whitespace(tag.get("content"))
        if not content:
            continue
        values.setdefault(key, []).append(content)
    return values


def fetch_archive_issue_urls(session: requests.Session, archive_url: str) -> list[str]:
    soup = fetch_soup(session, archive_url)
    issue_urls = []
    seen = set()
    for link in soup.select('a[href*="/issue/view/"]'):
        href = normalize_whitespace(link.get("href"))
        if not href:
            continue
        absolute = urljoin(archive_url, href)
        if absolute in seen:
            continue
        seen.add(absolute)
        issue_urls.append(absolute)
    return issue_urls


def parse_issue_page(session: requests.Session, issue_url: str) -> dict[str, Any]:
    soup = fetch_soup(session, issue_url)
    heading_tag = soup.select_one(".current_issue_title") or soup.select_one(".istu_section_small_margin")
    if not heading_tag:
        raise ValueError(f"Issue heading not found: {issue_url}")
    issue_data = parse_issue_heading(heading_tag.get_text(" ", strip=True))
    issue_data["source_url"] = issue_url

    published_value = ""
    published_label = soup.find(string=re.compile("Опубликован", re.IGNORECASE))
    if published_label:
        published_wrapper = published_label.find_parent(class_="published") or published_label.find_parent("section")
        if published_wrapper:
            value_tag = published_wrapper.find(class_="value")
            if value_tag:
                published_value = value_tag.get_text(" ", strip=True)
    issue_data["publication_date"] = parse_iso_date(published_value)

    articles = []
    sections = soup.select(".sections .section")
    if not sections:
        sections = [soup]

    for section_block in sections:
        section_title = normalize_whitespace(
            (
                section_block.find(["h2", "h3"], recursive=False)
                or section_block.find(["h2", "h3"])
            ).get_text(" ", strip=True)
            if section_block.find(["h2", "h3"])
            else "Статьи"
        )
        for article_summary in section_block.select(".obj_article_summary"):
            title_link = article_summary.select_one("h3.title a")
            if not title_link:
                continue
            article_url = urljoin(issue_url, title_link.get("href"))
            pdf_link = article_summary.select_one('.obj_galley_link[href*="/article/view/"]')
            articles.append(
                {
                    "url": article_url,
                    "pdf_url": urljoin(issue_url, pdf_link.get("href")) if pdf_link and pdf_link.get("href") else "",
                    "section": section_title or "Статьи",
                }
            )
    issue_data["articles"] = articles
    return issue_data


def parse_article_page(session: requests.Session, article_url: str) -> dict[str, Any]:
    soup = fetch_soup(session, article_url)
    meta = collect_meta_values(soup)

    title = meta.get("citation_title", meta.get("DC.Title", [""]))[0]
    abstract = ""
    for key in ("DC.Description", "citation_abstract", "description"):
        if values := meta.get(key):
            abstract = values[-1]
            if abstract:
                break
    if not abstract:
        abstract_tag = soup.select_one(".item.abstract .value")
        abstract = abstract_tag.get_text("\n", strip=True) if abstract_tag else ""

    keywords = meta.get("citation_keywords") or meta.get("DC.Subject") or []
    references = meta.get("citation_reference") or [
        normalize_whitespace(item.get_text(" ", strip=True))
        for item in soup.select(".item.references .value p")
        if normalize_whitespace(item.get_text(" ", strip=True))
    ]
    authors = meta.get("citation_author", []) or meta.get("DC.Creator.PersonalName", [])
    institutions = meta.get("citation_author_institution", [])
    author_rows = []
    for index, name in enumerate(authors):
        affiliation = institutions[index] if index < len(institutions) else ""
        author_rows.append({"name": name, "affiliation": affiliation})

    first_page = (meta.get("citation_firstpage") or [""])[0]
    last_page = (meta.get("citation_lastpage") or [""])[0]
    pages = "-".join(part for part in (first_page, last_page) if part)

    return {
        "article_id": extract_article_id(article_url),
        "title": title,
        "abstract": abstract,
        "keywords": keywords,
        "authors": author_rows,
        "language": (meta.get("citation_language") or meta.get("DC.Language") or ["ru"])[0],
        "date": parse_iso_date((meta.get("citation_date") or meta.get("DC.Date.issued") or [""])[0]),
        "volume": (meta.get("citation_volume") or meta.get("DC.Source.Volume") or [""])[0],
        "number": (meta.get("citation_issue") or meta.get("DC.Source.Issue") or [""])[0],
        "doi": (meta.get("citation_doi") or meta.get("DC.Identifier.DOI") or [""])[0],
        "pages": pages,
        "original_url": article_url,
        "pdf_url": (meta.get("citation_pdf_url") or [""])[0],
        "references": [item for item in references if item],
        "section": (meta.get("DC.Type.articleType") or [""])[0],
    }


def extract_text_from_pdf_bytes(payload: bytes) -> str:
    reader = PdfReader(io.BytesIO(payload))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return normalize_multiline_text("\n\n".join(pages))


def download_pdf_payload(session: requests.Session, pdf_url: str) -> tuple[bytes, str]:
    response = session.get(pdf_url, timeout=120)
    response.raise_for_status()
    payload = response.content
    return payload, extract_text_from_pdf_bytes(payload)


def extract_text_from_saved_file(article_file: ArticleFile | None) -> str:
    if not article_file or not article_file.file:
        return ""
    try:
        with article_file.file.open("rb") as fh:
            return extract_text_from_pdf_bytes(fh.read())
    except Exception:  # noqa: BLE001
        return ""


def resolve_journal() -> Journal:
    journal = Journal.objects.filter(is_active=True).order_by("id").first()
    if journal:
        return journal
    return Journal.objects.create(
        title="Научный журнал «Социально-экономическое управление: теория и практика»",
        short_title="Социально-экономическое управление: теория и практика",
        publisher="ИжГТУ имени М. Т. Калашникова",
        site_url="https://izdat.istu.ru/index.php/social-economic-management",
        description="Электронный корпус научного журнала ИжГТУ.",
        is_active=True,
    )


def get_or_create_issue(journal: Journal, issue_payload: dict[str, Any]) -> Issue:
    issue, _ = Issue.objects.get_or_create(
        journal=journal,
        year=issue_payload["year"],
        volume=str(issue_payload["volume"]),
        number=str(issue_payload["number"]),
        defaults={
            "title": issue_payload.get("title", ""),
            "publication_date": issue_payload.get("publication_date"),
            "source_url": issue_payload.get("source_url", ""),
        },
    )
    issue.title = issue_payload.get("title", issue.title)
    issue.publication_date = issue_payload.get("publication_date") or issue.publication_date
    issue.source_url = issue_payload.get("source_url", issue.source_url)
    issue.save()
    return issue


def get_or_create_section(journal: Journal, section_name: str) -> Section | None:
    cleaned = normalize_whitespace(section_name)
    if not cleaned:
        return None
    section, _ = Section.objects.get_or_create(
        journal=journal,
        slug=safe_slug(cleaned, "section"),
        defaults={"name": cleaned},
    )
    if section.name != cleaned:
        section.name = cleaned
        section.save(update_fields=["name", "updated_at"])
    return section


def get_or_create_author(display_name: str, affiliation_name: str) -> tuple[Author, Affiliation | None]:
    display_name = normalize_whitespace(display_name)
    last_name, first_name, middle_name = parse_person_name(display_name)
    author_slug = safe_slug(display_name or "author", "author")
    author, _ = Author.objects.get_or_create(
        slug=author_slug,
        defaults={
            "first_name": first_name,
            "last_name": last_name,
            "middle_name": middle_name,
        },
    )
    author.first_name = first_name
    author.last_name = last_name
    author.middle_name = middle_name
    author.save()

    affiliation = None
    if cleaned_affiliation := normalize_whitespace(affiliation_name):
        affiliation, _ = Affiliation.objects.get_or_create(name=cleaned_affiliation)
        author.affiliations.add(affiliation)
    return author, affiliation


def upsert_ojs_article(
    journal: Journal,
    issue_payload: dict[str, Any],
    article_payload: dict[str, Any],
    session: requests.Session,
    *,
    download_pdf: bool = True,
) -> tuple[Article, bool, bool]:
    issue = get_or_create_issue(journal, issue_payload)
    section = get_or_create_section(journal, article_payload.get("section") or issue_payload.get("section", ""))
    source_identifier = f"ojs:{article_payload['article_id']}"
    article = Article.objects.filter(source_identifier=source_identifier).first()
    created = article is None
    if article is None:
        article = Article(
            journal=journal,
            issue=issue,
            slug=f"ojs-{article_payload['article_id']}",
            source_identifier=source_identifier,
        )

    article.journal = journal
    article.issue = issue
    article.section = section
    article.title = article_payload["title"]
    article.language = article_payload.get("language") or Article.LANGUAGE_RU
    article.pages = article_payload.get("pages", "")
    article.doi = article_payload.get("doi", "")
    article.original_url = article_payload.get("original_url", "")
    article.abstract = article_payload.get("abstract", "")
    article.import_source = "ojs_sync"
    article.is_published = True
    article.save()

    ArticleAuthor.objects.filter(article=article).delete()
    for order, author_payload in enumerate(article_payload.get("authors", []), start=1):
        author, affiliation = get_or_create_author(
            author_payload.get("name", ""),
            author_payload.get("affiliation", ""),
        )
        ArticleAuthor.objects.create(
            article=article,
            author=author,
            affiliation=affiliation,
            order=order,
            display_name=normalize_whitespace(author_payload.get("name", "")) or author.full_name,
        )

    existing_text = ArticleText.objects.filter(article=article).first()
    references_text = "\n".join(article_payload.get("references", [])) or (existing_text.references_text if existing_text else "")
    body_text = ""
    pdf_saved = False
    article_file = ArticleFile.objects.filter(article=article, file_kind=ArticleFile.KIND_PDF).first()

    pdf_url = article_payload.get("pdf_url", "")
    if download_pdf and pdf_url:
        pdf_bytes, body_text = download_pdf_payload(session, pdf_url)
        article_file, _ = ArticleFile.objects.get_or_create(
            article=article,
            file_kind=ArticleFile.KIND_PDF,
            defaults={
                "original_filename": f"ojs-{article_payload['article_id']}.pdf",
                "external_url": pdf_url,
            },
        )
        if not article_file.file:
            article_file.file.save(
                f"ojs-{article_payload['article_id']}.pdf",
                ContentFile(pdf_bytes),
                save=False,
            )
        article_file.original_filename = article_file.original_filename or f"ojs-{article_payload['article_id']}.pdf"
        article_file.external_url = pdf_url
        article_file.save()
        pdf_saved = True
    elif article_file:
        body_text = extract_text_from_saved_file(article_file)

    cleaned_body_text = clean_article_body_text(
        body_text or (existing_text.body_text if existing_text else ""),
        title=article_payload["title"],
        abstract_text=article_payload.get("abstract", ""),
        keywords_text=", ".join(article_payload.get("keywords", [])),
        language=article.language,
    )

    ArticleText.objects.update_or_create(
        article=article,
        defaults={
            "title_text": article_payload["title"],
            "abstract_text": article_payload.get("abstract", ""),
            "keywords_text": ", ".join(article_payload.get("keywords", [])),
            "body_text": cleaned_body_text,
            "references_text": references_text,
        },
    )
    sync_keywords_for_article(article, ", ".join(article_payload.get("keywords", [])))
    return article, created, pdf_saved
