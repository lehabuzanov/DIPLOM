from django.conf import settings

from sem_corpus.apps.accounts.utils import user_can_edit_corpus


def site_context(request):
    return {
        "site_title": settings.CORPUS_TITLE,
        "site_short_title": settings.CORPUS_SHORT_TITLE,
        "university_name": settings.UNIVERSITY_NAME,
        "journal_base_url": settings.JOURNAL_BASE_URL,
        "can_edit_corpus": user_can_edit_corpus(request.user),
    }
