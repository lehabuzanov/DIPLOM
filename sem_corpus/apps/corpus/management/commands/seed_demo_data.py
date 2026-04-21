from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from sem_corpus.apps.accounts.models import Role
from sem_corpus.apps.corpus.models import Journal


User = get_user_model()


class Command(BaseCommand):
    help = "Creates base roles, service users and journal metadata without loading demo articles."

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

        roles = {
            "researcher": Role.objects.get_or_create(
                slug="researcher",
                defaults={"name": "Исследователь", "can_save_queries": True},
            )[0],
            "editor": Role.objects.get_or_create(
                slug="editor",
                defaults={"name": "Редактор", "can_edit_content": True, "can_run_imports": True, "can_save_queries": True},
            )[0],
            "administrator": Role.objects.get_or_create(
                slug="administrator",
                defaults={
                    "name": "Администратор",
                    "can_manage_users": True,
                    "can_edit_content": True,
                    "can_run_imports": True,
                    "can_save_queries": True,
                },
            )[0],
        }

        researcher, _ = User.objects.get_or_create(
            username="researcher",
            defaults={"email": "researcher@example.com", "first_name": "Научный", "last_name": "Пользователь"},
        )
        researcher.set_password("research123")
        researcher.save()
        researcher.profile.institution = "ИжГТУ имени М. Т. Калашникова"
        researcher.profile.primary_role = roles["researcher"]
        researcher.profile.save()

        editor, _ = User.objects.get_or_create(
            username="editor",
            defaults={"email": "editor@example.com", "first_name": "Редактор", "last_name": "Корпуса", "is_staff": True},
        )
        editor.is_staff = True
        editor.set_password("editor123")
        editor.save()
        editor.profile.institution = "ИжГТУ имени М. Т. Калашникова"
        editor.profile.primary_role = roles["editor"]
        editor.profile.save()

        admin_user, _ = User.objects.get_or_create(
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
        admin_user.set_password("admin123")
        admin_user.save()
        admin_user.profile.primary_role = roles["administrator"]
        admin_user.profile.save()

        self.stdout.write(self.style.SUCCESS("Служебные роли и пользователи подготовлены."))
        self.stdout.write("Пользователь researcher / пароль research123")
        self.stdout.write("Пользователь editor / пароль editor123")
        self.stdout.write("Пользователь admin / пароль admin123")
