from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from sem_corpus.apps.accounts.access import (
    ROLE_ADMINISTRATOR,
    ROLE_EDITOR,
    ROLE_RESEARCHER,
    assign_role,
    ensure_access_control,
)
from sem_corpus.apps.accounts.models import UserProfile
from sem_corpus.apps.corpus.models import Journal


User = get_user_model()


class Command(BaseCommand):
    help = "Creates base roles, service users and journal metadata without loading demo articles."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-passwords",
            action="store_true",
            help="Reset passwords for built-in local demo users. Do not use in production.",
        )

    def handle(self, *args, **options):
        Journal.objects.get_or_create(
            short_title="Социально-экономическое управление: теория и практика",
            defaults={
                "title": "Научный журнал «Социально-экономическое управление: теория и практика»",
                "publisher": "ИжГТУ имени М. Т. Калашникова",
                "description": "Электронный корпус научного журнала для хранения, поиска и анализа публикаций.",
                "site_url": "https://izdat.istu.ru/index.php/social-economic-management",
                "integration_hint": "Отдельный путь /corpus/ или самостоятельный поддомен.",
            },
        )

        ensure_access_control()
        reset_passwords = options["reset_passwords"]

        researcher, researcher_created = User.objects.get_or_create(
            username="researcher",
            defaults={"email": "researcher@example.com", "first_name": "Научный", "last_name": "Пользователь"},
        )
        if researcher_created or reset_passwords:
            researcher.set_password("research123")
        researcher.save()
        researcher_profile, _ = UserProfile.objects.get_or_create(user=researcher)
        researcher_profile.institution = "ИжГТУ имени М. Т. Калашникова"
        researcher_profile.save()
        assign_role(researcher, ROLE_RESEARCHER)

        editor, editor_created = User.objects.get_or_create(
            username="editor",
            defaults={"email": "editor@example.com", "first_name": "Редактор", "last_name": "Корпуса", "is_staff": True},
        )
        editor.is_staff = True
        if editor_created or reset_passwords:
            editor.set_password("editor123")
        editor.save()
        editor_profile, _ = UserProfile.objects.get_or_create(user=editor)
        editor_profile.institution = "ИжГТУ имени М. Т. Калашникова"
        editor_profile.save()
        assign_role(editor, ROLE_EDITOR)

        admin_user, admin_created = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@example.com",
                "first_name": "Системный",
                "last_name": "Администратор",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        admin_user.is_staff = True
        admin_user.is_superuser = True
        if admin_created or reset_passwords:
            admin_user.set_password("admin123")
        admin_user.save()
        assign_role(admin_user, ROLE_ADMINISTRATOR)

        self.stdout.write(self.style.SUCCESS("Служебные роли и пользователи подготовлены."))
        if reset_passwords:
            self.stdout.write("Пароли локальных демо-пользователей сброшены.")
            self.stdout.write("Пользователь researcher / пароль research123")
            self.stdout.write("Пользователь editor / пароль editor123")
            self.stdout.write("Пользователь admin / пароль admin123")
        else:
            self.stdout.write("Существующие пароли не изменялись.")
