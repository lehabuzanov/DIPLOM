from django.core.management.base import BaseCommand
from django.db.models import Count

from sem_corpus.apps.corpus.models import Affiliation, Article, Author, SavedQuery, SavedSubcorpus


class Command(BaseCommand):
    help = "Removes legacy demo articles, demo saved queries and demo subcorpora from the corpus."

    def handle(self, *args, **options):
        demo_article_total = Article.objects.filter(import_source="seed_demo_data").count()
        Article.objects.filter(import_source="seed_demo_data").delete()

        SavedQuery.objects.filter(description__icontains="демонстрацион").delete()
        SavedSubcorpus.objects.filter(
            name__in=[
                "Лингвистический подкорпус 2024–2025",
                "Цифровая экономика 2023–2025",
            ]
        ).delete()
        Author.objects.annotate(article_total=Count("articles")).filter(article_total=0).delete()
        Affiliation.objects.annotate(author_total=Count("authors")).filter(author_total=0).delete()

        self.stdout.write(self.style.SUCCESS(f"Удалено демо-статей: {demo_article_total}"))
