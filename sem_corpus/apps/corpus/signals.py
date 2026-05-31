from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from sem_corpus.apps.corpus.models import Article, ArticleFile, ArticleText
from sem_corpus.apps.corpus.services import cleanup_orphan_corpus_records, rebuild_article_index


@receiver(post_save, sender=ArticleText)
def rebuild_index_after_text_save(sender, instance, created, **kwargs):
    if kwargs.get("raw"):
        return
    rebuild_article_index(instance.article)


@receiver(post_delete, sender=ArticleFile)
def delete_article_file_after_row_delete(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)


@receiver(post_delete, sender=Article)
def cleanup_after_article_delete(sender, instance, **kwargs):
    transaction.on_commit(cleanup_orphan_corpus_records)
