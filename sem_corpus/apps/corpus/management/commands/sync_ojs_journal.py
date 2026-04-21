from __future__ import annotations

from django.core.management.base import BaseCommand

from sem_corpus.apps.corpus.models import Article
from sem_corpus.apps.corpus.ojs_import import (
    SyncCounters,
    build_session,
    fetch_archive_issue_urls,
    parse_article_page,
    parse_issue_page,
    resolve_journal,
    upsert_ojs_article,
)


class Command(BaseCommand):
    help = "Synchronize all available issues and articles from the journal OJS archive."

    def write_message(self, message: str, *, error: bool = False, success: bool = False):
        stream = self.stderr if error else self.stdout
        safe_message = message.encode("cp1251", "backslashreplace").decode("cp1251")
        if success and not error:
            stream.write(self.style.SUCCESS(safe_message))
        elif error:
            stream.write(self.style.WARNING(safe_message))
        else:
            stream.write(safe_message)

    def add_arguments(self, parser):
        parser.add_argument(
            "--archive-url",
            default="https://izdat.istu.ru/index.php/social-economic-management/issue/archive",
            help="Archive page of the journal OJS installation.",
        )
        parser.add_argument(
            "--limit-issues",
            type=int,
            default=0,
            help="Limit the number of issues processed, starting from the newest.",
        )
        parser.add_argument(
            "--limit-articles",
            type=int,
            default=0,
            help="Limit the total number of articles processed.",
        )
        parser.add_argument(
            "--skip-existing",
            action="store_true",
            help="Skip articles that are already present in the corpus by OJS source identifier.",
        )
        parser.add_argument(
            "--skip-pdf-download",
            action="store_true",
            help="Only import metadata without downloading and extracting PDF texts.",
        )

    def handle(self, *args, **options):
        session = build_session()
        counters = SyncCounters()
        journal = resolve_journal()

        issue_urls = fetch_archive_issue_urls(session, options["archive_url"])
        if options["limit_issues"]:
            issue_urls = issue_urls[: options["limit_issues"]]

        if not issue_urls:
            self.write_message("No issues found in the journal archive.", error=True)
            return

        article_limit = options["limit_articles"] or None
        download_pdf = not options["skip_pdf_download"]

        for issue_url in issue_urls:
            issue_payload = parse_issue_page(session, issue_url)
            counters.issues_seen += 1
            self.write_message(
                f"Processing issue {issue_payload['year']} / vol. {issue_payload['volume']} / no. {issue_payload['number']}"
            )
            for article_stub in issue_payload["articles"]:
                if article_limit is not None and counters.articles_seen >= article_limit:
                    break
                article_id = article_stub["url"].rstrip("/").split("/")[-1]
                if options["skip_existing"] and Article.objects.filter(source_identifier=f"ojs:{article_id}").exists():
                    continue
                counters.articles_seen += 1

                article_payload = parse_article_page(session, article_stub["url"])
                if not article_payload.get("section"):
                    article_payload["section"] = article_stub.get("section", "")
                if not article_payload.get("pdf_url"):
                    article_payload["pdf_url"] = article_stub.get("pdf_url", "")

                try:
                    article, created, pdf_saved = upsert_ojs_article(
                        journal,
                        issue_payload,
                        article_payload,
                        session,
                        download_pdf=download_pdf,
                    )
                except Exception as exc:  # noqa: BLE001
                    if download_pdf:
                        counters.pdf_failed += 1
                        self.write_message(
                            f"PDF extraction failed for {article_payload.get('title') or article_stub['url']}: {exc}. "
                            "Retrying metadata-only import.",
                            error=True,
                        )
                        try:
                            article, created, pdf_saved = upsert_ojs_article(
                                journal,
                                issue_payload,
                                article_payload,
                                session,
                                download_pdf=False,
                            )
                        except Exception as retry_exc:  # noqa: BLE001
                            self.write_message(
                                f"Skipped article {article_payload.get('title') or article_stub['url']}: {retry_exc}",
                                error=True,
                            )
                            continue
                    else:
                        counters.pdf_failed += 1
                        self.write_message(
                            f"Skipped article {article_payload.get('title') or article_stub['url']}: {exc}",
                            error=True,
                        )
                        continue

                if created:
                    counters.articles_created += 1
                else:
                    counters.articles_updated += 1
                if pdf_saved:
                    counters.pdf_downloaded += 1
                self.write_message(
                    f"  -> {article.title} ({'created' if created else 'updated'})",
                    success=True,
                )
            if article_limit is not None and counters.articles_seen >= article_limit:
                break

        self.write_message("")
        self.write_message("OJS sync completed.", success=True)
        self.write_message(f"Issues processed: {counters.issues_seen}")
        self.write_message(f"Articles processed: {counters.articles_seen}")
        self.write_message(f"Articles created: {counters.articles_created}")
        self.write_message(f"Articles updated: {counters.articles_updated}")
        self.write_message(f"PDF files downloaded: {counters.pdf_downloaded}")
        self.write_message(f"PDF/text extraction failures: {counters.pdf_failed}")
