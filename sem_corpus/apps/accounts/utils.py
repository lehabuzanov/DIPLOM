from __future__ import annotations


def get_primary_role(user):
    if not user or not user.is_authenticated:
        return None
    profile = getattr(user, "profile", None)
    return getattr(profile, "primary_role", None)


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
