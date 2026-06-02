from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import OperationalError, ProgrammingError, connection

from sem_corpus.apps.corpus.models import Article, ArticleFile
from sem_corpus.apps.corpus.pdf_extraction import extract_pdf_text_result
from sem_corpus.apps.corpus.text_quality import assess_text_quality


class Command(BaseCommand):
    help = "Audit corpus article texts for PDF extraction and text-quality issues."

    def add_arguments(self, parser):
        parser.add_argument("--article-id", type=int, default=0, help="Audit only one article by database id.")
        parser.add_argument("--limit", type=int, default=0, help="Limit the number of audited articles.")
        parser.add_argument("--min-words", type=int, default=120, help="Minimum words expected in a healthy body text.")
        parser.add_argument(
            "--check-pdf-pages",
            action="store_true",
            help="Read local PDF files and report empty/image-only pages when the extractor can detect them.",
        )
        parser.add_argument(
            "--fail-on-issues",
            action="store_true",
            help="Exit with non-zero status if any text-quality issue is found.",
        )

    def handle(self, *args, **options):
        try:
            connection.ensure_connection()
        except OperationalError as exc:
            self.stderr.write(self.style.ERROR(f"Database is unavailable: {exc}"))
            raise SystemExit(1) from exc

        queryset = Article.objects.published().select_related("text").prefetch_related("files")
        if options["article_id"]:
            queryset = queryset.filter(pk=options["article_id"])
        if options["limit"]:
            queryset = queryset[: options["limit"]]

        checked = 0
        issue_rows: list[dict[str, object]] = []
        pdf_warnings = 0

        try:
            article_iterable = list(queryset)
        except (OperationalError, ProgrammingError) as exc:
            self.stderr.write(self.style.ERROR(f"Cannot query corpus articles: {exc}"))
            raise SystemExit(1) from exc

        for article in article_iterable:
            checked += 1
            article_text = getattr(article, "text", None)
            body_text = article_text.body_text if article_text else ""
            quality = assess_text_quality(body_text, min_words=options["min_words"])
            flags = list(quality.flags)

            pdf_report = None
            if options["check_pdf_pages"]:
                article_file = article.files.filter(file_kind=ArticleFile.KIND_PDF).first()
                if article_file and article_file.file and article_file.file.storage.exists(article_file.file.name):
                    try:
                        with article_file.file.open("rb") as fh:
                            pdf_report = extract_pdf_text_result(fh.read())
                        if pdf_report.empty_pages or pdf_report.image_only_pages or pdf_report.warnings:
                            pdf_warnings += 1
                            if pdf_report.empty_pages:
                                flags.append(f"pdf_empty_pages:{pdf_report.empty_pages}")
                            if pdf_report.image_only_pages:
                                flags.append(f"pdf_image_only_pages:{pdf_report.image_only_pages}")
                    except Exception as exc:  # noqa: BLE001
                        flags.append(f"pdf_read_failed:{exc}")

            if flags:
                issue_rows.append(
                    {
                        "id": article.pk,
                        "title": article.title,
                        "flags": flags,
                        "chars": quality.char_count,
                        "words": quality.word_count,
                        "private_use": quality.private_use_count,
                        "engine": pdf_report.engine if pdf_report else "",
                    }
                )

        self.stdout.write(f"Articles checked: {checked}")
        self.stdout.write(f"Articles with issues: {len(issue_rows)}")
        if options["check_pdf_pages"]:
            self.stdout.write(f"PDF page warnings: {pdf_warnings}")

        if issue_rows:
            self.stdout.write("")
            self.stdout.write("Problematic articles:")
            for row in issue_rows[:80]:
                engine = f", engine={row['engine']}" if row["engine"] else ""
                self.stdout.write(
                    f"- #{row['id']}: chars={row['chars']}, words={row['words']}, "
                    f"private_use={row['private_use']}{engine}; flags={', '.join(row['flags'])}; "
                    f"{row['title']}"
                )
            if len(issue_rows) > 80:
                self.stdout.write(f"... {len(issue_rows) - 80} more article(s) omitted.")

        if issue_rows and options["fail_on_issues"]:
            raise SystemExit(1)
