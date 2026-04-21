from django.contrib import admin

from sem_corpus.apps.accounts.models import Role, UserActivity, UserProfile


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "can_manage_users", "can_edit_content", "can_run_imports")
    search_fields = ("name", "slug")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "institution", "primary_role")
    search_fields = ("user__username", "user__first_name", "user__last_name", "institution")
    list_select_related = ("user", "primary_role")


@admin.register(UserActivity)
class UserActivityAdmin(admin.ModelAdmin):
    list_display = ("user", "activity_type", "title", "created_at")
    list_filter = ("activity_type", "created_at")
    search_fields = ("user__username", "title")
