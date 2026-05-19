from django.core.management.base import BaseCommand

from sem_corpus.apps.corpus.geo import assign_affiliation_geography, seed_city_locations
from sem_corpus.apps.corpus.models import Affiliation


class Command(BaseCommand):
    help = "Extract and refresh city coordinates for author affiliations."

    def add_arguments(self, parser):
        parser.add_argument(
            "--geocode",
            action="store_true",
            help="Use Nominatim for unresolved affiliations. This requires internet access and marks results for review.",
        )

    def handle(self, *args, **options):
        seed_city_locations()
        resolved = 0
        unresolved = 0
        use_geocoder = options["geocode"]

        for affiliation in Affiliation.objects.order_by("name"):
            if assign_affiliation_geography(affiliation, use_geocoder=use_geocoder):
                resolved += 1
            else:
                unresolved += 1

        self.stdout.write(self.style.SUCCESS(f"Resolved affiliations: {resolved}"))
        self.stdout.write(f"Unresolved affiliations: {unresolved}")
        if unresolved:
            self.stdout.write(
                "Unresolved rows stay in the database with geography_source='unresolved' "
                "so an editor can review them or rerun the command with --geocode."
            )
