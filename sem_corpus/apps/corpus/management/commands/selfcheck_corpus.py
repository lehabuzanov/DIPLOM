from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.test import Client
from django.urls import reverse

from sem_corpus.apps.corpus.forms import SearchForm
from sem_corpus.apps.corpus.models import Article, ArticleFile, ArticleToken, Issue, SavedQuery, SavedSubcorpus
from sem_corpus.apps.corpus.services import search_articles


User = get_user_model()


class Command(BaseCommand):
    help = "Run a lightweight readiness check for the corpus MVP."

    def handle(self, *args, **options):
        failures: list[str] = []
        notes: list[str] = []

        def check(label: str, condition: bool, success_text: str, failure_text: str):
            if condition:
                self.stdout.write(self.style.SUCCESS(f"[OK] {label}: {success_text}"))
            else:
                self.stderr.write(self.style.ERROR(f"[FAIL] {label}: {failure_text}"))
                failures.append(label)

        client = Client(SERVER_NAME="localhost")
        article = Article.objects.published().select_related("text", "issue").first()
        editor = User.objects.filter(username="editor").first()
        researcher = User.objects.filter(username="researcher").first()

        check(
            "Data presence",
            Issue.objects.exists() and Article.objects.published().exists(),
            f"{Issue.objects.count()} issues, {Article.objects.published().count()} published articles.",
            "No issues or published articles were found in the database.",
        )
        check(
            "Article text",
            bool(article and hasattr(article, "text")),
            f"Sample article: {article.title}" if article else "Texts are attached to sample articles.",
            "No article with attached text was found.",
        )
        missing_text_count = Article.objects.published().exclude(text__body_text__gt="").distinct().count()
        check(
            "Text completeness",
            missing_text_count == 0,
            "All published articles have extracted body text.",
            f"{missing_text_count} published article(s) still have no extracted body text.",
        )

        docs_dir = Path(settings.BASE_DIR) / "docs"
        check(
            "Documentation",
            (docs_dir / "user-guide.md").exists() and (docs_dir / "admin-guide.md").exists(),
            "User and admin guides are present in docs/.",
            "Required documentation files are missing from docs/.",
        )

        for name, url_name in [
            ("Home page", "core:home"),
            ("About page", "core:about"),
            ("Guide page", "core:guide"),
            ("Issue catalog", "corpus:issue-list"),
            ("Article catalog", "corpus:article-list"),
            ("Search", "corpus:search"),
            ("Analytics", "analytics:dashboard"),
        ]:
            response = client.get(reverse(url_name))
            check(name, response.status_code == 200, f"HTTP {response.status_code}", f"HTTP {response.status_code}")

        if article:
            response = client.get(article.get_absolute_url())
            check(
                "Article detail page",
                response.status_code == 200,
                f"HTTP {response.status_code}",
                f"HTTP {response.status_code}",
            )
            article_file = ArticleFile.objects.filter(article=article).first()
            if article_file:
                file_response = client.get(reverse("corpus:article-file", kwargs={"pk": article_file.pk}))
                check(
                    "Article file access",
                    file_response.status_code in {200, 302},
                    f"HTTP {file_response.status_code}",
                    f"HTTP {file_response.status_code}",
                )

            title_probe = article.title.split()[0]
            title_form = SearchForm({"text_query": title_probe, "search_mode": SearchForm.SEARCH_FULLTEXT})
            results = search_articles(title_form) if title_form.is_valid() else []
            check(
                "Full-text search",
                bool(results),
                f"Query '{title_probe}' returned {len(results)} result(s).",
                "Full-text search returned no results for a corpus article.",
            )

        token = ArticleToken.objects.filter(lemma__isnull=False).select_related("lemma").first()
        if token:
            lemma_form = SearchForm({"text_query": token.lemma.normalized, "search_mode": SearchForm.SEARCH_LEMMA})
            lemma_results = search_articles(lemma_form) if lemma_form.is_valid() else []
            check(
                "Lemma search",
                bool(lemma_results),
                f"Lemma '{token.lemma.normalized}' returned {len(lemma_results)} result(s).",
                "Lemma search returned no results.",
            )
        else:
            notes.append("Lemma search was skipped because there are no indexed tokens with lemmas yet.")

        if SavedSubcorpus.objects.exists():
            self.stdout.write(
                self.style.SUCCESS(f"[OK] Saved subcorpora: {SavedSubcorpus.objects.count()} subcorpus record(s) available.")
            )
        else:
            notes.append("No saved subcorpora were found yet. Create one from search results to test reuse scenarios.")
        saved_query_count = SavedQuery.objects.count()
        saved_query = None
        saved_subcorpus = None
        if saved_query_count:
            self.stdout.write(self.style.SUCCESS(f"[OK] Saved queries: {saved_query_count} query record(s) available."))
        else:
            notes.append("No saved queries were found yet. Save a query from the search page to test reuse scenarios.")

        if researcher:
            saved_query = SavedQuery.objects.filter(user=researcher).first()
            saved_subcorpus = SavedSubcorpus.objects.filter(user=researcher).first()
            client.force_login(researcher)
            for name, url_name in [
                ("Dashboard page", "accounts:dashboard"),
                ("Saved query list", "corpus:saved-query-list"),
                ("Saved subcorpus list", "corpus:subcorpus-list"),
            ]:
                response = client.get(reverse(url_name))
                check(name, response.status_code == 200, f"HTTP {response.status_code}", f"HTTP {response.status_code}")
            if saved_query:
                response = client.get(reverse("corpus:saved-query-edit", kwargs={"pk": saved_query.pk}))
                check("Saved query edit page", response.status_code == 200, f"HTTP {response.status_code}", f"HTTP {response.status_code}")
            else:
                notes.append("No researcher-owned saved query found for edit-page verification.")
            if saved_subcorpus:
                for name, url_name in [
                    ("Saved subcorpus detail page", "corpus:subcorpus-detail"),
                    ("Saved subcorpus edit page", "corpus:subcorpus-edit"),
                ]:
                    response = client.get(reverse(url_name, kwargs={"pk": saved_subcorpus.pk}))
                    check(name, response.status_code == 200, f"HTTP {response.status_code}", f"HTTP {response.status_code}")
            else:
                notes.append("No researcher-owned subcorpus found for detail/edit-page verification.")
            client.logout()
        else:
            notes.append("Researcher-only pages were not checked because the researcher user is missing.")

        if editor:
            client.force_login(editor)
            response = client.get(reverse("corpus:editor-upload"))
            check(
                "Editor upload page",
                response.status_code == 200,
                f"HTTP {response.status_code}",
                f"HTTP {response.status_code}",
            )
            client.logout()
        else:
            notes.append("Editor upload page was not checked because the editor user is missing.")

        ojs_count = Article.objects.filter(import_source="ojs_sync").count()
        if ojs_count:
            self.stdout.write(self.style.SUCCESS(f"[OK] OJS archive sync: {ojs_count} article(s) imported from the journal site."))
        else:
            notes.append("No OJS-synced articles were found yet. Run python manage.py sync_ojs_journal to import the archive.")

        if notes:
            self.stdout.write("")
            self.stdout.write("Notes:")
            for note in notes:
                self.stdout.write(f"- {note}")

        if failures:
            raise SystemExit(1)
