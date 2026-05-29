from __future__ import annotations

from dataclasses import dataclass

from django.apps import apps
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from sem_corpus.apps.accounts.models import Role, UserProfile


ROLE_RESEARCHER = "researcher"
ROLE_EDITOR = "editor"
ROLE_ADMINISTRATOR = "administrator"


@dataclass(frozen=True)
class RoleDefinition:
    slug: str
    name: str
    group_name: str
    description: str
    can_manage_users: bool = False
    can_edit_content: bool = False
    can_run_imports: bool = False
    can_save_queries: bool = False


ROLE_DEFINITIONS = {
    ROLE_RESEARCHER: RoleDefinition(
        slug=ROLE_RESEARCHER,
        name="Исследователь",
        group_name="Исследователь",
        description=(
            "Работает с поиском, личными сохраненными запросами, подкорпусами, "
            "пометками и аналитикой без доступа к редакторской части."
        ),
        can_save_queries=True,
    ),
    ROLE_EDITOR: RoleDefinition(
        slug=ROLE_EDITOR,
        name="Редактор",
        group_name="Редактор корпуса",
        description=(
            "Имеет права исследователя, может загружать статьи и редактировать "
            "данные корпуса через административный интерфейс."
        ),
        can_edit_content=True,
        can_run_imports=True,
        can_save_queries=True,
    ),
    ROLE_ADMINISTRATOR: RoleDefinition(
        slug=ROLE_ADMINISTRATOR,
        name="Администратор",
        group_name="Администратор корпуса",
        description=(
            "Управляет пользователями, ролями, справочниками и всеми данными корпуса."
        ),
        can_manage_users=True,
        can_edit_content=True,
        can_run_imports=True,
        can_save_queries=True,
    ),
}


EDITOR_CORPUS_MODELS = [
    "Journal",
    "Issue",
    "Section",
    "Affiliation",
    "CityLocation",
    "Author",
    "Keyword",
    "Article",
    "ArticleAuthor",
    "ArticleFile",
    "ArticleText",
]

EDITOR_READONLY_CORPUS_MODELS = [
    "ArticleHighlight",
    "Lemma",
    "ArticleToken",
    "SavedQuery",
    "SavedSubcorpus",
    "SavedSubcorpusArticle",
    "SearchHistory",
]

ADMIN_APPS = ["accounts", "corpus"]
ADMIN_AUTH_MODELS = ["User", "Group"]
ACCESS_GROUP_NAMES = [definition.group_name for definition in ROLE_DEFINITIONS.values()]


def _model_permissions(app_label: str, model_name: str, actions: list[str]) -> list[Permission]:
    model = apps.get_model(app_label, model_name)
    content_type = ContentType.objects.get_for_model(model)
    codenames = [f"{action}_{model._meta.model_name}" for action in actions]
    return list(Permission.objects.filter(content_type=content_type, codename__in=codenames))


def _permissions_for_app(app_label: str) -> list[Permission]:
    return list(Permission.objects.filter(content_type__app_label=app_label))


def _editor_permissions() -> list[Permission]:
    permissions: list[Permission] = []
    for model_name in EDITOR_CORPUS_MODELS:
        permissions.extend(_model_permissions("corpus", model_name, ["add", "change", "delete", "view"]))
    for model_name in EDITOR_READONLY_CORPUS_MODELS:
        permissions.extend(_model_permissions("corpus", model_name, ["view"]))
    return permissions


def _administrator_permissions() -> list[Permission]:
    permissions: list[Permission] = []
    for app_label in ADMIN_APPS:
        permissions.extend(_permissions_for_app(app_label))
    for model_name in ADMIN_AUTH_MODELS:
        permissions.extend(_model_permissions("auth", model_name, ["add", "change", "delete", "view"]))
    return permissions


@transaction.atomic
def ensure_access_control() -> dict[str, Role]:
    roles: dict[str, Role] = {}
    for slug, definition in ROLE_DEFINITIONS.items():
        role, _created = Role.objects.update_or_create(
            slug=slug,
            defaults={
                "name": definition.name,
                "description": definition.description,
                "can_manage_users": definition.can_manage_users,
                "can_edit_content": definition.can_edit_content,
                "can_run_imports": definition.can_run_imports,
                "can_save_queries": definition.can_save_queries,
            },
        )
        group, _created = Group.objects.get_or_create(name=definition.group_name)
        if slug == ROLE_EDITOR:
            group.permissions.set(_editor_permissions())
        elif slug == ROLE_ADMINISTRATOR:
            group.permissions.set(_administrator_permissions())
        else:
            group.permissions.clear()
        roles[slug] = role
    return roles


def get_default_researcher_role() -> Role:
    role = Role.objects.filter(slug=ROLE_RESEARCHER).first()
    if role:
        return role
    return ensure_access_control()[ROLE_RESEARCHER]


def sync_user_role_membership(user, role: Role | None) -> None:
    if not user or not user.pk:
        return

    access_groups = Group.objects.filter(name__in=ACCESS_GROUP_NAMES)
    if access_groups.exists():
        user.groups.remove(*access_groups)

    role_slug = getattr(role, "slug", "")
    definition = ROLE_DEFINITIONS.get(role_slug)
    if definition:
        group, _created = Group.objects.get_or_create(name=definition.group_name)
        user.groups.add(group)

    should_be_staff = user.is_staff
    if role_slug in {ROLE_EDITOR, ROLE_ADMINISTRATOR}:
        should_be_staff = True
    elif role_slug == ROLE_RESEARCHER and not user.is_superuser:
        should_be_staff = False

    if user.is_staff != should_be_staff:
        user.is_staff = should_be_staff
        user.save(update_fields=["is_staff"])


def assign_role(user, role_slug: str) -> Role:
    roles = ensure_access_control()
    role = roles[role_slug]
    profile, _created = UserProfile.objects.get_or_create(user=user)
    profile.primary_role = role
    profile.save(update_fields=["primary_role", "updated_at"])
    sync_user_role_membership(user, role)
    return role


def assign_default_role(user) -> Role:
    return assign_role(user, ROLE_RESEARCHER)
