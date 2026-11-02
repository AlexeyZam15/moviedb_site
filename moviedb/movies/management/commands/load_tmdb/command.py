# movies/load_tmdb/command.py
"""
Логика команды load_movies (TMDB-импортёр).

Вызывает collector (сбор ID / полных данных), loader (маппинг + сохранение),
OffsetManager (offset), TmdbCacheManager (кэш проверенных).
"""

import os
import time
from typing import Optional, Dict, Any, List

from django.core.cache import cache

from movies.models import Movie
from .collector import TmdbCollector
from .loader import TmdbLoader
from .offset_manager import OffsetManager
from .cache import TmdbCacheManager
from .tmdb_api import build_image_url


class TmdbLoadCommand:
    """Логика TMDB-импорта (load_movies)."""

    def __init__(self, stdout, stderr, options: Dict[str, Any]):
        self.stdout = stdout
        self.stderr = stderr
        self.options = options

        self.limit = options.get('limit') or 0
        self.offset = options.get('offset') or 0
        self.genres = options.get('genres') or ''
        self.year_from = options.get('year_from')
        self.year_to = options.get('year_to')
        self.min_vote_count = options.get('min_vote_count') or 0
        self.sort_by = options.get('sort_by') or 'popularity.desc'
        self.tmdb_ids = options.get('tmdb_ids')
        self.tmdb_ids_file = options.get('tmdb_ids_file')
        self.movie_names = options.get('movie_names') or ''
        self.update_missing_data = options.get('update_missing_data', False)
        self.update_covers = options.get('update_covers', False)
        self.overwrite = options.get('overwrite', False)
        self.count_only = options.get('count_only', False)
        self.dry_run = options.get('dry_run', False)
        self.debug = options.get('debug', False)
        self.workers = options.get('workers') or 8
        self.language = options.get('language') or 'en-US'
        self.append = options.get('append') or 'keywords,credits,recommendations,similar,release_dates'
        self.use_cache = not options.get('no_cache', False)
        self.cache_ttl = options.get('cache_ttl') or (60 * 60 * 24 * 7)
        self.clear_cache = options.get('clear_cache', False)
        self.clear_db_cache = options.get('clear_db_cache', False)
        self.reset_offset = options.get('reset_offset', False)
        self.description_contains = options.get('description_contains') or ''

        self.collector = TmdbCollector(self.stdout, self.stderr, language=self.language, debug=self.debug)
        self.loader = TmdbLoader(self.stdout, self.stderr, debug=self.debug)

    # ------------------------------------------------------------------ #
    #  Offset-параметры
    # ------------------------------------------------------------------ #

    def _offset_params(self) -> Dict[str, Any]:
        return {
            'genres': self.genres,
            'year_from': self.year_from,
            'year_to': self.year_to,
            'min_vote_count': self.min_vote_count,
            'sort_by': self.sort_by,
            'mode': 'discover',
        }

    # ------------------------------------------------------------------ #
    #  Main
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        start = time.time()

        # 0. Очистки
        if self.clear_cache:
            n = TmdbCacheManager.clear_cache()
            self.stdout.write(f"🧹 Очищен кэш TMDB: {n}\n")
        if self.clear_db_cache:
            try:
                cache.clear()
                self.stdout.write("🧹 Очищен весь кэш Django\n")
            except Exception as e:
                self.stdout.write(f"⚠️ Ошибка cache.clear(): {e}\n")

        if self.reset_offset:
            OffsetManager.clear_offset(self._offset_params())
            self.stdout.write("🔄 Offset сброшен\n")

        if self.description_contains:
            self.stdout.write(
                f"⚠️ --description-contains='{self.description_contains}' не поддерживается "
                f"discover/movie (TMDB). Флаг проигнорирован.\n"
            )

        # 1. --update-covers (без discover)
        if self.update_covers:
            updated = self._update_covers()
            self.stdout.write(f"🖼️ Обновлено cover_url/backdrop_url: {updated}\n")
            self._print_elapsed(start)
            return

        # 2. --update-missing-data (без discover, по существующим)
        if self.update_missing_data:
            self._update_missing_data(start)
            return

        # 3. Собрать tmdb_ids
        tmdb_ids = self._resolve_tmdb_ids()
        if not tmdb_ids:
            self.stdout.write("⚠️ Нет TMDB ID для обработки\n")
            self._print_elapsed(start)
            return

        # 4. --count-only
        if self.count_only:
            self.stdout.write(f"✅ Найдено (count-only): {len(tmdb_ids)}\n")
            self._print_elapsed(start)
            return

        # 5. Фильтр по кэшу
        if self.use_cache and not self.overwrite:
            checked = TmdbCacheManager.batch_check(tmdb_ids)
            before = len(tmdb_ids)
            tmdb_ids = [tid for tid in tmdb_ids if not checked.get(int(tid), False)]
            skipped = before - len(tmdb_ids)
            if skipped:
                self.stdout.write(f"⏭️ Пропущено (уже проверены): {skipped}\n")

        if not tmdb_ids:
            self.stdout.write("✅ Все TMDB ID уже проверены\n")
            self._print_elapsed(start)
            return

        self.stdout.write(f"📥 К загрузке: {len(tmdb_ids)} TMDB ID\n")

        if self.dry_run:
            self.stdout.write(f"🔧 [DRY-RUN] Были бы загружены: {len(tmdb_ids)} TMDB ID\n")
            self.stdout.write(f"   Первые 10: {tmdb_ids[:10]}\n")
            self._print_elapsed(start)
            return

        # 6. Загрузить полные данные
        details = self.collector.fetch_movies_details(
            tmdb_ids, workers=self.workers, append=self.append
        )
        self.stdout.write(f"📥 Загружено полных данных: {len(details)}/{len(tmdb_ids)}\n")

        if not details:
            self.stdout.write("⚠️ Нет данных для сохранения\n")
            self._print_elapsed(start)
            return

        # 7. Сохранить
        movies_data_list = list(details.values())
        created, updated, _, movie_map = self.loader.save_movies(
            movies_data_list, overwrite=self.overwrite
        )
        self.stdout.write(f"💾 Movie: создано={created}, обновлено={updated}\n")

        # 8. Recommendations + Images/Videos
        recs = self.loader.save_recommendations(movies_data_list, movie_map)
        imgs, vids = self.loader.save_images_videos(movies_data_list, movie_map)
        if recs:
            self.stdout.write(f"🎬 MovieRecommendation: {recs}\n")
        if imgs or vids:
            self.stdout.write(f"🖼️ Image: {imgs}, Video: {vids}\n")

        # 9. Кэш
        if self.use_cache:
            TmdbCacheManager.batch_mark_checked(list(details.keys()))

        # 10. Offset (только для discover-режима)
        if not self.tmdb_ids and not self.tmdb_ids_file and not self.movie_names:
            OffsetManager.save_offset(self._offset_params(), self.offset + len(tmdb_ids))

        self._print_elapsed(start)

    # ------------------------------------------------------------------ #
    #  Резолв TMDB ID
    # ------------------------------------------------------------------ #

    def _resolve_tmdb_ids(self) -> List[int]:
        # 1. --tmdb-ids
        if self.tmdb_ids:
            return [int(x) for x in self.tmdb_ids]

        # 2. --tmdb-ids-file
        if self.tmdb_ids_file:
            if not os.path.exists(self.tmdb_ids_file):
                self.stderr.write(f"❌ Файл не найден: {self.tmdb_ids_file}\n")
                return []
            ids = []
            with open(self.tmdb_ids_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.isdigit():
                        ids.append(int(line))
            self.stdout.write(f"📂 Загружено {len(ids)} TMDB ID из {self.tmdb_ids_file}\n")
            return ids

        # 3. --Movie-names
        if self.movie_names:
            names = [n.strip() for n in self.movie_names.split(',') if n.strip()]
            self.stdout.write(f"🔍 Поиск по именам: {len(names)}\n")
            return self.collector.search_movie_ids_by_names(names)

        # 4. discover
        genre_ids = []
        if self.genres:
            genre_names = [g.strip() for g in self.genres.split(',') if g.strip()]
            genre_ids = self.collector.resolve_genre_ids(genre_names)
            self.stdout.write(f"🎭 Жанры TMDB ID: {genre_ids}\n")

        offset = self.offset
        if not self.reset_offset:
            saved = OffsetManager.load_offset(self._offset_params())
            if saved is not None:
                offset = saved
                self.stdout.write(f"📍 Восстановлен offset: {offset}\n")

        if self.count_only:
            n = self.collector.count_discover(
                genres=genre_ids or None,
                year_from=self.year_from,
                year_to=self.year_to,
                min_vote_count=self.min_vote_count or None,
                sort_by=self.sort_by,
            )
            self.stdout.write(f"✅ discover total_results: {n}\n")
            return []

        return self.collector.discover_movie_ids(
            genres=genre_ids or None,
            year_from=self.year_from,
            year_to=self.year_to,
            min_vote_count=self.min_vote_count or None,
            sort_by=self.sort_by,
            limit=self.limit,
            offset=offset,
        )

    # ------------------------------------------------------------------ #
    #  --update-missing-data / --update-covers
    # ------------------------------------------------------------------ #

    def _update_missing_data(self, start: float) -> None:
        tmdb_ids = self.tmdb_ids or []
        if not tmdb_ids:
            tmdb_ids = list(
                Movie.objects.exclude(tmdb_id__isnull=True).values_list('tmdb_id', flat=True)
            )
        self.stdout.write(f"🔄 update-missing-data: {len(tmdb_ids)} TMDB ID\n")
        details = self.collector.fetch_movies_details(tmdb_ids, workers=self.workers, append=self.append)
        if not details:
            self.stdout.write("⚠️ Нет данных\n")
            self._print_elapsed(start)
            return
        created, updated, _, movie_map = self.loader.save_movies(
            list(details.values()), overwrite=False
        )
        self.stdout.write(f"💾 Movie: создано={created}, обновлено={updated}\n")
        self.loader.save_recommendations(list(details.values()), movie_map)
        self._print_elapsed(start)

    def _update_covers(self) -> int:
        qs = Movie.objects.exclude(poster_path__isnull=True).exclude(poster_path='')
        updated = 0
        to_update = []
        for m in qs.iterator(chunk_size=500):
            new_cover = build_image_url(m.poster_path, 'w500')
            new_backdrop = build_image_url(m.backdrop_path, 'w780') if m.backdrop_path else None
            changed = False
            if new_cover and m.cover_url != new_cover:
                m.cover_url = new_cover
                changed = True
            if new_backdrop and m.backdrop_url != new_backdrop:
                m.backdrop_url = new_backdrop
                changed = True
            if changed:
                to_update.append(m)
                updated += 1
            if len(to_update) >= 500:
                Movie.objects.bulk_update(to_update, ['cover_url', 'backdrop_url'], batch_size=200)
                to_update = []
        if to_update:
            Movie.objects.bulk_update(to_update, ['cover_url', 'backdrop_url'], batch_size=200)
        return updated

    # ------------------------------------------------------------------ #
    #  Утилиты
    # ------------------------------------------------------------------ #

    def _print_elapsed(self, start: float) -> None:
        elapsed = time.time() - start
        self.stdout.write(f"⏱️ Время: {elapsed:.1f}с\n")