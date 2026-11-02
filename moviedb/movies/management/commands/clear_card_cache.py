from django.core.management.base import BaseCommand
from movies.models import MovieCardCache


class Command(BaseCommand):
    help = 'Clear all Movie card caches'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force deletion without confirmation',
        )

    def handle(self, *args, **options):
        if not options['force']:
            self.stdout.write(
                self.style.WARNING(
                    'This will delete all cached Movie cards. '
                    'Type "yes" to continue: '
                )
            )
            if input().lower() != 'yes':
                self.stdout.write(self.style.SUCCESS('Operation cancelled'))
                return

        count = MovieCardCache.objects.count()
        MovieCardCache.objects.all().delete()

        self.stdout.write(
            self.style.SUCCESS(f'Successfully deleted {count} Movie cards')
        )