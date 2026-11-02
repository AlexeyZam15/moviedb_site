# movies/management/commands/sync_keyword_m2m.py
"""
Синхронизация materialized keyword_ids (ArrayField, tmdb_id) -> M2M movies_movie_keywords (Keyword.id).

Нужно, потому что analyze_movie_criteria_fast --keywords пишет только в keyword_ids,
а UI (Movie.keywords.all) читает M2M.

По умолчанию — dry-run. С --apply — создаёт через-записи.
"""

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from movies.models import Keyword, Movie


class Command(BaseCommand):
    help = 'Синхронизирует Movie.keyword_ids (tmdb_id) -> M2M movies_movie_keywords'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='Реально создать через-записи (без флага — dry-run)')
        parser.add_argument('--batch-size', type=int, default=1000,
                            help='Размер батча (по умолчанию: 1000)')
        parser.add_argument('--verbose', action='store_true', help='Подробный вывод')

    def _through_info(self, m2m_manager, related_model):
        through = m2m_manager.through
        table = through._meta.db_table
        movie_col = next(
            f.column for f in through._meta.fields
            if f.remote_field and f.remote_field.model is Movie
        )
        related_col = next(
            f.column for f in through._meta.fields
            if f.remote_field and f.remote_field.model is related_model
        )
        return table, movie_col, related_col

    def handle(self, *args, **options):
        apply_changes = options['apply']
        batch_size = max(1, options['batch_size'])
        verbose = options['verbose']

        self.stdout.write('=' * 70)
        self.stdout.write('sync_keyword_m2m: ' + ('APPLY' if apply_changes else 'DRY-RUN'))
        self.stdout.write('=' * 70)

        table, movie_col, kw_col = self._through_info(Movie.keywords, Keyword)
        self.stdout.write(f'through table: {table} ({movie_col}, {kw_col})')

        # 1. Собираем все tmdb_id, которые встречаются в keyword_ids
        all_tmdb_ids = set()
        movie_keyword_ids = {}  # movie_id -> list(tmdb_id)
        qs = Movie.objects.exclude(keyword_ids=[]).only('id', 'keyword_ids')
        total_movies = 0
        for m in qs.iterator(chunk_size=2000):
            ids = list(m.keyword_ids or [])
            if not ids:
                continue
            movie_keyword_ids[m.id] = ids
            all_tmdb_ids.update(ids)
            total_movies += 1

        self.stdout.write(f'Фильмов с непустым keyword_ids: {total_movies}')
        self.stdout.write(f'Уникальных tmdb_id в keyword_ids: {len(all_tmdb_ids)}')

        if not all_tmdb_ids:
            self.stdout.write(self.style.WARNING('Нечего синхронизировать (keyword_ids пусты)'))
            return

        # 2. Карта tmdb_id -> Keyword.id (pk)
        tmdb_to_pk = {}
        tmdb_list = list(all_tmdb_ids)
        for i in range(0, len(tmdb_list), batch_size):
            batch = tmdb_list[i:i + batch_size]
            for tmdb_id, pk in Keyword.objects.filter(tmdb_id__in=batch).values_list('tmdb_id', 'id'):
                tmdb_to_pk[tmdb_id] = pk
        self.stdout.write(f'Найдено Keyword по tmdb_id: {len(tmdb_to_pk)} (из {len(all_tmdb_ids)})')
        missing = all_tmdb_ids - set(tmdb_to_pk.keys())
        if missing:
            self.stdout.write(self.style.WARNING(f'  tmdb_id без Keyword: {len(missing)} (пропущены)'))

        # 3. Считаем связи
        total_relations = 0
        for mid, ids in movie_keyword_ids.items():
            for tid in ids:
                if tid in tmdb_to_pk:
                    total_relations += 1
        self.stdout.write(f'Связей к созданию (movie_id, keyword_id): {total_relations}')

        if not apply_changes:
            self.stdout.write(self.style.WARNING('DRY-RUN: ничего не создано. Запустите с --apply.'))
            return

        # 4. Создаём через-записи батчами
        created = 0
        errors = 0
        batch = []
        with transaction.atomic():
            for mid, ids in movie_keyword_ids.items():
                for tid in ids:
                    pk = tmdb_to_pk.get(tid)
                    if pk is None:
                        continue
                    batch.append((mid, pk))
                    if len(batch) >= batch_size:
                        created += self._flush(batch, table, movie_col, kw_col, verbose)
                        batch = []
            if batch:
                created += self._flush(batch, table, movie_col, kw_col, verbose)

        self.stdout.write(self.style.SUCCESS(f'APPLY: создано (или уже было) связей: {created}'))

    def _flush(self, batch, table, movie_col, kw_col, verbose):
        with connection.cursor() as cursor:
            placeholders = ','.join(['(%s,%s)'] * len(batch))
            flat = []
            for mid, pk in batch:
                flat.append(mid)
                flat.append(pk)
            cursor.execute(
                f"INSERT INTO {table} ({movie_col}, {kw_col}) VALUES {placeholders} "
                f"ON CONFLICT DO NOTHING",
                flat,
            )
            return cursor.rowcount