# movies/management/commands/convert_keyword_ids_pk_to_tmdb.py
"""
Конвертирует Movie.keyword_ids из pk (Keyword.id) в tmdb_id (Keyword.tmdb_id).

Нужно, потому что analyze_movie_criteria_fast --keywords пишет pk,
а update_materialized_vectors / sync_keyword_m2m ожидают tmdb_id.

Одноразовая миграция данных. По умолчанию — dry-run. С --apply — обновляет.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from movies.models import Keyword, Movie


class Command(BaseCommand):
    help = 'Конвертирует Movie.keyword_ids: pk (Keyword.id) -> tmdb_id (Keyword.tmdb_id)'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='Реально обновить (без флага — dry-run)')
        parser.add_argument('--batch-size', type=int, default=2000,
                            help='Размер батча (по умолчанию: 2000)')

    def handle(self, *args, **options):
        apply_changes = options['apply']
        batch_size = max(1, options['batch_size'])

        self.stdout.write('=' * 70)
        self.stdout.write('convert_keyword_ids_pk_to_tmdb: ' + ('APPLY' if apply_changes else 'DRY-RUN'))
        self.stdout.write('=' * 70)

        # 1. Собираем все значения из keyword_ids (предположительно pk)
        all_ids = set()
        qs = Movie.objects.exclude(keyword_ids=[]).only('id', 'keyword_ids')
        total_movies = 0
        for m in qs.iterator(chunk_size=batch_size):
            ids = list(m.keyword_ids or [])
            if not ids:
                continue
            all_ids.update(ids)
            total_movies += 1

        self.stdout.write(f'Фильмов с непустым keyword_ids: {total_movies}')
        self.stdout.write(f'Уникальных значений в keyword_ids: {len(all_ids)}')

        if not all_ids:
            self.stdout.write(self.style.WARNING('Нечего конвертировать'))
            return

        # 2. Строим карту pk -> tmdb_id
        pk_to_tmdb = {}
        id_list = list(all_ids)
        for i in range(0, len(id_list), batch_size):
            batch = id_list[i:i + batch_size]
            for pk, tid in Keyword.objects.filter(id__in=batch).values_list('id', 'tmdb_id'):
                pk_to_tmdb[pk] = tid

        self.stdout.write(f'Найдено Keyword по pk: {len(pk_to_tmdb)} (из {len(all_ids)})')
        missing = all_ids - set(pk_to_tmdb.keys())
        if missing:
            self.stdout.write(self.style.WARNING(f'  pk без Keyword: {len(missing)} (пропущены)'))

        # 3. Считаем, сколько значений изменится
        changed_movies = 0
        changed_values = 0
        sample_changes = []
        for m in qs.iterator(chunk_size=batch_size):
            old_ids = list(m.keyword_ids or [])
            if not old_ids:
                continue
            new_ids = []
            local_changed = False
            for v in old_ids:
                tid = pk_to_tmdb.get(v)
                if tid is None:
                    new_ids.append(v)
                else:
                    new_ids.append(tid)
                    if tid != v:
                        local_changed = True
                        changed_values += 1
            if local_changed:
                changed_movies += 1
                if len(sample_changes) < 5:
                    sample_changes.append((m.id, old_ids[:5], new_ids[:5]))

        self.stdout.write(f'Фильмов с изменениями: {changed_movies}')
        self.stdout.write(f'Значений к замене: {changed_values}')
        if sample_changes:
            self.stdout.write('Примеры (movie_id, old[:5], new[:5]):')
            for s in sample_changes:
                self.stdout.write(f'  {s}')

        if not apply_changes:
            self.stdout.write(self.style.WARNING('DRY-RUN: ничего не изменено. Запустите с --apply.'))
            return

        # 4. Применяем: обновляем keyword_ids батчами
        updated = 0
        for m in qs.iterator(chunk_size=batch_size):
            old_ids = list(m.keyword_ids or [])
            if not old_ids:
                continue
            new_ids = []
            local_changed = False
            for v in old_ids:
                tid = pk_to_tmdb.get(v)
                if tid is None:
                    new_ids.append(v)
                else:
                    new_ids.append(tid)
                    if tid != v:
                        local_changed = True
            if local_changed:
                Movie.objects.filter(id=m.id).update(keyword_ids=new_ids)
                updated += 1

        self.stdout.write(self.style.SUCCESS(f'APPLY: обновлено фильмов: {updated}'))