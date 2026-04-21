from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sem_corpus.apps.accounts"
    verbose_name = "Пользователи и роли"

    def ready(self):
        from sem_corpus.apps.accounts import signals  # noqa: F401
