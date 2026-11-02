# movies/management/commands/criteries_reassign.py
"""
Переназначение критериев под TMDB-модель.

Правило (источник истины — PatternManager):
  • Genre: удалить все Genre, чьё имя (iexact) отсутствует в GENRE_PATTERNS.
  • Theme: удалить все Theme, чьё имя (iexact) отсутствует в THEME_PATTERNS.
  • Слияние дублей Genre по имени: оставить «канонический» (tmdb_id > 0, если есть),
    перенести связи movies_movie_genres с дублей на канонический, дубли удалить.
  • После удаления/слияния — пересобрать genre_ids у затронутых Movie.

По умолчанию — dry-run (ничего не меняет). С --apply — реально удаляет.
"""

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from movies.models import Genre, Keyword, Movie, Theme
from movies.analyze.pattern_manager import PatternManager


class Command(BaseCommand):
    help = 'Удаляет Genre/Theme, которых нет в PatternManager; сливает дубли Genre по имени; пересобирает genre_ids'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='Реально применить изменения (без флага — dry-run)')
        parser.add_argument('--batch-size', type=int, default=1000,
                            help='Размер батча для through-операций (по умолчанию: 1000)')
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

    def _count_relations(self, table, movie_col, related_col, related_ids):
        if not related_ids:
            return 0
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {related_col} = ANY(%s)",
                [list(related_ids)],
            )
            return cursor.fetchone()[0]

    def _delete_relations_by_related(self, table, movie_col, related_col, related_ids, batch_size):
        if not related_ids:
            return 0
        total = 0
        ids = list(related_ids)
        with connection.cursor() as cursor:
            for i in range(0, len(ids), batch_size):
                batch = ids[i:i + batch_size]
                cursor.execute(
                    f"DELETE FROM {table} WHERE {related_col} = ANY(%s)",
                    [batch],
                )
                total += cursor.rowcount
        return total

    def _reassign_relations(self, table, movie_col, related_col, old_id, new_id):
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE {table}
                SET {related_col} = %s
                WHERE {related_col} = %s
                  AND NOT EXISTS (
                      SELECT 1 FROM {table} t2
                      WHERE t2.{movie_col} = {table}.{movie_col}
                        AND t2.{related_col} = %s
                  )
                """,
                [new_id, old_id, new_id],
            )
            moved = cursor.rowcount
            cursor.execute(f"DELETE FROM {table} WHERE {related_col} = %s", [old_id])
        return moved

    def _affected_movie_ids(self, table, movie_col, related_col, related_ids):
        if not related_ids:
            return set()
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT DISTINCT {movie_col} FROM {table} WHERE {related_col} = ANY(%s)",
                [list(related_ids)],
            )
            return {row[0] for row in cursor.fetchall()}

    def _rebuild_genre_ids(self, movie_ids):
        if not movie_ids:
            return 0
        updated = 0
        qs = Movie.objects.filter(id__in=list(movie_ids)).only('id')
        for m in qs.iterator(chunk_size=500):
            try:
                m.update_materialized_vectors(force=True)
                updated += 1
            except Exception as exc:
                self.stderr.write(f'  ⚠️ update_materialized_vectors для Movie {m.id}: {exc}')
        return updated

    def _rebuild_keyword_ids(self, movie_ids):
        if not movie_ids:
            return 0
        updated = 0
        qs = Movie.objects.filter(id__in=list(movie_ids)).only('id')
        for m in qs.iterator(chunk_size=500):
            try:
                m.update_materialized_vectors(force=True)
                updated += 1
            except Exception as exc:
                self.stderr.write(f'  ⚠️ update_materialized_vectors (keywords) для Movie {m.id}: {exc}')
        return updated

    def _canonical_name_map(self, model, patterns_keys):
        patterns_lower = {k.lower() for k in patterns_keys}
        by_name = {}
        for obj in model.objects.all():
            by_name.setdefault(obj.name.lower(), []).append(obj)

        keep_map = {}
        remove_objects = []
        for name_lower, objs in by_name.items():
            if name_lower not in patterns_lower:
                remove_objects.extend(objs)
                continue
            if len(objs) == 1:
                keep_map[name_lower] = objs[0]
                continue
            def sort_key(o):
                tid = getattr(o, 'tmdb_id', None) or 0
                return (0 if tid > 0 else 1, -tid, o.id)
            objs_sorted = sorted(objs, key=sort_key)
            keep_map[name_lower] = objs_sorted[0]
            # дубли (objs_sorted[1:]) НЕ добавляем в remove_objects:
            # они обрабатываются отдельно через merge_actions (перенос связей + удаление дубля).
        return keep_map, remove_objects

    def handle(self, *args, **options):
        apply_changes = options['apply']
        batch_size = max(1, options['batch_size'])
        verbose = options['verbose']

        pm = PatternManager()
        genre_keys = list(getattr(pm, 'GENRE_PATTERNS', {}).keys())
        theme_keys = list(getattr(pm, 'THEME_PATTERNS', {}).keys())

        self.stdout.write('=' * 70)
        self.stdout.write('criteries_reassign: ' + ('APPLY' if apply_changes else 'DRY-RUN'))
        self.stdout.write('=' * 70)
        self.stdout.write(f'GENRE_PATTERNS: {len(genre_keys)} имён')
        self.stdout.write(f'THEME_PATTERNS: {len(theme_keys)} имён')
        self.stdout.write('')

        g_table, g_movie_col, g_genre_col = self._through_info(Movie.genres, Genre)
        t_table, t_movie_col, t_theme_col = self._through_info(Movie.themes, Theme)

        # ---------- GENRE ----------
        self.stdout.write('--- GENRE ---')
        genre_keep, genre_remove = self._canonical_name_map(Genre, genre_keys)

        merge_actions = []
        for name_lower, canonical in genre_keep.items():
            dupes = list(Genre.objects.filter(name__iexact=canonical.name).exclude(id=canonical.id))
            for d in dupes:
                merge_actions.append((d, canonical))

        remove_ids = [g.id for g in genre_remove]
        if remove_ids:
            rels = self._count_relations(g_table, g_movie_col, g_genre_col, remove_ids)
            affected = self._affected_movie_ids(g_table, g_movie_col, g_genre_col, remove_ids)
            names = sorted({g.name for g in genre_remove})
            self.stdout.write(f'Удалить Genre (нет в GENRE_PATTERNS): {len(remove_ids)} шт., связей={rels}, фильмов={len(affected)}')
            self.stdout.write(f'  Имена: {names}')
        else:
            rels = 0
            affected = set()
            self.stdout.write('Удалять Genre (нет в GENRE_PATTERNS): нечего')

        if merge_actions:
            self.stdout.write(f'Слияние дублей Genre по имени: {len(merge_actions)}')
            for d, c in merge_actions:
                cnt = self._count_relations(g_table, g_movie_col, g_genre_col, [d.id])
                self.stdout.write(f'  "{d.name}" (id={d.id}, tmdb_id={getattr(d,"tmdb_id",None)}) -> "{c.name}" (id={c.id}, tmdb_id={getattr(c,"tmdb_id",None)}), связей={cnt}')

        if apply_changes:
            with transaction.atomic():
                if remove_ids:
                    self._delete_relations_by_related(g_table, g_movie_col, g_genre_col, remove_ids, batch_size)
                    Genre.objects.filter(id__in=remove_ids).delete()
                merged = 0
                for d, c in merge_actions:
                    merged += self._reassign_relations(g_table, g_movie_col, g_genre_col, d.id, c.id)
                    d.delete()
            self.stdout.write(self.style.SUCCESS(f'APPLY Genre: удалено {len(remove_ids)}, слито дублей {len(merge_actions)}, перенесено связей {merged}'))
            if merge_actions:
                affected |= self._affected_movie_ids(g_table, g_movie_col, g_genre_col, [c.id for _, c in merge_actions])
            rebuilt = self._rebuild_genre_ids(affected)
            self.stdout.write(self.style.SUCCESS(f'genre_ids пересобраны для {rebuilt} фильмов'))
        else:
            self.stdout.write(self.style.WARNING('DRY-RUN: Genre не изменялись'))

        # ---------- THEME ----------
        self.stdout.write('')
        self.stdout.write('--- THEME ---')
        theme_keep, theme_remove = self._canonical_name_map(Theme, theme_keys)
        theme_remove_ids = [t.id for t in theme_remove]
        if theme_remove_ids:
            rels_t = self._count_relations(t_table, t_movie_col, t_theme_col, theme_remove_ids)
            names_t = sorted({t.name for t in theme_remove})
            self.stdout.write(f'Удалить Theme (нет в THEME_PATTERNS): {len(theme_remove_ids)}, связей={rels_t}')
            self.stdout.write(f'  Имена: {names_t}')
        else:
            self.stdout.write('Удалять Theme (нет в THEME_PATTERNS): нечего')

        theme_merge = []
        for name_lower, canonical in theme_keep.items():
            dupes = list(Theme.objects.filter(name__iexact=canonical.name).exclude(id=canonical.id))
            for d in dupes:
                theme_merge.append((d, canonical))
        if theme_merge:
            self.stdout.write(f'Слияние дублей Theme по имени: {len(theme_merge)}')
            for d, c in theme_merge:
                cnt = self._count_relations(t_table, t_movie_col, t_theme_col, [d.id])
                self.stdout.write(f'  "{d.name}" (id={d.id}) -> "{c.name}" (id={c.id}), связей={cnt}')

        if apply_changes:
            with transaction.atomic():
                if theme_remove_ids:
                    self._delete_relations_by_related(t_table, t_movie_col, t_theme_col, theme_remove_ids, batch_size)
                    Theme.objects.filter(id__in=theme_remove_ids).delete()
                merged_t = 0
                for d, c in theme_merge:
                    merged_t += self._reassign_relations(t_table, t_movie_col, t_theme_col, d.id, c.id)
                    d.delete()
            self.stdout.write(self.style.SUCCESS(f'APPLY Theme: удалено {len(theme_remove_ids)}, слито дублей {len(theme_merge)}, перенесено связей {merged_t}'))
        else:
            self.stdout.write(self.style.WARNING('DRY-RUN: Theme не изменялись'))

        # ---------- KEYWORD (только свои: tmdb_id <= 0; TMDB tmdb_id > 0 — удалить) ----------
        self.stdout.write('')
        self.stdout.write('--- KEYWORD ---')
        kw_table, kw_movie_col, kw_kw_col = self._through_info(Movie.keywords, Keyword)

        tmdb_kw_qs = Keyword.objects.filter(tmdb_id__gt=0)
        own_kw_qs = Keyword.objects.filter(tmdb_id__lte=0)
        tmdb_ids = list(tmdb_kw_qs.values_list('id', flat=True))
        own_count = own_kw_qs.count()
        self.stdout.write(f'TMDB-ключевые (tmdb_id>0) к удалению: {len(tmdb_ids)}')
        self.stdout.write(f'Свои ключевые (tmdb_id<=0) останутся: {own_count}')

        if tmdb_ids:
            kw_rels = self._count_relations(kw_table, kw_movie_col, kw_kw_col, tmdb_ids)
            kw_affected = self._affected_movie_ids(kw_table, kw_movie_col, kw_kw_col, tmdb_ids)
            # также фильмы, у которых keyword_ids содержит TMDB keyword_ids (tmdb_id, не pk!) —
            # это те, у кого мог быть рассинхрон M2M и materialized. Возьмём объединение.
            self.stdout.write(f'  Связей movies_movie_keywords на удаление: {kw_rels}, фильмов (M2M): {len(kw_affected)}')
        else:
            kw_rels = 0
            kw_affected = set()
            self.stdout.write('  Удалять TMDB-ключевые: нечего')

        if apply_changes:
            with transaction.atomic():
                if tmdb_ids:
                    self._delete_relations_by_related(kw_table, kw_movie_col, kw_kw_col, tmdb_ids, batch_size)
                    Keyword.objects.filter(id__in=tmdb_ids).delete()
            self.stdout.write(self.style.SUCCESS(f'APPLY Keyword: удалено {len(tmdb_ids)} TMDB-ключевых, удалено связей {kw_rels}'))

            # Пересобрать keyword_ids у затронутых фильмов + у всех, где в keyword_ids могли
            # остаться tmdb_id удалённых (на случай рассинхрона).
            rebuilt_kw = self._rebuild_keyword_ids(kw_affected)
            self.stdout.write(self.style.SUCCESS(f'keyword_ids пересобраны для {rebuilt_kw} фильмов'))
        else:
            self.stdout.write(self.style.WARNING('DRY-RUN: Keyword не изменялись'))

        self.stdout.write('')
        self.stdout.write('=' * 70)
        if apply_changes:
            self.stdout.write(self.style.SUCCESS('ГОТОВО (изменения применены)'))
        else:
            self.stdout.write(self.style.WARNING('ГОТОВО (dry-run, БД не изменялась). Запустите с --apply для применения.'))