# movies/management/commands/analyze_game_criteria_fas_src/saving.py

import sys
import time
from typing import Dict, List

from django.db import connection, transaction


class SavingMixin:
    """Сохранение результатов в БД и подтверждение."""

    def _confirm_save(self, count: int, results_count: int, elements_count: int) -> bool:
        """Запрашивает подтверждение сохранения с принудительной синхронизацией"""

        sys.stderr.write(f"\n💾 Готово к сохранению в БД: {count} фильмов\n")
        sys.stderr.write(f"   🎯 Фильмов с новыми критериями: {results_count}\n")
        sys.stderr.write(f"   📈 Всего элементов: {elements_count}\n")
        sys.stderr.flush()

        if self.output_path:
            sys.stderr.write(f"   📄 Результаты сохранены в: {self.output_path}\n")
            sys.stderr.flush()

        if self.auto_save:
            sys.stderr.write("\n✅ Авто-сохранение включено\n")
            sys.stderr.flush()
            return True

        sys.stderr.write("\n⚠️ Сохранить результаты в БД? (y/N): ")
        sys.stderr.flush()

        try:
            import select
            if select.select([sys.stdin], [], [], 0)[0]:
                sys.stdin.read()
        except Exception:
            pass

        try:
            answer = sys.stdin.readline().strip().lower()
        except (EOFError, KeyboardInterrupt, OSError):
            sys.stderr.write("\n")
            sys.stderr.flush()
            return False

        if answer in ['y', 'yes', 'да', 'д', '1']:
            sys.stderr.write("\n✅ Сохраняем...\n")
            sys.stderr.flush()
            return True

        sys.stderr.write("\n⏭️ Сохранение отменено\n")
        sys.stderr.flush()
        return False

    def _bulk_save_results(self, to_save: List[Dict]):
        """Максимально быстрое сохранение для PostgreSQL с индикацией прогресса"""
        if not to_save:
            return

        total_movies = len(to_save)
        sys.stderr.write(f"\n💾 Сохранение {total_movies} фильмов в БД...\n")
        sys.stderr.flush()

        try:
            first = to_save[0]
            sys.stderr.write(f"   🔎 [DEBUG] to_save[0] keys: {list(first.keys())}\n")
            found_dbg = first.get('found', {})
            sys.stderr.write(
                f"   🔎 [DEBUG] found type: {type(found_dbg).__name__}, keys: {list(found_dbg.keys()) if isinstance(found_dbg, dict) else found_dbg}\n")
            if isinstance(found_dbg, dict):
                for k, v in found_dbg.items():
                    if v:
                        sys.stderr.write(f"   🔎 [DEBUG] found['{k}'][0] = {repr(v[0])[:200]}\n")
            sys.stderr.flush()
        except Exception as e:
            sys.stderr.write(f"   ⚠️ [DEBUG] не удалось вывести структуру: {e}\n")
            sys.stderr.flush()

        save_start = time.time()

        from movies.models import Movie, Genre, Theme

        movie_table = Movie._meta.db_table  # 'movies_movie'

        def _through_info(m2m_manager, related_model):
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

        movies_genres_table, movies_genres_movie_col, movies_genres_genre_col = _through_info(
            Movie.genres, Genre
        )
        movies_themes_table, movies_themes_movie_col, movies_themes_theme_col = _through_info(
            Movie.themes, Theme
        )

        genre_relations = []
        theme_relations = []
        keyword_relations = []

        for item in to_save:
            game_id = item['id']
            found = item.get('found', {}) or {}
            if not isinstance(found, dict):
                continue

            for criteria_type, items in found.items():
                if not items:
                    continue
                for crit in items:
                    if isinstance(crit, dict):
                        crit_id = crit.get('id')
                    else:
                        crit_id = crit
                    if crit_id is None:
                        continue

                    if criteria_type == 'genres':
                        genre_relations.append((game_id, crit_id))
                    elif criteria_type == 'themes':
                        theme_relations.append((game_id, crit_id))
                    elif criteria_type == 'keywords':
                        keyword_relations.append((game_id, crit_id))
                    # perspectives / game_modes в новой модели отсутствуют — пропускаем

        total_relations = (len(genre_relations) + len(theme_relations) + len(keyword_relations))
        sys.stderr.write(f"   📊 Связей для сохранения: {total_relations} "
                         f"(genres={len(genre_relations)}, themes={len(theme_relations)}, "
                         f"keywords={len(keyword_relations)})\n")
        sys.stderr.flush()

        def bulk_insert(relations, table_name, movie_col, related_col, type_name):
            if not relations:
                return 0

            with connection.cursor() as cursor:
                game_ids = list(set(r[0] for r in relations))
                crit_ids = list(set(r[1] for r in relations))

                cursor.execute(
                    f"""
                    SELECT {movie_col}, {related_col} FROM {table_name}
                    WHERE {movie_col} = ANY(%s) AND {related_col} = ANY(%s)
                    """,
                    [game_ids, crit_ids],
                )
                existing = set(cursor.fetchall())

                new_relations = [(g, c) for g, c in relations if (g, c) not in existing]

                if not new_relations:
                    return 0

                import io
                data_buffer = io.StringIO()
                for game_id, crit_id in new_relations:
                    data_buffer.write(f"{game_id}\t{crit_id}\n")
                data_buffer.seek(0)

                cursor.copy_from(data_buffer, table_name,
                                 columns=(movie_col, related_col))

                return len(new_relations)

        def bulk_update_keywords(relations):
            if not relations:
                return 0

            from collections import defaultdict
            new_by_game = defaultdict(set)
            for game_id, kw_id in relations:
                new_by_game[game_id].add(kw_id)

            game_ids = list(new_by_game.keys())

            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT id, keyword_ids FROM {movie_table} WHERE id = ANY(%s)",
                    [game_ids]
                )
                existing_map = {}
                for gid, kw_ids in cursor.fetchall():
                    existing_map[gid] = set(kw_ids or [])

            from movies.models import Movie as MovieModel
            updated_rows = 0
            for gid, new_set in new_by_game.items():
                old_set = existing_map.get(gid, set())
                merged = old_set | new_set
                if merged != old_set:
                    MovieModel.objects.filter(id=gid).update(
                        keyword_ids=sorted(merged)
                    )
                    updated_rows += 1

            return updated_rows
        with transaction.atomic():
            sys.stderr.write(f"   📖 Сохранение жанров... ")
            sys.stderr.flush()
            start = time.time()
            genres_added = bulk_insert(
                genre_relations, movies_genres_table,
                movies_genres_movie_col, movies_genres_genre_col, 'Жанры'
            )
            sys.stderr.write(f"{genres_added} связей за {time.time() - start:.1f}с\n")
            sys.stderr.flush()

            sys.stderr.write(f"   📖 Сохранение тем... ")
            sys.stderr.flush()
            start = time.time()
            themes_added = bulk_insert(
                theme_relations, movies_themes_table,
                movies_themes_movie_col, movies_themes_theme_col, 'Темы'
            )
            sys.stderr.write(f"{themes_added} связей за {time.time() - start:.1f}с\n")
            sys.stderr.flush()

            sys.stderr.write(f"   📖 Сохранение ключевых слов (ArrayField)... ")
            sys.stderr.flush()
            start = time.time()
            keywords_updated = bulk_update_keywords(keyword_relations)
            sys.stderr.write(f"{keywords_updated} фильмов обновлено за {time.time() - start:.1f}с\n")
            sys.stderr.flush()

        save_time = time.time() - save_start
        total_added = genres_added + themes_added

        sys.stderr.write(f"\n   ✅ Сохранено за {save_time:.1f}с:\n")
        sys.stderr.write(f"      Жанры: {genres_added} связей\n")
        sys.stderr.write(f"      Темы: {themes_added} связей\n")
        sys.stderr.write(f"      Ключевые слова: {keywords_updated} фильмов обновлено\n")
        sys.stderr.write(f"      Всего (M2M): {total_added} связей\n")
        if save_time > 0 and total_added > 0:
            sys.stderr.write(f"      ⚡ Скорость: {total_added / save_time:.0f} связей/сек\n")
        sys.stderr.flush()
