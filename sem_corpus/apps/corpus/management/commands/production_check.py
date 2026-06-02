from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import OperationalError, ProgrammingError, connection

from sem_corpus.apps.accounts.models import UserProfile
from sem_corpus.apps.corpus.models import Article, ArticleFile, ArticleText, Issue, Journal
from sem_corpus.apps.corpus.text_quality import assess_text_quality


LOCAL_HOSTS = {"127.0.0.1", "localhost", "testserver", "0.0.0.0"}
UNSAFE_SECRET_FRAGMENTS = {"change-me", "unsafe", "replace-with", "secret"}
REQUIRED_VENDOR_FILES = [
    "vendor/bootstrap/bootstrap.min.css",
    "vendor/bootstrap/bootstrap.bundle.min.js",
    "vendor/chart/chart.umd.min.js",
    "vendor/leaflet/leaflet.css",
    "vendor/leaflet/leaflet.js",
    "vendor/leaflet/images/marker-icon.png",
    "vendor/leaflet/images/marker-icon-2x.png",
    "vendor/leaflet/images/marker-shadow.png",
    "vendor/leaflet/images/layers.png",
    "vendor/leaflet/images/layers-2x.png",
]


class Command(BaseCommand):
    help = "Check whether the corpus package is ready for a production deployment."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true", help="Treat warnings as deployment blockers.")
        parser.add_argument("--min-words", type=int, default=120, help="Minimum words expected in article body text.")

    def handle(self, *args, **options):
        strict = options["strict"]
        failures: list[str] = []
        warnings: list[str] = []

        def report(level: str, label: str, message: str) -> None:
            prefix = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}[level]
            line = f"[{prefix}] {label}: {message}"
            if level == "ok":
                self.stdout.write(self.style.SUCCESS(line))
            elif level == "warn":
                warnings.append(label)
                self.stdout.write(self.style.WARNING(line))
            else:
                failures.append(label)
                self.stderr.write(self.style.ERROR(line))

        self._check_settings(report)
        self._check_static_assets(report)
        self._check_database(report, options["min_words"])

        self.stdout.write("")
        self.stdout.write(f"Warnings: {len(warnings)}")
        self.stdout.write(f"Failures: {len(failures)}")

        if failures or (strict and warnings):
            raise SystemExit(1)

    def _check_settings(self, report) -> None:
        report(
            "fail" if settings.DEBUG else "ok",
            "DEBUG",
            "DJANGO_DEBUG must be 0 in production." if settings.DEBUG else "Disabled.",
        )

        secret_key = settings.SECRET_KEY or ""
        secret_lower = secret_key.lower()
        unsafe_secret = len(secret_key) < 40 or any(fragment in secret_lower for fragment in UNSAFE_SECRET_FRAGMENTS)
        report(
            "fail" if unsafe_secret else "ok",
            "SECRET_KEY",
            "Set a long random DJANGO_SECRET_KEY." if unsafe_secret else "Looks non-default.",
        )

        hosts = set(settings.ALLOWED_HOSTS or [])
        host_level = "ok"
        host_message = ", ".join(sorted(hosts)) or "no hosts configured"
        if not hosts or hosts <= LOCAL_HOSTS:
            host_level = "fail"
        elif "*" in hosts:
            host_level = "warn"
            host_message = "Wildcard host is allowed; prefer explicit production domains."
        report(host_level, "ALLOWED_HOSTS", host_message)

        csrf_origins = list(getattr(settings, "CSRF_TRUSTED_ORIGINS", []))
        report(
            "warn" if not csrf_origins else "ok",
            "CSRF_TRUSTED_ORIGINS",
            "Set https:// origins for the production host." if not csrf_origins else ", ".join(csrf_origins),
        )

        site_url = getattr(settings, "SITE_URL", "")
        report(
            "warn" if site_url.startswith("http://127.") or "localhost" in site_url else "ok",
            "SITE_URL",
            site_url or "SITE_URL is empty.",
        )

        for setting_name in ("SECURE_SSL_REDIRECT", "SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE"):
            enabled = bool(getattr(settings, setting_name, False))
            report("warn" if not enabled else "ok", setting_name, "Enable for HTTPS production deployments.")

        hsts_seconds = int(getattr(settings, "SECURE_HSTS_SECONDS", 0))
        report("warn" if hsts_seconds <= 0 else "ok", "SECURE_HSTS_SECONDS", str(hsts_seconds))

        email_backend = getattr(settings, "EMAIL_BACKEND", "")
        require_email = bool(getattr(settings, "ACCOUNTS_REQUIRE_EMAIL_CONFIRMATION", False))
        if require_email and "smtp" not in email_backend.lower():
            report("fail", "EMAIL_BACKEND", "Email confirmation requires an SMTP backend.")
        else:
            report("warn" if "console" in email_backend.lower() else "ok", "EMAIL_BACKEND", email_backend)

    def _check_static_assets(self, report) -> None:
        static_roots = [Path(path) for path in getattr(settings, "STATICFILES_DIRS", [])]
        missing_vendor: list[str] = []
        for relative_path in REQUIRED_VENDOR_FILES:
            if not any((root / relative_path).exists() for root in static_roots):
                missing_vendor.append(relative_path)

        report(
            "fail" if missing_vendor else "ok",
            "Local vendor assets",
            "Missing: " + ", ".join(missing_vendor) if missing_vendor else "Bootstrap, Chart.js and Leaflet are local.",
        )

        static_root = Path(settings.STATIC_ROOT)
        report(
            "warn" if not static_root.exists() else "ok",
            "STATIC_ROOT",
            f"{static_root} exists." if static_root.exists() else "Run collectstatic before serving production traffic.",
        )

    def _check_database(self, report, min_words: int) -> None:
        try:
            connection.ensure_connection()
        except OperationalError as exc:
            report("fail", "Database", f"Cannot connect: {exc}")
            return

        try:
            journal_count = Journal.objects.count()
            issue_count = Issue.objects.count()
            article_count = Article.objects.published().count()
            text_count = ArticleText.objects.filter(article__is_published=True).count()
        except (OperationalError, ProgrammingError) as exc:
            report("fail", "Database schema", f"Cannot query corpus tables: {exc}")
            return

        report("ok" if journal_count else "fail", "Journals", str(journal_count))
        report("ok" if issue_count else "fail", "Issues", str(issue_count))
        report("ok" if article_count else "fail", "Published articles", str(article_count))
        report(
            "ok" if article_count == text_count else "fail",
            "Article texts",
            f"{text_count}/{article_count} published articles have ArticleText.",
        )

        missing_body = Article.objects.published().exclude(text__body_text__gt="").distinct().count()
        report(
            "ok" if missing_body == 0 else "fail",
            "Body text completeness",
            f"{missing_body} published article(s) have no body text.",
        )

        quality_issues = 0
        private_use_articles = 0
        for article_text in ArticleText.objects.filter(article__is_published=True).iterator(chunk_size=200):
            quality = assess_text_quality(article_text.body_text, min_words=min_words)
            if quality.flags:
                quality_issues += 1
            if quality.private_use_count:
                private_use_articles += 1

        report(
            "ok" if private_use_articles == 0 else "fail",
            "Private-use PDF artifacts",
            f"{private_use_articles} article(s) still contain private-use symbols.",
        )
        report(
            "ok" if quality_issues == 0 else "warn",
            "Text quality audit",
            f"{quality_issues} article(s) have quality flags at min_words={min_words}.",
        )

        missing_vector = ArticleText.objects.filter(article__is_published=True, search_vector__isnull=True).count()
        report(
            "ok" if missing_vector == 0 else "fail",
            "Search vectors",
            f"{missing_vector} published article text(s) need index rebuild.",
        )

        missing_files = 0
        for article_file in ArticleFile.objects.filter(article__is_published=True):
            has_local_file = bool(
                article_file.file and article_file.file.storage.exists(article_file.file.name)
            )
            if not has_local_file and not article_file.external_url:
                missing_files += 1
        report(
            "ok" if missing_files == 0 else "fail",
            "Article files",
            f"{missing_files} file record(s) have neither local media nor external URL.",
        )

        role_count = UserProfile.objects.filter(
            primary_role__isnull=False,
        ).filter(
            primary_role__can_edit_content=True
        ).count()
        report(
            "ok" if role_count else "warn",
            "Staff roles",
            "At least one editor/admin role exists." if role_count else "Create editor/admin accounts for maintenance.",
        )
