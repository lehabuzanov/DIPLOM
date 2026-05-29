from __future__ import annotations


def repair_legacy_mojibake(value: str | None) -> str:
    if not value:
        return ""
    try:
        repaired = value.encode("cp1251").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    return repaired if repaired != value else value


def get_primary_role(user):
    if not user or not user.is_authenticated:
        return None
    profile = getattr(user, "profile", None)
    return getattr(profile, "primary_role", None)


def user_can_save_queries(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_staff or user.is_superuser:
        return True
    role = get_primary_role(user)
    return bool(role and role.can_save_queries)


def user_can_use_personal_tools(user) -> bool:
    return user_can_save_queries(user)


def user_can_edit_corpus(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_staff or user.is_superuser:
        return True
    role = get_primary_role(user)
    return bool(role and role.can_edit_content)


def user_can_run_imports(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_staff or user.is_superuser:
        return True
    role = get_primary_role(user)
    return bool(role and role.can_run_imports)


def user_can_manage_users(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    role = get_primary_role(user)
    return bool(role and role.can_manage_users)
