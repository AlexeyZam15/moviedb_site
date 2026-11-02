# movies/similarity_parts/data_mixin.py
"""Data access methods for moviesimilarity."""

from ..models import Movie
from .utils import timeit


class DataMixin:
    """Загрузка и кэширование данных, подготовка source и кандидатов."""

    # ------------------------------------------------------------------
    # Кэширование данных фильма
    # ------------------------------------------------------------------
    def _get_cached_movie_data(self, obj):
        """Получает или кэширует данные фильма (Movie)."""
        cache_key = f"movie_{obj.id}"

        if cache_key not in self._movie_data_cache:
            self._movie_data_cache[cache_key] = {
                'genres': self._get_genres(obj),
                'keywords': self._get_keywords(obj),
                'themes': self._get_themes(obj),
                'developers': self._get_developers(obj),
                'series_id': self._get_series_id(obj),
            }

        return self._movie_data_cache[cache_key]

    def _get_genres(self, obj):
        """Локальные id жанров через связь."""
        if hasattr(obj, 'genres'):
            if not hasattr(obj, '_cached_genre_ids'):
                obj._cached_genre_ids = set(obj.genres.values_list('id', flat=True))
            return obj._cached_genre_ids
        return set()

    def _get_keywords(self, obj):
        """Локальные id ключевых слов через связь (вариант C), НЕ tmdb_id."""
        if hasattr(obj, 'keywords') and hasattr(obj.keywords, 'all'):
            if not hasattr(obj, '_cached_keyword_ids'):
                obj._cached_keyword_ids = set(obj.keywords.values_list('id', flat=True))
            return obj._cached_keyword_ids
        return set()

    def _get_themes(self, obj):
        """Локальные id тем через связь."""
        if hasattr(obj, 'themes'):
            if not hasattr(obj, '_cached_theme_ids'):
                obj._cached_theme_ids = set(obj.themes.values_list('id', flat=True))
            return obj._cached_theme_ids
        return set()

    def _get_developers(self, obj):
        """production_companies (локальные id)."""
        if hasattr(obj, 'production_companies'):
            if not hasattr(obj, '_cached_developer_ids'):
                obj._cached_developer_ids = set(
                    obj.production_companies.values_list('id', flat=True)
                )
            return obj._cached_developer_ids
        return set()

    def _get_series_id(self, obj):
        return getattr(obj, 'series_id', None)

    # ------------------------------------------------------------------
    # Подготовка source
    # ------------------------------------------------------------------
    def _prepare_source_data(self, source_movie, override_criteria=None):
        """Подготовка данных исходного фильма с поддержкой override критериев.

        source_movie может быть None — тогда все критерии пустые, а затем
        заменяются значениями из override_criteria.
        """
        source_movie_id = None
        source_genre_ids = []
        source_keyword_ids = []
        source_theme_ids = []
        source_developer_ids = []
        source_series_id = None

        if source_movie is not None:
            source_data = self._get_cached_movie_data(source_movie)

            if isinstance(source_movie, Movie):
                source_movie_id = source_movie.id

            source_genre_ids = list(source_data.get('genres', set()))
            source_keyword_ids = list(source_data.get('keywords', set()))
            source_theme_ids = list(source_data.get('themes', set()))
            source_developer_ids = list(source_data.get('developers', set()))
            source_series_id = source_data.get('series_id')

        # Применяем override (замена критериев source).
        if override_criteria:
            if 'genres' in override_criteria:
                source_genre_ids = list(override_criteria.get('genres') or [])
            if 'keywords' in override_criteria:
                source_keyword_ids = list(override_criteria.get('keywords') or [])
            if 'themes' in override_criteria:
                source_theme_ids = list(override_criteria.get('themes') or [])
            if 'developers' in override_criteria or 'production_companies' in override_criteria:
                val = override_criteria.get(
                    'developers',
                    override_criteria.get('production_companies'),
                )
                source_developer_ids = list(val or [])
            if 'series' in override_criteria or 'series_id' in override_criteria:
                source_series_id = override_criteria.get(
                    'series_id',
                    override_criteria.get('series'),
                )

        source_genre_count = len(source_genre_ids)
        source_keyword_count = len(source_keyword_ids)
        source_theme_count = len(source_theme_ids)
        source_developer_count = len(source_developer_ids)
        source_series_count = 1 if source_series_id else 0

        enhanced_source_data = {
            'movie_id': source_movie_id,
            'genre_ids': source_genre_ids,
            'genre_count': source_genre_count,
            'keyword_ids': source_keyword_ids,
            'keyword_count': source_keyword_count,
            'theme_ids': source_theme_ids,
            'theme_count': source_theme_count,
            'developer_ids': source_developer_ids,
            'developer_count': source_developer_count,
            'series_id': source_series_id,
            'series_count': source_series_count,
            'genres': set(source_genre_ids),
            'keywords': set(source_keyword_ids),
            'themes': set(source_theme_ids),
            'developers': set(source_developer_ids),
        }

        return enhanced_source_data

    # ------------------------------------------------------------------
    # Подготовка кандидатов
    # ------------------------------------------------------------------
    def _prepare_candidate_data(self, candidate_ids):
        from django.db import connection
        import time

        if self.stop_flag:
            if self.verbose:
                print("Прерывание: остановка в _prepare_candidate_data")
            return {}

        prep_time = time.time()
        movies_data = {}

        if not candidate_ids:
            return movies_data

        candidate_ids_str = ','.join(map(str, candidate_ids))

        query = f"""
            SELECT
                m.id,
                m.name,
                COALESCE((
                    SELECT COUNT(*)
                    FROM movies_movie_keywords mmk
                    WHERE mmk.movie_id = m.id
                ), 0) as total_keywords,
                COALESCE((
                    SELECT COUNT(*)
                    FROM movies_movie_genres mmg
                    WHERE mmg.movie_id = m.id
                ), 0) as total_genres,
                COALESCE((
                    SELECT COUNT(*)
                    FROM movies_movie_themes mmt
                    WHERE mmt.movie_id = m.id
                ), 0) as total_themes,
                COALESCE((
                    SELECT COUNT(*)
                    FROM movies_movie_production_companies mmpc
                    WHERE mmpc.movie_id = m.id
                ), 0) as total_developers,
                COALESCE(m.rating_count, 0) as rating_count,
                m.series_id
            FROM movies_movie m
            WHERE m.id IN ({candidate_ids_str})
        """

        with connection.cursor() as cursor:
            cursor.execute(query)
            for row in cursor.fetchall():
                if self.stop_flag:
                    if self.verbose:
                        print("Прерывание: остановка в цикле _prepare_candidate_data")
                    return movies_data

                movie_id, movie_name = row[0], row[1]
                movies_data[movie_id] = {
                    'id': movie_id,
                    'name': movie_name,
                    'total_keywords': row[2] or 0,
                    'total_genres': row[3] or 0,
                    'total_themes': row[4] or 0,
                    'total_developers': row[5] or 0,
                    'rating_count': row[6] or 0,
                    'series_id': row[7],
                    'common_keywords': 0,
                    'common_genres': 0,
                    'common_themes': 0,
                    'common_developers': 0,
                    'common_series': 0,
                }

        if self.verbose:
            elapsed = time.time() - prep_time
            print(f"Подготовлено {len(movies_data)} фильмов за {elapsed:.2f} сек")

        return movies_data

    # ------------------------------------------------------------------
    # Поиск кандидатов (SQL)
    # ------------------------------------------------------------------
    @timeit
    def _get_candidate_ids_new(self, source_data, min_similarity, search_filters=None):
        import time
        from django.utils import timezone
        from django.db import connection

        if self.verbose:
            start_time = time.time()  # noqa: F841
        current_time = timezone.now()

        if self.stop_flag:
            if self.verbose:
                print("Прерывание: остановка перед поиском кандидатов")
            return []

        source_genre_ids = source_data['genre_ids']
        source_theme_ids = source_data['theme_ids']
        source_keyword_ids = source_data['keyword_ids']
        source_movie_id = source_data.get('movie_id')

        sql_parts = []
        params = [current_time]

        base_sql = """
                   SELECT DISTINCT m.id
                   FROM movies_movie m
                   WHERE m.first_release_date IS NOT NULL
                     AND m.first_release_date <= %s
                   """
        sql_parts.append(base_sql)

        # Исключаем source-фильм только если есть реальный source_movie_id.
        if source_movie_id is not None:
            sql_parts.append(" AND m.id != %s")
            params.append(source_movie_id)

        if self.stop_flag:
            if self.verbose:
                print("Прерывание: остановка после базового SQL")
            return []

        if search_filters:
            if self.verbose:
                print(f"Applying search filters in SQL: {search_filters}")

            year_start = search_filters.get('release_year_start')
            year_end = search_filters.get('release_year_end')

            if year_start:
                sql_parts.append(
                    f" AND EXTRACT(YEAR FROM m.first_release_date) >= {int(year_start)}"
                )
            if year_end:
                sql_parts.append(
                    f" AND EXTRACT(YEAR FROM m.first_release_date) <= {int(year_end)}"
                )

            if search_filters.get('genres'):
                for genre_id in search_filters['genres']:
                    sql_parts.append(f"""
                        AND EXISTS (
                            SELECT 1 FROM movies_movie_genres mmg
                            WHERE mmg.movie_id = m.id AND mmg.genre_id = {int(genre_id)}
                        )
                    """)

            if search_filters.get('keywords'):
                for keyword_id in search_filters['keywords']:
                    sql_parts.append(f"""
                        AND EXISTS (
                            SELECT 1 FROM movies_movie_keywords mmk
                            WHERE mmk.movie_id = m.id AND mmk.keyword_id = {int(keyword_id)}
                        )
                    """)

            if search_filters.get('themes'):
                for theme_id in search_filters['themes']:
                    sql_parts.append(f"""
                        AND EXISTS (
                            SELECT 1 FROM movies_movie_themes mmt
                            WHERE mmt.movie_id = m.id AND mmt.theme_id = {int(theme_id)}
                        )
                    """)

        # Основной fallback-фильтр по критериям source
        if source_genre_ids:
            source_genre_ids_str = ','.join(map(str, source_genre_ids))
            if source_data['genre_count'] >= 2:
                sql_parts.append(f"""
                    AND EXISTS (
                        SELECT 1 FROM movies_movie_genres mmg
                        WHERE mmg.movie_id = m.id AND mmg.genre_id IN ({source_genre_ids_str})
                        GROUP BY mmg.movie_id
                        HAVING COUNT(DISTINCT mmg.genre_id) >= 2
                    )
                """)
            else:
                sql_parts.append(f"""
                    AND EXISTS (
                        SELECT 1 FROM movies_movie_genres mmg
                        WHERE mmg.movie_id = m.id AND mmg.genre_id IN ({source_genre_ids_str})
                    )
                """)
        elif source_theme_ids:
            source_theme_ids_str = ','.join(map(str, source_theme_ids))
            sql_parts.append(f"""
                AND EXISTS (
                    SELECT 1 FROM movies_movie_themes mmt
                    WHERE mmt.movie_id = m.id AND mmt.theme_id IN ({source_theme_ids_str})
                )
            """)
        elif source_keyword_ids:
            source_keyword_ids_str = ','.join(map(str, source_keyword_ids))
            sql_parts.append(f"""
                AND EXISTS (
                    SELECT 1 FROM movies_movie_keywords mmk
                    WHERE mmk.movie_id = m.id AND mmk.keyword_id IN ({source_keyword_ids_str})
                )
            """)

        if self.stop_flag:
            if self.verbose:
                print("Прерывание: остановка перед выполнением SQL")
            return []

        final_sql = ' '.join(sql_parts)

        print(f"[_get_candidate_ids_new] SQL params={params}, sql_len={len(final_sql)}")

        candidate_ids = []

        with connection.cursor() as cursor:
            try:
                cursor.execute("SET statement_timeout = 30000")
                cursor.execute(final_sql, params)
                candidate_ids = [row[0] for row in cursor.fetchall()]
            except Exception as e:
                if "canceling statement due to statement timeout" in str(e):
                    print("[_get_candidate_ids_new] SQL отменён по таймауту (30 сек)")
                    return []
                print(f"[_get_candidate_ids_new] ОШИБКА SQL: {e}")
                raise

        print(f"[_get_candidate_ids_new] candidate_ids={len(candidate_ids)}")

        return candidate_ids

    # ------------------------------------------------------------------
    # Подсчет общих элементов (SQL по локальным id)
    # ------------------------------------------------------------------
    @timeit
    def _calculate_common_elements_new(self, movies_data, source_data, candidate_ids):
        """Подсчет общих элементов через связные таблицы по локальным id (вариант C)."""
        import time
        from django.db import connection

        if self.stop_flag:
            if self.verbose:
                print("Прерывание: остановка в _calculate_common_elements_new")
            return movies_data

        start_time = time.time()

        if not candidate_ids:
            return movies_data

        source_genre_ids = source_data.get('genre_ids', [])
        source_keyword_ids = source_data.get('keyword_ids', [])
        source_theme_ids = source_data.get('theme_ids', [])
        source_developer_ids = source_data.get('developer_ids', [])
        source_series_id = source_data.get('series_id')

        candidate_ids_str = ','.join(map(str, candidate_ids))

        genre_ids_str = ','.join(map(str, source_genre_ids)) if source_genre_ids else '-1'
        keyword_ids_str = ','.join(map(str, source_keyword_ids)) if source_keyword_ids else '-1'
        theme_ids_str = ','.join(map(str, source_theme_ids)) if source_theme_ids else '-1'
        developer_ids_str = ','.join(map(str, source_developer_ids)) if source_developer_ids else '-1'

        if source_series_id is not None:
            series_sql = f"(CASE WHEN m.series_id = {int(source_series_id)} THEN 1 ELSE 0 END)"
        else:
            series_sql = "0"

        query = f"""
            SELECT
                m.id as movie_id,
                COALESCE((
                    SELECT COUNT(*)
                    FROM movies_movie_genres mmg
                    WHERE mmg.movie_id = m.id
                      AND mmg.genre_id IN ({genre_ids_str})
                ), 0) as common_genres,
                COALESCE((
                    SELECT COUNT(*)
                    FROM movies_movie_keywords mmk
                    WHERE mmk.movie_id = m.id
                      AND mmk.keyword_id IN ({keyword_ids_str})
                ), 0) as common_keywords,
                COALESCE((
                    SELECT COUNT(*)
                    FROM movies_movie_themes mmt
                    WHERE mmt.movie_id = m.id
                      AND mmt.theme_id IN ({theme_ids_str})
                ), 0) as common_themes,
                COALESCE((
                    SELECT COUNT(*)
                    FROM movies_movie_production_companies mmpc
                    WHERE mmpc.movie_id = m.id
                      AND mmpc.company_id IN ({developer_ids_str})
                ), 0) as common_developers,
                {series_sql} as common_series
            FROM movies_movie m
            WHERE m.id IN ({candidate_ids_str})
        """

        with connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()

            for row in rows:
                if self.stop_flag:
                    if self.verbose:
                        print("Прерывание: остановка в цикле _calculate_common_elements_new")
                    return movies_data

                movie_id = row[0]
                if movie_id in movies_data:
                    movies_data[movie_id].update({
                        'common_genres': row[1],
                        'common_keywords': row[2],
                        'common_themes': row[3],
                        'common_developers': row[4],
                        'common_series': row[5],
                    })

        if self.verbose:
            elapsed = time.time() - start_time
            print(f"Подсчет общих элементов завершен за {elapsed:.2f} сек")

        return movies_data