from django.apps import AppConfig


class CorpusConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sem_corpus.apps.corpus"
    verbose_name = "Корпус журнала"

    def ready(self):
        from sem_corpus.apps.corpus import signals  # noqa: F401
