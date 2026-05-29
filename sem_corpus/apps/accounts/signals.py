from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from sem_corpus.apps.accounts.access import (
    ROLE_ADMINISTRATOR,
    assign_default_role,
    assign_role,
    sync_user_role_membership,
)
from sem_corpus.apps.accounts.models import UserProfile


User = get_user_model()


@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)
        if instance.is_superuser:
            assign_role(instance, ROLE_ADMINISTRATOR)
        else:
            assign_default_role(instance)


@receiver(post_save, sender=UserProfile)
def sync_profile_role(sender, instance, **kwargs):
    sync_user_role_membership(instance.user, instance.primary_role)
