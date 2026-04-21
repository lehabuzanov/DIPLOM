from django.db.models.signals import post_save
from django.dispatch import receiver

from sem_corpus.apps.corpus.models import ArticleText
from sem_corpus.apps.corpus.services import rebuild_article_index


@receiver(post_save, sender=ArticleText)
def rebuild_index_after_text_save(sender, instance, created, **kwargs):
    if kwargs.get("raw"):
        return
    rebuild_article_index(instance.article)
