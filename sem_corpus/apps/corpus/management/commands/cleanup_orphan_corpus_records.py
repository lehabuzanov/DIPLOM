from django.core.management.base import BaseCommand

from sem_corpus.apps.corpus.services import cleanup_orphan_corpus_records


class Command(BaseCommand):
    help = "Remove corpus reference records that are no longer linked to articles."

    def handle(self, *args, **options):
        deleted = cleanup_orphan_corpus_records()
        for label, count in deleted.items():
            self.stdout.write(f"{label}: {count}")
        self.stdout.write(self.style.SUCCESS("Orphan corpus records cleanup completed."))
