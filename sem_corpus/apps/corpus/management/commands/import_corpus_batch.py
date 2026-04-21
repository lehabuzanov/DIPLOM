from __future__ import annotations

import json
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

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
from sem_corpus.apps.corpus.services import sync_keywords_for_article


class Command(BaseCommand):
    help = "Импортирует статьи из metadata.json и связанных файлов."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            dest="source",
            default="sample_data/batch_import",
            help="Каталог с metadata.json и подпапками files/texts.",
        )

    def handle(self, *args, **options):
        source_dir = Path(options["source"]).resolve()
        metadata_path = source_dir / "metadata.json"
        if not metadata_path.exists():
            raise CommandError(f"Файл {metadata_path} не найден.")

        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        journal_data = payload["journal"]
        journal, _ = Journal.objects.get_or_create(
            short_title=journal_data["short_title"],
            defaults={
                "title": journal_data["title"],
                "publisher": journal_data.get("publisher", ""),
                "description": journal_data.get("description", ""),
                "site_url": journal_data.get("site_url", ""),
            },
        )

        for item in payload["articles"]:
            issue, _ = Issue.objects.get_or_create(
                journal=journal,
                year=item["year"],
                volume=item["volume"],
                number=item["number"],
                defaults={"title": item.get("issue_title", ""), "source_url": item.get("issue_url", "")},
            )
            section, _ = Section.objects.get_or_create(
                journal=journal,
                slug=slugify(item["section"]),
                defaults={"name": item["section"]},
            )
            article, _ = Article.objects.get_or_create(
                slug=item["slug"],
                defaults={
                    "journal": journal,
                    "issue": issue,
                    "section": section,
                    "title": item["title"],
                    "language": item.get("language", Article.LANGUAGE_RU),
                    "pages": item.get("pages", ""),
                    "doi": item.get("doi", ""),
                    "abstract": item.get("abstract", ""),
                    "original_url": item.get("original_url", ""),
                    "import_source": f"batch:{source_dir.name}",
                    "is_published": item.get("is_published", True),
                },
            )
            article.issue = issue
            article.section = section
            article.title = item["title"]
            article.abstract = item.get("abstract", "")
            article.language = item.get("language", Article.LANGUAGE_RU)
            article.pages = item.get("pages", "")
            article.doi = item.get("doi", "")
            article.original_url = item.get("original_url", "")
            article.import_source = f"batch:{source_dir.name}"
            article.is_published = item.get("is_published", True)
            article.save()

            ArticleAuthor.objects.filter(article=article).delete()
            for order, author_data in enumerate(item.get("authors", []), start=1):
                affiliation = None
                if affiliation_name := author_data.get("affiliation"):
                    affiliation, _ = Affiliation.objects.get_or_create(name=affiliation_name)
                author, _ = Author.objects.get_or_create(
                    slug=author_data.get("slug") or slugify(author_data["last_name"] + "-" + author_data["first_name"]),
                    defaults={
                        "first_name": author_data["first_name"],
                        "last_name": author_data["last_name"],
                        "middle_name": author_data.get("middle_name", ""),
                    },
                )
                author.first_name = author_data["first_name"]
                author.last_name = author_data["last_name"]
                author.middle_name = author_data.get("middle_name", "")
                author.save()
                if affiliation:
                    author.affiliations.add(affiliation)
                ArticleAuthor.objects.create(
                    article=article,
                    author=author,
                    affiliation=affiliation,
                    order=order,
                    display_name=author_data.get("display_name", author.full_name),
                )

            text_path = source_dir / item["text_file"]
            if not text_path.exists():
                raise CommandError(f"Файл текста не найден: {text_path}")
            references = item.get("references", "")
            ArticleText.objects.update_or_create(
                article=article,
                defaults={
                    "title_text": item["title"],
                    "abstract_text": item.get("abstract", ""),
                    "keywords_text": ", ".join(item.get("keywords", [])),
                    "body_text": text_path.read_text(encoding="utf-8"),
                    "references_text": references,
                },
            )

            sync_keywords_for_article(article, ", ".join(item.get("keywords", [])))

            if source_file := item.get("source_file"):
                source_file_path = source_dir / source_file
                if source_file_path.exists():
                    article_file, _ = ArticleFile.objects.get_or_create(
                        article=article,
                        file_kind=ArticleFile.KIND_PDF if source_file_path.suffix.lower() == ".pdf" else ArticleFile.KIND_OTHER,
                        defaults={"original_filename": source_file_path.name},
                    )
                    with source_file_path.open("rb") as fh:
                        article_file.file.save(source_file_path.name, File(fh), save=True)
                    article_file.original_filename = source_file_path.name
                    article_file.external_url = item.get("original_url", "")
                    article_file.save()

            self.stdout.write(self.style.SUCCESS(f"Импортирована статья: {article.title}"))
