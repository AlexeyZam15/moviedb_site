# movies/management/commands/fill_tv_keywords_from_summary.py
"""Заполняет Movie.keyword_ids (tmdb_id) для TV по совпадениям Keyword.name в summary/tagline."""

from django.core.management.base import BaseCommand
from django.db import transaction

from movies.models import Movie, Keyword


class Command(BaseCommand):
    help = 'Заполняет keyword_ids для TV по совпадениям Keyword.name в summary/tagline'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='Реально обновить (без флага — dry-run)')
        parser.add_argument('--only-empty', action='store_true', default=True,
                            help='Только TV с пустым keyword_ids (по умолчанию: да)')

    def handle(self, *args, **options):
        apply_changes = options['apply']

        self.stdout.write('=' * 70)
        self.stdout.write('fill_tv_keywords_from_summary: ' + ('APPLY' if apply_changes else 'DRY-RUN'))
        self.stdout.write('=' * 70)

        keywords = list(Keyword.objects.only('tmdb_id', 'name'))
        kw_by_name = {}
        for kw in keywords:
            name = (kw.name or '').strip().lower()
            if len(name) < 3:
                continue
            kw_by_name.setdefault(name, []).append(kw.tmdb_id)

        qs = Movie.objects.filter(media_type='tv')
        if options.get('only_empty'):
            qs = qs.filter(keyword_ids=[])

        total = 0
        updated = 0
        to_update = []

        for m in qs.iterator(chunk_size=500):
            total += 1
            text = ' '.join(filter(None, [m.summary or '', m.tagline or ''])).lower()
            if not text:
                continue
            found = set()
            for name, tmdb_ids in kw_by_name.items():
                if name in text:
                    found.update(tmdb_ids)
            if not found:
                continue
            new_ids = sorted(set((m.keyword_ids or [])) | found)
            if new_ids != sorted(set(m.keyword_ids or [])):
                m.keyword_ids = new_ids
                to_update.append(m)
                updated += 1
                if updated <= 10:
                    self.stdout.write(f'  {m.tmdb_id} {m.name}: +{len(found)} kw')

        self.stdout.write(f'TV проверено: {total}, к обновлению: {updated}')

        if not apply_changes:
            self.stdout.write('DRY-RUN: запустите с --apply')
            return

        for m in to_update:
            Movie.objects.filter(id=m.id).update(keyword_ids=m.keyword_ids)

        self.stdout.write(self.style.SUCCESS(f'APPLY: обновлено: {len(to_update)}'))
