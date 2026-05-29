from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from sem_corpus.apps.accounts.access import (
    ROLE_ADMINISTRATOR,
    ROLE_EDITOR,
    ROLE_RESEARCHER,
    assign_role,
    ensure_access_control,
    get_default_researcher_role,
    sync_user_role_membership,
)
from sem_corpus.apps.accounts.models import UserProfile


class Command(BaseCommand):
    help = "Creates roles, Django groups and permissions for the corpus access model."

    def add_arguments(self, parser):
        parser.add_argument(
            "--assign-missing-researcher",
            action="store_true",
            help="Assign the researcher role to existing active users without a primary role.",
        )
        parser.add_argument(
            "--sync-service-users",
            action="store_true",
            help=(
                "Assign roles to existing legacy local users admin/editor/researcher by username "
                "without creating users, changing passwords or granting superuser status."
            ),
        )

    def handle(self, *args, **options):
        roles = ensure_access_control()
        self.stdout.write(self.style.SUCCESS("Роли, группы и разрешения подготовлены."))

        User = get_user_model()
        changed_users = 0

        if options["sync_service_users"]:
            service_roles = {
                "admin": ROLE_ADMINISTRATOR,
                "editor": ROLE_EDITOR,
                "researcher": ROLE_RESEARCHER,
            }
            for username, role_slug in service_roles.items():
                user = User.objects.filter(username=username).first()
                if not user:
                    continue
                assign_role(user, role_slug)
                changed_users += 1

        if options["assign_missing_researcher"]:
            researcher_role = get_default_researcher_role()
            users_without_role = User.objects.filter(is_active=True, profile__primary_role__isnull=True)
            for user in users_without_role:
                profile, _created = UserProfile.objects.get_or_create(user=user)
                profile.primary_role = researcher_role
                profile.save(update_fields=["primary_role", "updated_at"])
                sync_user_role_membership(user, researcher_role)
                changed_users += 1

        self.stdout.write(f"Синхронизировано пользователей: {changed_users}")
        for role_slug, role in roles.items():
            self.stdout.write(f"- {role.name} ({role_slug})")
