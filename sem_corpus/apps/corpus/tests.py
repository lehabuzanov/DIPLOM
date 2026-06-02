from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from sem_corpus.apps.accounts.access import ROLE_EDITOR, assign_role, ensure_access_control
from sem_corpus.apps.corpus.forms import SearchForm
from sem_corpus.apps.corpus.models import Article, ArticleText, Issue, Journal, Section
from sem_corpus.apps.corpus.pdf_extraction import extract_pdf_text_result
from sem_corpus.apps.corpus.services import HIGHLIGHT_END, HIGHLIGHT_START, render_highlighted_context, search_articles
from sem_corpus.apps.corpus.text_quality import assess_text_quality, count_private_use, sanitize_extracted_text

try:
    import fitz
except ImportError:  # pragma: no cover - dependency is installed in the Docker image
    fitz = None


def make_pdf_payload(text: str) -> bytes:
    if fitz is None:
        raise unittest.SkipTest("PyMuPDF is not installed.")
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    return document.tobytes()


class CorpusTestDataMixin:
    def create_article(self, *, title: str = "Corpus analytics article", slug: str = "corpus-article") -> Article:
        journal = Journal.objects.create(
            title="Test Journal",
            short_title="Test Journal",
            site_url="https://journal.example.org",
            is_active=True,
        )
        issue = Issue.objects.create(journal=journal, year=2026, volume="1", number="1", title="Test Issue")
        section = Section.objects.create(journal=journal, name="Articles", slug="articles")
        article = Article.objects.create(
            journal=journal,
            issue=issue,
            section=section,
            title=title,
            slug=slug,
            language=Article.LANGUAGE_EN,
            abstract="Short abstract about corpus analytics.",
            is_published=True,
        )
        body = " ".join(["corpus analytics search safety extraction"] * 40)
        ArticleText.objects.create(
            article=article,
            title_text=article.title,
            abstract_text=article.abstract,
            keywords_text="corpus, analytics",
            body_text=body,
        )
        article.refresh_from_db()
        return article


class TextAndHighlightTests(TestCase):
    def test_sanitize_extracted_text_removes_private_use_symbols(self):
        raw_text = "alpha\ue000 beta\r\nsoft\u00adhyphen"

        cleaned = sanitize_extracted_text(raw_text)
        quality = assess_text_quality(cleaned, min_words=1)

        self.assertEqual(count_private_use(cleaned), 0)
        self.assertIn("alpha", cleaned)
        self.assertIn("softhyphen", cleaned)
        self.assertTrue(quality.ok)

    def test_render_highlighted_context_escapes_untrusted_html(self):
        raw_context = f"<script>alert(1)</script> {HIGHLIGHT_START}<img src=x onerror=alert(2)>{HIGHLIGHT_END}"

        rendered = str(render_highlighted_context(raw_context))

        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertIn("<mark>&lt;img src=x onerror=alert(2)&gt;</mark>", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<img src=x", rendered)


@unittest.skipUnless(fitz is not None, "PyMuPDF is not installed.")
class PDFExtractionTests(TestCase):
    def test_extract_pdf_text_result_returns_clean_text(self):
        payload = make_pdf_payload("Corpus PDF extraction text")

        result = extract_pdf_text_result(payload)

        self.assertGreater(result.page_count, 0)
        self.assertEqual(result.empty_pages, 0)
        self.assertIn("Corpus PDF extraction text", result.text)
        self.assertEqual(count_private_use(result.text), 0)


class SearchAndPageTests(CorpusTestDataMixin, TestCase):
    def setUp(self):
        self.article = self.create_article()

    def test_fulltext_search_returns_safe_highlighted_context(self):
        form = SearchForm({"text_query": "corpus", "search_mode": SearchForm.SEARCH_FULLTEXT})
        self.assertTrue(form.is_valid(), form.errors)

        results = search_articles(form, record_history=False)

        self.assertTrue(results)
        self.assertIn("<mark>", str(results[0]["contexts"][0]))

    def test_main_public_pages_return_success(self):
        urls = [
            reverse("core:home"),
            reverse("core:about"),
            reverse("core:guide"),
            reverse("corpus:issue-list"),
            reverse("corpus:article-list"),
            reverse("corpus:search"),
            reverse("corpus:geography"),
            reverse("analytics:dashboard"),
            self.article.get_absolute_url(),
        ]

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)


@unittest.skipUnless(fitz is not None, "PyMuPDF is not installed.")
class EditorUploadTests(TestCase):
    def test_editor_can_upload_pdf_and_extract_body_text(self):
        ensure_access_control()
        User = get_user_model()
        editor = User.objects.create_user(username="editor-test", password="pass")
        assign_role(editor, ROLE_EDITOR)
        self.client.force_login(editor)

        payload = make_pdf_payload("Uploaded corpus article body " * 20)
        uploaded = SimpleUploadedFile("article.pdf", payload, content_type="application/pdf")

        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.post(
                reverse("corpus:editor-upload"),
                {
                    "issue_year": 2026,
                    "issue_volume": "1",
                    "issue_number": "2",
                    "section_name": "Articles",
                    "title": "Uploaded PDF Article",
                    "language": Article.LANGUAGE_EN,
                    "authors_text": "Ivan Ivanov | Test University",
                    "source_file": uploaded,
                    "is_published": "on",
                },
            )

        self.assertEqual(response.status_code, 302)
        article = Article.objects.get(title="Uploaded PDF Article")
        self.assertIn("Uploaded corpus article body", article.text.body_text)
        self.assertEqual(count_private_use(article.text.body_text), 0)


class ProductionCheckTests(CorpusTestDataMixin, TestCase):
    def test_production_check_passes_for_hardened_settings_and_clean_data(self):
        self.create_article()
        ensure_access_control()
        User = get_user_model()
        editor = User.objects.create_user(username="production-editor", password="pass")
        assign_role(editor, ROLE_EDITOR)

        with tempfile.TemporaryDirectory() as static_root:
            output = io.StringIO()
            errors = io.StringIO()
            Path(static_root).mkdir(parents=True, exist_ok=True)
            with override_settings(
                DEBUG=False,
                SECRET_KEY="x" * 64,
                ALLOWED_HOSTS=["corpus.example.org"],
                CSRF_TRUSTED_ORIGINS=["https://corpus.example.org"],
                SITE_URL="https://corpus.example.org",
                SECURE_SSL_REDIRECT=True,
                SESSION_COOKIE_SECURE=True,
                CSRF_COOKIE_SECURE=True,
                SECURE_HSTS_SECONDS=2592000,
                EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
                ACCOUNTS_REQUIRE_EMAIL_CONFIRMATION=True,
                STATIC_ROOT=static_root,
            ):
                call_command("production_check", "--strict", stdout=output, stderr=errors)

        self.assertIn("Failures: 0", output.getvalue())
        self.assertEqual(errors.getvalue(), "")
