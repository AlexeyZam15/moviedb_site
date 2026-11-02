# movies/similarity_parts/search_mixin.py
"""Search / orchestration methods for moviesimilarity."""

from .utils import timeit


class SearchMixin:
    """Поиск похожих фильмов и загрузка результатов."""

    # ------------------------------------------------------------------
    # Основной публичный метод
    # ------------------------------------------------------------------
    @timeit
    def find_similar_movies(self, source_movie=None, min_similarity=None, limit=None,
                            search_filters=None, override_criteria=None):
        """Поиск похожих фильмов.

        source_movie — Movie или None. Если None, критерии берутся ТОЛЬКО
        из override_criteria.
        """
        import time
        from ..models import Movie

        total_start_time = time.time()

        if limit is None:
            limit = self.DEFAULT_SIMILAR_MOVIES_LIMIT

        if min_similarity is None:
            min_similarity = self.DEFAULT_MIN_SIMILARITY

        if self.verbose:
            print(f"\n{'=' * 60}")
            print("🔍 НАЧАЛО ПОИСКА ПОХОЖИХ ФИЛЬМОВ")
            print(f"{'=' * 60}")
            print(f"Source: {getattr(source_movie, 'id', None) if source_movie else None}")
            print(f"Search filters: {search_filters}")
            print(f"Override criteria: {override_criteria}")
            print(f"Min similarity: {min_similarity}")
            print(f"{'=' * 60}\n")

        try:
            source_data = self._prepare_source_data(
                source_movie,
                override_criteria=override_criteria,
            )

            # Основные критерии, которые могут дать вклад >= порога.
            main_criteria = (
                    source_data['genre_count'] +
                    source_data['keyword_count'] +
                    source_data['theme_count'] +
                    source_data['developer_count'] +
                    (1 if source_data.get('series_id') else 0)
            )
            effective_min_similarity = min_similarity if main_criteria > 0 else 0.0

            print(
                f"[find_similar_movies] source={getattr(source_movie, 'id', None) if source_movie else None}, "
                f"main_criteria={main_criteria}, effective_min_similarity={effective_min_similarity}, "
                f"override_criteria={override_criteria}"
            )

            if self.stop_flag:
                if self.verbose:
                    print("Прерывание: остановка после подготовки данных")
                return []

            candidate_ids = self._get_candidate_ids_new(
                source_data, effective_min_similarity, search_filters,
            )

            print(f"[find_similar_movies] candidate_ids={len(candidate_ids)}")

            if self.stop_flag:
                if self.verbose:
                    print("Прерывание: остановка после получения кандидатов")
                return []

            if not candidate_ids:
                print("[find_similar_movies] Нет кандидатов, возвращаем []")
                return []

            movies_data = self._prepare_candidate_data(candidate_ids)

            print(f"[find_similar_movies] movies_data after prepare={len(movies_data)}")

            if self.stop_flag:
                if self.verbose:
                    print("Прерывание: остановка после подготовки данных")
                return []

            movies_data = self._calculate_common_elements_new(
                movies_data, source_data, candidate_ids,
            )

            print(f"[find_similar_movies] movies_data after common_elements={len(movies_data)}")

            if self.stop_flag:
                if self.verbose:
                    print("Прерывание: остановка после подсчета общих элементов")
                return []

            similar_movies = self._calculate_similarity_for_candidates(
                movies_data, source_data, source_movie,
                min_similarity=effective_min_similarity,
            )

            print(f"[find_similar_movies] similar_movies before limit={len(similar_movies)}")

            if self.stop_flag:
                if self.verbose:
                    print("Прерывание: остановка после расчета схожести")
                return []

            # Если source-фильм не проходит фильтр по дате — убрать из результатов.
            if (search_filters and isinstance(source_movie, Movie)
                    and source_movie.first_release_date):
                year_start = search_filters.get('release_year_start')
                year_end = search_filters.get('release_year_end')
                source_year = source_movie.first_release_date.year

                source_passes_date = True
                if year_start and source_year < year_start:
                    source_passes_date = False
                if year_end and source_year > year_end:
                    source_passes_date = False

                if not source_passes_date:
                    similar_movies = [
                        item for item in similar_movies
                        if not item.get('is_source_movie', False)
                    ]
                    if self.verbose:
                        print("Исходный фильм удалён из результатов (не проходит фильтр по дате)")

            similar_movies = self._sort_and_limit_results(similar_movies, limit)

            final_results = self._load_full_objects(similar_movies)

            print(f"[find_similar_movies] final_results={len(final_results)}")

            total_elapsed = time.time() - total_start_time

            if self.verbose:
                print(f"\n{'=' * 60}")
                print("✅ ПОИСК ЗАВЕРШЕН")
                print(f"{'=' * 60}")
                print(f"Найдено похожих фильмов: {len(final_results)}")
                print(f"Общее время выполнения: {total_elapsed:.2f} сек")
                print(f"{'=' * 60}\n")

            return final_results

        except KeyboardInterrupt:
            self.stop_flag = True
            if self.verbose:
                print("\n\n⚠️ Поиск прерван пользователем (Ctrl+C)")
            return []
        except Exception as e:
            print(f"[find_similar_movies] ОШИБКА при поиске похожих фильмов: {e}")
            import traceback
            traceback.print_exc()
            return []

    # ------------------------------------------------------------------
    # Загрузка полных объектов
    # ------------------------------------------------------------------
    @timeit
    def _load_full_objects(self, similar_movies):
        import time
        from ..models import Movie

        load_time = time.time()
        final_results = []

        if not similar_movies:
            return final_results

        try:
            movie_ids = [item['movie_id'] for item in similar_movies]
            similarity_map = {item['movie_id']: item for item in similar_movies}

            movies = Movie.objects.filter(id__in=movie_ids).prefetch_related(
                'genres',
                'themes',
                'production_companies',
            ).only(
                'id', 'name', 'rating', 'rating_count',
                'first_release_date', 'cover_url',
            )

            for movie in movies:
                item = similarity_map.get(movie.id)
                if item:
                    final_results.append({
                        'movie': movie,
                        'similarity': item['similarity'],
                        'common_keywords_count': item.get('common_keywords', 0),
                        'common_genres_count': item.get('common_genres', 0),
                        'common_themes_count': item.get('common_themes', 0),
                        'common_developers_count': item.get('common_developers', 0),
                        'common_series_count': item.get('common_series', 0),
                        'is_source_movie': item.get('is_source_movie', False),
                    })
        except Exception as e:
            if self.verbose:
                print(f"Ошибка при загрузке объектов: {e}")
            return []

        if self.verbose:
            print(f"Загрузка объектов завершена за {time.time() - load_time:.2f} сек")

        return final_results

    # ------------------------------------------------------------------
    # Ключи кэша
    # ------------------------------------------------------------------
    def _get_similarity_cache_key(self, source, target):
        """Генерирует ключ для кэша схожести с учетом версии алгоритма."""
        from django.db.models import Model

        if isinstance(source, Model) and hasattr(source, 'id'):
            source_key = f"movie_{source.id}"
        else:
            source_key = "movie_None"

        if isinstance(target, Model) and hasattr(target, 'id'):
            target_key = f"movie_{target.id}"
        else:
            target_key = f"movie_{getattr(target, 'id', 0)}"

        return f"sim_v{self.ALGORITHM_VERSION}_{source_key}_{target_key}"

    def _generate_cache_key(self, source_movie, min_similarity, limit,
                            source_data, search_filters=None, override_criteria=None):
        """Генерация ключа кэша с учетом версии алгоритма."""
        import json
        import hashlib
        from ..models import Movie

        if isinstance(source_movie, Movie):
            source_part = {
                'type': 'movie',
                'movie_id': source_movie.id,
            }
        else:
            source_part = {
                'type': 'criteria',
                'genres': sorted(source_data.get('genre_ids', [])),
                'keywords': sorted(source_data.get('keyword_ids', [])),
                'themes': sorted(source_data.get('theme_ids', [])),
                'developers': sorted(source_data.get('developer_ids', [])),
                'series_id': source_data.get('series_id'),
            }

        cache_key_data = {
            'source': source_part,
            'min_similarity': min_similarity,
            'limit': limit,
            'search_filters': search_filters or {},
            'override_criteria': override_criteria or {},
            'algorithm_version': self.ALGORITHM_VERSION,
        }

        cache_key_str = json.dumps(cache_key_data, sort_keys=True, default=str)
        return f"movie_similarity_{hashlib.md5(cache_key_str.encode()).hexdigest()}"

    # ------------------------------------------------------------------
    # Сортировка и лимит
    # ------------------------------------------------------------------
    def _sort_and_limit_results(self, similar_movies, limit):
        """Сортировка: source-фильм первым, остальные по similarity desc."""
        if self.verbose:
            print("Этап: Сортировка результатов...")

        source_items = [item for item in similar_movies if item.get('is_source_movie', False)]
        other_items = [item for item in similar_movies if not item.get('is_source_movie', False)]

        other_items.sort(key=lambda x: x['similarity'], reverse=True)

        similar_movies = source_items + other_items
        if limit and limit > 0:
            similar_movies = similar_movies[:limit]

        return similar_movies