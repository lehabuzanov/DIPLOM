from django.core.management.base import BaseCommand

from sem_corpus.apps.corpus.models import Article
from sem_corpus.apps.corpus.services import rebuild_article_index


class Command(BaseCommand):
    help = "Перестраивает токенизацию, лемматизацию и поисковые индексы для всех статей корпуса."

    def handle(self, *args, **options):
        for article in Article.objects.select_related("text"):
            if hasattr(article, "text"):
                rebuild_article_index(article)
                self.stdout.write(self.style.SUCCESS(f"Индекс обновлен: {article.title}"))
