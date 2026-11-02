# movies/load_tmdb/collector.py
"""
Сбор TMDB ID и полных данных фильмов.

- discover/movie: пагинация по фильтрам (жанры, годы, min_vote_count, sort_by).
- movie/{id}?append_to_response=...: полные данные (keywords, credits, recommendations, similar, release_dates).
- search/movie: поиск по названию (--Movie-names) + схожесть названий.
- genre/movie/list: резолв жанров (имя <-> id).
"""

import time
import difflib
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, Any, List, Tuple

from .tmdb_api import (
    tmdb_get_movie,
    tmdb_discover_movies,
    tmdb_request,
    tmdb_get_genres,
    get_last_error,
)


class TmdbCollector:
    """Сбор TMDB ID и полных данных фильмов."""

    def __init__(self, stdout, stderr, language: str = 'en-US', debug: bool = False):
        self.stdout = stdout
        self.stderr = stderr
        self.language = language
        self.debug = debug
        self._genre_name_to_id: Optional[Dict[str, int]] = None
        self._genre_id_to_name: Optional[Dict[int, str]] = None

    # ------------------------------------------------------------------ #
    #  Жанры
    # ------------------------------------------------------------------ #

    def _ensure_genres(self) -> None:
        if self._genre_name_to_id is not None:
            return
        data = tmdb_get_genres(language=self.language)
        if not data:
            self.stderr.write(f"   ⚠️ Не удалось загрузить жанры TMDB (error={get_last_error()})\n")
            self.stderr.flush()
            self._genre_name_to_id = {}
            self._genre_id_to_name = {}
            return
        genres = data.get('genres') or []
        self._genre_name_to_id = {g['name'].lower(): int(g['id']) for g in genres if g.get('id') and g.get('name')}
        self._genre_id_to_name = {int(g['id']): g['name'] for g in genres if g.get('id') and g.get('name')}
        if self.debug:
            self.stdout.write(f"   🎭 Загружено жанров TMDB: {len(self._genre_name_to_id)}\n")

    def resolve_genre_ids(self, genre_names: List[str]) -> List[int]:
        """Имена жанров -> TMDB ID. Неизвестные — warning."""
        self._ensure_genres()
        result = []
        for name in genre_names:
            key = name.strip().lower()
            gid = self._genre_name_to_id.get(key)
            if gid is None:
                # Попробуем частичное совпадение
                for n, i in self._genre_name_to_id.items():
                    if key in n or n in key:
                        gid = i
                        break
            if gid is None:
                self.stderr.write(f"   ⚠️ Жанр '{name}' не найден в TMDB\n")
                self.stderr.flush()
            else:
                result.append(gid)
        return result

    def genre_name(self, genre_id: int) -> Optional[str]:
        self._ensure_genres()
        return self._genre_id_to_name.get(int(genre_id)) if self._genre_id_to_name else None

    # ------------------------------------------------------------------ #
    #  discover/movie
    # ------------------------------------------------------------------ #

    def _build_discover_params(
            self,
            genres: Optional[List[int]] = None,
            year_from: Optional[int] = None,
            year_to: Optional[int] = None,
            min_vote_count: Optional[int] = None,
            sort_by: str = 'popularity.desc',
            include_adult: bool = False,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            'sort_by': sort_by,
            'include_adult': str(include_adult).lower(),
        }
        if genres:
            # ',' = AND (все жанры), '|' = OR. Для --genres используем AND.
            params['with_genres'] = ','.join(str(g) for g in genres)
        if year_from:
            params['primary_release_date.gte'] = f'{year_from}-01-01'
        if year_to:
            params['primary_release_date.lte'] = f'{year_to}-12-31'
        if min_vote_count:
            params['vote_count.gte'] = int(min_vote_count)
        return params

    def count_discover(
            self,
            genres: Optional[List[int]] = None,
            year_from: Optional[int] = None,
            year_to: Optional[int] = None,
            min_vote_count: Optional[int] = None,
            sort_by: str = 'popularity.desc',
    ) -> int:
        """Возвращает total_results для discover (page=1)."""
        params = self._build_discover_params(genres, year_from, year_to, min_vote_count, sort_by)
        data = tmdb_discover_movies(params=params, page=1, language=self.language)
        if not data:
            self.stderr.write(f"   ⚠️ discover/movie вернул None (error={get_last_error()})\n")
            self.stderr.flush()
            return 0
        return int(data.get('total_results') or 0)

    def discover_movie_ids(
            self,
            genres: Optional[List[int]] = None,
            year_from: Optional[int] = None,
            year_to: Optional[int] = None,
            min_vote_count: Optional[int] = None,
            sort_by: str = 'popularity.desc',
            limit: int = 0,
            offset: int = 0,
    ) -> List[int]:
        """
        Собирает TMDB ID через discover/movie с пагинацией.

        limit: сколько ID собрать (0 = без лимита).
        offset: сколько ID пропустить.
        TMDB ограничивает page <= 500.
        """
        params = self._build_discover_params(genres, year_from, year_to, min_vote_count, sort_by)

        ids: List[int] = []
        page = 1
        total_pages = None
        collected = 0  # сколько уже пропущено + собрано
        skipped = 0

        while True:
            if page > 500:
                if self.debug:
                    self.stdout.write("   ⚠️ discover: достигнут лимит page=500\n")
                break

            data = tmdb_discover_movies(params=params, page=page, language=self.language)
            if not data:
                self.stderr.write(f"   ⚠️ discover page={page} вернул None (error={get_last_error()})\n")
                self.stderr.flush()
                break

            if total_pages is None:
                total_pages = int(data.get('total_pages') or 0)
                total_results = int(data.get('total_results') or 0)
                if self.debug:
                    self.stdout.write(
                        f"   🔍 discover: total_results={total_results}, total_pages={total_pages}\n"
                    )

            results = data.get('results') or []
            if not results:
                break

            for item in results:
                tid = item.get('id')
                if not tid:
                    continue
                if skipped < offset:
                    skipped += 1
                    continue
                ids.append(int(tid))
                collected += 1
                if limit and len(ids) >= limit:
                    break

            if limit and len(ids) >= limit:
                break
            if total_pages and page >= total_pages:
                break

            page += 1
            # Небольшая пауза, чтобы не спамить (rate limiter уже есть)
            time.sleep(0.05)

        if self.debug:
            self.stdout.write(
                f"   ✅ discover: собрано {len(ids)} ID (offset={offset}, limit={limit})\n"
            )
        return ids

    # ------------------------------------------------------------------ #
    #  search/movie (по именам)
    # ------------------------------------------------------------------ #

    def search_movie_ids_by_names(
            self,
            names: List[str],
            min_similarity: float = 0.7,
            limit_per_name: int = 1,
    ) -> List[int]:
        """
        Поиск TMDB ID по названиям через search/movie.
        Берёт лучший матч по схожести (difflib), порог min_similarity.
        """
        ids: List[int] = []
        for name in names:
            name = name.strip()
            if not name:
                continue
            data = tmdb_request(
                'search/movie',
                params={'query': name, 'language': self.language, 'include_adult': 'false'},
            )
            if not data:
                self.stderr.write(
                    f"   ⚠️ search/movie '{name}' вернул None (error={get_last_error()})\n"
                )
                self.stderr.flush()
                continue
            results = data.get('results') or []
            if not results:
                if self.debug:
                    self.stdout.write(f"   ❌ search/movie '{name}': нет результатов\n")
                continue

            best = None
            best_ratio = 0.0
            for item in results:
                title = (item.get('title') or '').lower()
                original = (item.get('original_title') or '').lower()
                ratio = max(
                    difflib.SequenceMatcher(None, name.lower(), title).ratio(),
                    difflib.SequenceMatcher(None, name.lower(), original).ratio(),
                )
                if ratio > best_ratio:
                    best_ratio = ratio
                    best = item

            if best and best_ratio >= min_similarity:
                tid = best.get('id')
                if tid:
                    ids.append(int(tid))
                    if self.debug:
                        self.stdout.write(
                            f"   ✅ search/movie '{name}' -> {tid} "
                            f"('{best.get('title')}', ratio={best_ratio:.2f})\n"
                        )
                    if limit_per_name and len(ids) >= limit_per_name * len(names):
                        pass
            else:
                if self.debug:
                    self.stdout.write(
                        f"   ❌ search/movie '{name}': лучший ratio={best_ratio:.2f} < {min_similarity}\n"
                    )
        return ids

    # ------------------------------------------------------------------ #
    #  movie/{id}
    # ------------------------------------------------------------------ #

    def fetch_movie_details(
            self,
            tmdb_id: int,
            append: str = 'keywords,credits,recommendations,similar,release_dates',
    ) -> Optional[Dict[str, Any]]:
        """Полные данные фильма (movie/{id}?append_to_response=...)."""
        data = tmdb_get_movie(tmdb_id, append=append, language=self.language)
        if not data:
            self.stderr.write(
                f"   ⚠️ movie/{tmdb_id} вернул None (error={get_last_error()})\n"
            )
            self.stderr.flush()
        return data

    def fetch_movies_details(
            self,
            tmdb_ids: List[int],
            workers: int = 8,
            append: str = 'keywords,credits,recommendations,similar,release_dates',
    ) -> Dict[int, Dict[str, Any]]:
        """Параллельно загружает полные данные для списка tmdb_id."""
        result: Dict[int, Dict[str, Any]] = {}
        if not tmdb_ids:
            return result

        total = len(tmdb_ids)
        done = 0
        with ThreadPoolExecutor(max_workers=max(1, min(workers, 16))) as executor:
            futures = {
                executor.submit(self.fetch_movie_details, tid, append): tid
                for tid in tmdb_ids
            }
            for future in as_completed(futures):
                tid = futures[future]
                done += 1
                try:
                    data = future.result()
                    if data:
                        result[tid] = data
                except Exception as e:
                    if self.debug:
                        self.stderr.write(f"   ❌ Ошибка movie/{tid}: {e}\n")
                        self.stderr.flush()
                if self.debug and (done % 25 == 0 or done == total):
                    self.stdout.write(f"   📥 Загружено полных данных: {done}/{total}\n")

        return result