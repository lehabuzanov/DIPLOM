from __future__ import annotations

from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from sem_corpus.apps.corpus.models import Article, ArticleFile, ArticleText
from sem_corpus.apps.corpus.ojs_import import build_session, extract_text_from_pdf_bytes
from sem_corpus.apps.corpus.services import clean_article_body_text


class Command(BaseCommand):
    help = "Recover missing article texts from saved PDFs or external article files."

    def add_arguments(self, parser):
        parser.add_argument("--article-id", type=int, default=0, help="Repair only one article by database id.")
        parser.add_argument("--limit", type=int, default=0, help="Limit the number of repaired articles.")
        parser.add_argument("--force", action="store_true", help="Rebuild text even if the article already has body text.")
        parser.add_argument(
            "--skip-download",
            action="store_true",
            help="Use only locally saved files and do not request missing PDFs from remote URLs.",
        )

    def handle(self, *args, **options):
        queryset = Article.objects.published().prefetch_related("files", "keywords")
        if options["article_id"]:
            queryset = queryset.filter(pk=options["article_id"])
        if not options["force"]:
            queryset = queryset.exclude(text__body_text__gt="").distinct()
        if options["limit"]:
            queryset = queryset[: options["limit"]]

        session = None if options["skip_download"] else build_session()
        repaired = 0
        skipped = 0
        failed = 0

        for article in queryset:
            article_text = getattr(article, "text", None)
            article_file = article.files.filter(file_kind=ArticleFile.KIND_PDF).first()
            pdf_bytes = b""
            extracted_text = ""

            if article_file and article_file.file and article_file.file.storage.exists(article_file.file.name):
                try:
                    with article_file.file.open("rb") as fh:
                        pdf_bytes = fh.read()
                    extracted_text = extract_text_from_pdf_bytes(pdf_bytes)
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    self.stderr.write(self.style.WARNING(f"Local PDF read failed for article {article.pk}: {exc}"))

            if not extracted_text and session and article_file and article_file.external_url:
                try:
                    response = session.get(article_file.external_url, timeout=120)
                    response.raise_for_status()
                    pdf_bytes = response.content
                    extracted_text = extract_text_from_pdf_bytes(pdf_bytes)
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    self.stderr.write(self.style.WARNING(f"Remote PDF download failed for article {article.pk}: {exc}"))

            if not extracted_text:
                skipped += 1
                continue

            if article_file and pdf_bytes and (not article_file.file or not article_file.file.storage.exists(article_file.file.name)):
                filename = article_file.original_filename or f"{article.slug or 'article'}-{article.pk}.pdf"
                article_file.file.save(Path(filename).name, ContentFile(pdf_bytes), save=False)
                article_file.save(update_fields=["file", "updated_at"])

            keyword_text = ", ".join(article.keywords.values_list("name", flat=True))
            cleaned_body_text = clean_article_body_text(
                extracted_text,
                title=article.title,
                abstract_text=article.abstract or (article_text.abstract_text if article_text else ""),
                keywords_text=keyword_text or (article_text.keywords_text if article_text else ""),
                language=article.language,
            )
            defaults = {
                "title_text": article.title,
                "abstract_text": article.abstract or (article_text.abstract_text if article_text else ""),
                "keywords_text": keyword_text or (article_text.keywords_text if article_text else ""),
                "body_text": cleaned_body_text,
                "references_text": article_text.references_text if article_text else "",
            }
            ArticleText.objects.update_or_create(article=article, defaults=defaults)
            repaired += 1
            self.stdout.write(self.style.SUCCESS(f"Repaired text for article {article.pk}: {article.title}"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Recovered texts: {repaired}"))
        self.stdout.write(f"Skipped: {skipped}")
        self.stdout.write(f"Failures: {failed}")
