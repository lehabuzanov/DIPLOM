from django.conf import settings
from django.db import models

from sem_corpus.apps.core.models import TimestampedModel


class Role(TimestampedModel):
    name = models.CharField("название", max_length=120, unique=True)
    slug = models.SlugField("код", max_length=60, unique=True)
    description = models.TextField("описание", blank=True)
    can_manage_users = models.BooleanField("может управлять пользователями", default=False)
    can_edit_content = models.BooleanField("может редактировать содержимое", default=False)
    can_run_imports = models.BooleanField("может запускать импорт", default=False)
    can_save_queries = models.BooleanField("может сохранять запросы", default=False)

    class Meta:
        verbose_name = "роль"
        verbose_name_plural = "роли"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class UserProfile(TimestampedModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    institution = models.CharField("организация", max_length=255, blank=True)
    position = models.CharField("должность", max_length=255, blank=True)
    preferred_language = models.CharField("предпочитаемый язык", max_length=16, default="ru")
    primary_role = models.ForeignKey(
        Role,
        verbose_name="основная роль",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="profiles",
    )

    class Meta:
        verbose_name = "профиль пользователя"
        verbose_name_plural = "профили пользователей"

    def __str__(self) -> str:
        return f"Профиль {self.user.username}"


class UserActivity(TimestampedModel):
    SEARCH = "search"
    SUBCORPUS = "subcorpus"
    EXPORT = "export"
    IMPORT = "import"
    LOGIN = "login"

    ACTIVITY_TYPES = [
        (SEARCH, "Поиск"),
        (SUBCORPUS, "Подкорпус"),
        (EXPORT, "Экспорт"),
        (IMPORT, "Импорт"),
        (LOGIN, "Вход"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="activities",
        verbose_name="пользователь",
    )
    activity_type = models.CharField("тип активности", max_length=32, choices=ACTIVITY_TYPES)
    title = models.CharField("заголовок", max_length=255)
    payload = models.JSONField("данные", default=dict, blank=True)

    class Meta:
        verbose_name = "действие пользователя"
        verbose_name_plural = "действия пользователей"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user.username}: {self.title}"
