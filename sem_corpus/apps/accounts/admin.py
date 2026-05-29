from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from sem_corpus.apps.accounts.models import Role, UserActivity, UserProfile


User = get_user_model()


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    extra = 0
    fields = ("institution", "position", "preferred_language", "primary_role")


try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    inlines = [UserProfileInline]
    list_display = ("username", "email", "first_name", "last_name", "is_staff", "is_active", "display_role")
    list_select_related = ("profile__primary_role",)

    @admin.display(description="роль")
    def display_role(self, obj):
        profile = getattr(obj, "profile", None)
        return getattr(profile, "primary_role", None) or "не назначена"


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "can_manage_users",
        "can_edit_content",
        "can_run_imports",
        "can_save_queries",
    )
    search_fields = ("name", "slug")
    readonly_fields = ("created_at", "updated_at")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "institution", "position", "primary_role")
    list_filter = ("primary_role",)
    search_fields = ("user__username", "user__first_name", "user__last_name", "institution")
    list_select_related = ("user", "primary_role")


@admin.register(UserActivity)
class UserActivityAdmin(admin.ModelAdmin):
    list_display = ("user", "activity_type", "title", "created_at")
    list_filter = ("activity_type", "created_at")
    search_fields = ("user__username", "title")
