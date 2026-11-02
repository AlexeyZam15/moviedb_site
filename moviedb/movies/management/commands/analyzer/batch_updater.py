# movies/management/commands/analyzer/batch_updater.py
"""
Батч-апдейтер для обновления игр с предотвращением рекурсии
"""

from typing import Dict, Any, List
from django.db import transaction
import sys
import time
from .output_manager import UnifiedProgressBar


class BatchUpdater:
    """Батч-апдейтер для обновления игр в базе"""

    def __init__(self, batch_size: int = 100, verbose: bool = False):
        self.batch_size = batch_size  # Сохраняем batch_size
        self.movies_to_update: List[Dict] = []
        self.verbose = verbose
        self.progress_bar = None
        self.last_update_time = 0
        self.total_movies_added = 0  # Для отладки - общее количество добавленных игр

    def get_optimal_threshold(self):
        """Возвращает оптимальный порог для обновления батча"""
        # Если игр мало - обновляем сразу
        if len(self.movies_to_update) < 100:
            return 10

        # Если игр много - используем половину batch_size
        # Но не больше 1000 и не меньше 100
        return min(max(self.batch_size // 2, 100), 1000)

    def get_batch_count(self) -> int:
        """Возвращает текущее количество игр в батче"""
        return len(self.movies_to_update)

    def add_game_for_update(self, game_id: int, results: Dict[str, Any], is_keywords: bool) -> int:
        """Добавляет игру для обновления - проверяет дубликаты"""
        # УБРАНО ЛИШНЕЕ СООБЩЕНИЕ

        try:
            # Проверяем, не добавлена ли уже эта игра в текущий батч
            for game_data in self.movies_to_update:
                if game_data['game_id'] == game_id:
                    # УБРАНО ЛИШНЕЕ СООБЩЕНИЕ
                    return 0

            # Добавляем игру в батч
            self.movies_to_update.append({
                'game_id': game_id,
                'results': results,
                'is_keywords': is_keywords,
            })

            movies_in_batch = len(self.movies_to_update)

            # УБРАНО ЛИШНЕЕ СООБЩЕНИЕ

            return 1  # Игра добавлена успешно

        except Exception as e:
            # УБРАНО ЛИШНЕЕ СООБЩЕНИЕ
            return 0

    def flush(self) -> int:
        """Обновляет все накопленные игры с детальным логированием"""
        if not self.movies_to_update:
            if self.verbose:
                print(f"\nℹ️ Батч пуст, нечего обновлять")
            return 0

        try:
            movies_in_batch = len(self.movies_to_update)
            print(f"\n💾 Начинаем ОПТИМИЗИРОВАННОЕ обновление батча из {movies_in_batch} игр")

            # Разделяем на ключевые слова и обычные критерии
            keyword_movies = []
            criteria_movies = []

            for game_data in self.movies_to_update:
                if game_data['is_keywords']:
                    keyword_movies.append(game_data)
                else:
                    criteria_movies.append(game_data)

            print(f"   📊 Ключевые слова: {len(keyword_movies)} игр")
            print(f"   📊 Обычные критерии: {len(criteria_movies)} игр")

            total_updated = 0
            all_skipped = []

            # Обработка ключевых слов
            if keyword_movies:
                keywords_updated, keywords_skipped = self._update_keywords_bulk(keyword_movies)
                print(f"\n📊 КЛЮЧЕВЫЕ СЛОВА:")
                print(f"   ✅ Обновлено: {keywords_updated} игр")
                print(f"   ⚠️ Пропущено: {len(keyword_movies) - keywords_updated} игр")
                if keywords_skipped:
                    for skipped in keywords_skipped[:10]:
                        print(f"      - Игра {skipped['game_id']}: {skipped['reason']}")
                    if len(keywords_skipped) > 10:
                        print(f"      ... и еще {len(keywords_skipped) - 10} игр")
                total_updated += keywords_updated
                all_skipped.extend(keywords_skipped)

            # Обработка критериев
            if criteria_movies:
                criteria_updated, criteria_skipped = self._update_criteria_bulk(criteria_movies)
                print(f"\n📊 ОБЫЧНЫЕ КРИТЕРИИ:")
                print(f"   ✅ Обновлено: {criteria_updated} игр")
                print(f"   ⚠️ Пропущено: {len(criteria_movies) - criteria_updated} игр")
                if criteria_skipped:
                    for skipped in criteria_skipped[:10]:
                        print(f"      - Игра {skipped['game_id']}: {skipped['reason']}")
                    if len(criteria_skipped) > 10:
                        print(f"      ... и еще {len(criteria_skipped) - 10} игр")
                total_updated += criteria_updated
                all_skipped.extend(criteria_skipped)

            print(f"\n📊 РЕЗУЛЬТАТ:")
            print(f"   ✅ Реально обновлено: {total_updated} игр из {movies_in_batch}")
            print(f"   ⚠️ Пропущено: {movies_in_batch - total_updated} игр")

            # Очищаем батч
            self.movies_to_update.clear()

            return total_updated

        except Exception as e:
            print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА при обновлении батча: {e}")
            import traceback
            traceback.print_exc()
            import sys
            sys.exit(1)

    def _update_keywords_bulk(self, keyword_movies):
        """
        МАКСИМАЛЬНО ОПТИМИЗИРОВАННОЕ обновление ключевых слов
        Возвращает: (обновлено_игр, список_пропущенных_с_причинами)
        """
        from movies.models import Movie, Keyword
        from django.utils import timezone
        from django.db import transaction
        from collections import defaultdict

        start_time = time.time()

        game_ids = [g['game_id'] for g in keyword_movies]

        # 1. Получаем все игры одним запросом
        movies = {Movie.id: Movie for Movie in Movie.objects.filter(id__in=game_ids)}

        # 2. Собираем все ID ключевых слов из всех игр
        all_keyword_ids = set()
        movies_with_keywords = []
        skipped_movies = []

        for game_data in keyword_movies:
            Movie = movies.get(game_data['game_id'])
            if not Movie:
                skipped_movies.append({
                    'game_id': game_data['game_id'],
                    'reason': 'игра не найдена в БД'
                })
                continue

            keywords_data = game_data['results'].get('keywords', {})
            items = keywords_data.get('items', [])

            if not items:
                skipped_movies.append({
                    'game_id': Movie.id,
                    'reason': 'в результатах нет ключевых слов'
                })
                continue

            keyword_ids = [k['id'] for k in items if 'id' in k]
            if not keyword_ids:
                skipped_movies.append({
                    'game_id': Movie.id,
                    'reason': f'ключевые слова без ID: {items}'
                })
                continue

            all_keyword_ids.update(keyword_ids)
            movies_with_keywords.append({
                'Movie': Movie,
                'keyword_ids': keyword_ids
            })

        if not movies_with_keywords:
            return 0, skipped_movies

        # 3. Получаем все существующие ключевые слова
        existing_keywords = set(Keyword.objects.filter(id__in=all_keyword_ids).values_list('id', flat=True))

        missing_keyword_ids = all_keyword_ids - existing_keywords
        if missing_keyword_ids:
            print(
                f"   ⚠️ Предупреждение: {len(missing_keyword_ids)} ключевых слов не найдены в БД: {list(missing_keyword_ids)[:5]}...")

        # 4. Получаем текущие связи всех игр (используя keyword_ids поле)
        existing_by_game = {}
        for Movie in movies.values():
            existing_by_game[Movie.id] = set(Movie.keyword_ids or [])

        # 5. Собираем новые связи
        new_relations = []
        updated_movies = set()

        for item in movies_with_keywords:
            Movie = item['Movie']
            keyword_ids = item['keyword_ids']

            valid_ids = [kid for kid in keyword_ids if kid in existing_keywords]

            if not valid_ids:
                skipped_movies.append({
                    'game_id': Movie.id,
                    'reason': f'все {len(keyword_ids)} ключевых слов не найдены в БД'
                })
                continue

            existing_for_game = existing_by_game.get(Movie.id, set())
            new_ids = [kid for kid in valid_ids if kid not in existing_for_game]

            if new_ids:
                # Обновляем keyword_ids
                Movie.keyword_ids = list(existing_for_game.union(new_ids))
                new_relations.append(Movie)
                updated_movies.add(Movie.id)
            else:
                skipped_movies.append({
                    'game_id': Movie.id,
                    'reason': f'все ключевые слова уже есть у игры (существующих: {len(existing_for_game)})'
                })

        # 6. Массовое обновление
        if new_relations:
            try:
                with transaction.atomic():
                    Movie.objects.bulk_update(new_relations, ['keyword_ids', 'updated_at'])
            except Exception as e:
                print(f"\n❌ ОШИБКА БД при сохранении ключевых слов: {e}")
                raise

        elapsed = time.time() - start_time
        if self.verbose:
            print(
                f"⚡ Ключевые слова: {len(updated_movies)} игр, {sum(len(g.keyword_ids) for g in new_relations)} связей за {elapsed:.2f}с")

        return len(updated_movies), skipped_movies

    def _update_criteria_bulk(self, criteria_movies):
        """
        МАКСИМАЛЬНО ОПТИМИЗИРОВАННОЕ обновление критериев
        Возвращает: (обновлено_игр, список_пропущенных_с_причинами)
        """
        from movies.models import Movie, Genre, Theme, PlayerPerspective, GameMode
        from django.utils import timezone
        from django.db import transaction
        from collections import defaultdict

        start_time = time.time()

        game_ids = [g['game_id'] for g in criteria_movies]

        # 1. Получаем все игры с префетчингом
        movies = {Movie.id: Movie for Movie in Movie.objects.filter(id__in=game_ids).prefetch_related(
            'genres', 'themes', 'player_perspectives', 'game_modes'
        )}

        criteria_config = [
            ('genres', Genre, 'genre', 'genres'),
            ('themes', Theme, 'theme', 'themes'),
            ('perspectives', PlayerPerspective, 'playerperspective', 'player_perspectives'),
            ('game_modes', GameMode, 'gamemode', 'game_modes')
        ]

        all_new_relations = defaultdict(list)
        updated_movies = set()
        skipped_movies = []

        for game_data in criteria_movies:
            Movie = movies.get(game_data['game_id'])
            if not Movie:
                skipped_movies.append({
                    'game_id': game_data['game_id'],
                    'reason': 'игра не найдена в БД'
                })
                continue

            game_has_updates = False
            game_skipped_reasons = []

            for key, model, field_prefix, relation_field in criteria_config:
                items = game_data['results'].get(key, {}).get('items', [])
                if not items:
                    continue

                item_ids = [item['id'] for item in items if 'id' in item]
                if not item_ids:
                    game_skipped_reasons.append(f'{key}: нет ID в элементах')
                    continue

                # Получаем существующие ID
                existing_ids = set()
                if key == 'genres':
                    existing_ids = set(Movie.genres.values_list('id', flat=True))
                elif key == 'themes':
                    existing_ids = set(Movie.themes.values_list('id', flat=True))
                elif key == 'perspectives':
                    existing_ids = set(Movie.player_perspectives.values_list('id', flat=True))
                elif key == 'game_modes':
                    existing_ids = set(Movie.game_modes.values_list('id', flat=True))

                # Находим новые ID
                new_ids = [iid for iid in item_ids if iid not in existing_ids]

                if new_ids:
                    # Проверяем, существуют ли эти ID в БД
                    model_objects = model.objects.filter(id__in=new_ids)
                    existing_model_ids = set(model_objects.values_list('id', flat=True))
                    valid_new_ids = [iid for iid in new_ids if iid in existing_model_ids]

                    if valid_new_ids:
                        through_model = getattr(Movie, relation_field).through
                        for iid in valid_new_ids:
                            all_new_relations[through_model].append(
                                through_model(game_id=Movie.id, **{f"{field_prefix}_id": iid})
                            )
                        game_has_updates = True
                    else:
                        game_skipped_reasons.append(f'{key}: новые ID не найдены в БД ({new_ids})')
                else:
                    if item_ids:
                        game_skipped_reasons.append(f'{key}: все {len(item_ids)} элементов уже есть у игры')

            if game_has_updates:
                updated_movies.add(Movie.id)
            elif game_skipped_reasons:
                skipped_movies.append({
                    'game_id': Movie.id,
                    'reason': '; '.join(game_skipped_reasons)
                })
            else:
                skipped_movies.append({
                    'game_id': Movie.id,
                    'reason': 'нет элементов для добавления'
                })

        # 2. Массовое добавление
        total_added = 0
        if all_new_relations:
            try:
                with transaction.atomic():
                    for through_model, relations in all_new_relations.items():
                        if relations:
                            through_model.objects.bulk_create(relations, ignore_conflicts=True)
                            total_added += len(relations)

                    if updated_movies:
                        Movie.objects.filter(id__in=updated_movies).update(updated_at=timezone.now())
            except Exception as e:
                print(f"\n❌ ОШИБКА БД при сохранении критериев: {e}")
                raise

        elapsed = time.time() - start_time
        if self.verbose:
            print(f"⚡ Критерии: {len(updated_movies)} игр, {total_added} связей за {elapsed:.2f}с")

        return len(updated_movies), skipped_movies

    def _execute_large_batch_update(self) -> int:
        """Выполняет обновление крупного батча (оптимизировано для скорости)"""
        from movies.models import Movie, Keyword, Genre, Theme, PlayerPerspective, GameMode
        from django.utils import timezone
        from django.db import transaction

        try:
            with transaction.atomic():
                movies_in_batch = len(self.movies_to_update)

                # Оптимизированная группировка по типам
                keyword_movies = []
                criteria_movies = []

                for game_data in self.movies_to_update:
                    if game_data['is_keywords']:
                        keyword_movies.append(game_data)
                    else:
                        criteria_movies.append(game_data)

                updated_count = 0

                # Обработка ключевых слов (если есть)
                if keyword_movies:
                    updated_count += self._update_keywords_batch(keyword_movies)

                # Обработка критериев (если есть)
                if criteria_movies:
                    updated_count += self._update_criteria_batch(criteria_movies)

                # Очищаем батч
                self.movies_to_update.clear()

                return updated_count

        except Exception as e:
            if self.verbose:
                print(f"⚠️ Ошибка обновления крупного батча: {e}")
            return 0

    def _execute_small_batch_update(self) -> int:
        """Выполняет обновление небольшого батча (оригинальная логика)"""
        return self._execute_batch_update()

    def _update_keywords_batch(self, keyword_movies):
        """Оптимизированное обновление ключевых слов"""
        from movies.models import Movie, Keyword
        from django.utils import timezone

        updated_count = 0
        skipped_count = 0
        game_ids = [g['game_id'] for g in keyword_movies]

        # Получаем все игры одним запросом (без prefetch_related)
        movies_dict = {Movie.id: Movie for Movie in Movie.objects.filter(id__in=game_ids)}

        # Собираем все ID ключевых слов из всех игр
        all_keyword_ids = []
        movies_with_keywords = []

        for game_data in keyword_movies:
            keywords_data = game_data['results'].get('keywords', {})
            items = keywords_data.get('items', [])
            if items:
                all_keyword_ids.extend([k['id'] for k in items])
                movies_with_keywords.append(game_data)

        if not movies_with_keywords:
            if self.verbose:
                print(f"ℹ️ Нет игр с ключевыми словами для обновления")
            return 0

        # Проверяем, какие ключевые слова действительно существуют в базе
        existing_keyword_ids = set(Keyword.objects.filter(id__in=all_keyword_ids).values_list('id', flat=True))

        if self.verbose:
            print(
                f"🔍 В базе найдено {len(existing_keyword_ids)} ключевых слов из {len(set(all_keyword_ids))} запрошенных")

        # Обрабатываем каждую игру с ключевыми словами
        for game_data in movies_with_keywords:
            try:
                Movie = movies_dict.get(game_data['game_id'])
                if not Movie:
                    if self.verbose:
                        print(f"⚠️ Игра {game_data['game_id']} не найдена в базе")
                    skipped_count += 1
                    continue

                keywords_data = game_data['results'].get('keywords', {})
                items = keywords_data.get('items', [])

                # Получаем ID ключевых слов
                keyword_ids = [k['id'] for k in items]

                # Фильтруем только существующие ключевые слова
                valid_keyword_ids = [kid for kid in keyword_ids if kid in existing_keyword_ids]

                if not valid_keyword_ids:
                    if self.verbose:
                        print(f"⚠️ Для игры {Movie.id} нет валидных ключевых слов в базе")
                    skipped_count += 1
                    continue

                # Получаем существующие ключевые слова из keyword_ids
                existing_game_ids = set(Movie.keyword_ids or [])

                # Находим новые ключевые слова (которых еще нет у игры)
                new_ids = [kid for kid in valid_keyword_ids if kid not in existing_game_ids]

                if not new_ids:
                    skipped_count += 1
                    if self.verbose:
                        print(f"ℹ️ Игра {Movie.id} уже имеет все ключевые слова")
                    continue

                # Обновляем keyword_ids
                Movie.keyword_ids = list(existing_game_ids.union(new_ids))
                Movie.updated_at = timezone.now()
                Movie.save(update_fields=['keyword_ids', 'updated_at'])
                updated_count += 1

                if self.verbose:
                    print(f"✅ Игра {Movie.id} обновлена: добавлено {len(new_ids)} ключевых слов")
                elif updated_count % 10 == 0:
                    print(f"✅ Обновлено {updated_count} игр...")

            except Exception as e:
                if self.verbose:
                    print(f"❌ Ошибка обновления игры {game_data.get('game_id', 'unknown')}: {e}")
                skipped_count += 1
                continue

        if self.verbose:
            print(
                f"📊 Обновлено {updated_count} игр, пропущено {skipped_count} (всего {len(movies_with_keywords)} с ключевыми словами)")

        return updated_count

    def _update_criteria_batch(self, criteria_movies):
        """Оптимизированное обновление критериев"""
        from movies.models import Movie, Genre, Theme, PlayerPerspective, GameMode
        from django.utils import timezone

        updated_count = 0
        game_ids = [g['game_id'] for g in criteria_movies]

        if self.verbose:
            print(f"\n📊 _update_criteria_batch: обрабатываем {len(criteria_movies)} игр")
            print(f"   game_ids: {game_ids}")

        # Получаем все игры одним запросом с префетчингом
        movies_dict = {Movie.id: Movie for Movie in Movie.objects.filter(id__in=game_ids).prefetch_related(
            'genres', 'themes', 'player_perspectives', 'game_modes'
        )}

        if self.verbose:
            print(f"   найдено игр в БД: {len(movies_dict)}")

        for game_data in criteria_movies:
            Movie = movies_dict.get(game_data['game_id'])
            if not Movie:
                if self.verbose:
                    print(f"   ⚠️ Игра {game_data['game_id']} не найдена в БД")
                continue

            if self.verbose:
                print(f"\n   🔍 Обрабатываем игру {Movie.id}: {Movie.name}")
                print(f"   Результаты анализа: {game_data['results'].keys()}")

            added_elements = 0

            # Жанры
            genres = game_data['results'].get('genres', {}).get('items', [])
            if self.verbose:
                print(f"   Найдено жанров: {len(genres)}")
            if genres:
                genre_ids = [g['id'] for g in genres]
                existing_genre_ids = set(Movie.genres.values_list('id', flat=True))
                new_genre_ids = [gid for gid in genre_ids if gid not in existing_genre_ids]

                if new_genre_ids:
                    genre_objects = Genre.objects.filter(id__in=new_genre_ids)
                    if genre_objects.exists():
                        Movie.genres.add(*genre_objects)
                        added_elements += len(new_genre_ids)
                        if self.verbose:
                            print(f"      ✅ Добавлены жанры: {[g.name for g in genre_objects]}")

            # Темы
            themes = game_data['results'].get('themes', {}).get('items', [])
            if self.verbose:
                print(f"   Найдено тем: {len(themes)}")
            if themes:
                theme_ids = [t['id'] for t in themes]
                existing_theme_ids = set(Movie.themes.values_list('id', flat=True))
                new_theme_ids = [tid for tid in theme_ids if tid not in existing_theme_ids]

                if new_theme_ids:
                    theme_objects = Theme.objects.filter(id__in=new_theme_ids)
                    if theme_objects.exists():
                        Movie.themes.add(*theme_objects)
                        added_elements += len(new_theme_ids)
                        if self.verbose:
                            print(f"      ✅ Добавлены темы: {[t.name for t in theme_objects]}")

            # Перспективы
            perspectives = game_data['results'].get('perspectives', {}).get('items', [])
            if self.verbose:
                print(f"   Найдено перспектив: {len(perspectives)}")
            if perspectives:
                perspective_ids = [p['id'] for p in perspectives]
                existing_perspective_ids = set(Movie.player_perspectives.values_list('id', flat=True))
                new_perspective_ids = [pid for pid in perspective_ids if pid not in existing_perspective_ids]

                if new_perspective_ids:
                    perspective_objects = PlayerPerspective.objects.filter(id__in=new_perspective_ids)
                    if perspective_objects.exists():
                        Movie.player_perspectives.add(*perspective_objects)
                        added_elements += len(new_perspective_ids)
                        if self.verbose:
                            print(f"      ✅ Добавлены перспективы: {[p.name for p in perspective_objects]}")

            # Режимы игры
            game_modes = game_data['results'].get('game_modes', {}).get('items', [])
            if self.verbose:
                print(f"   Найдено режимов: {len(game_modes)}")
            if game_modes:
                mode_ids = [m['id'] for m in game_modes]
                existing_mode_ids = set(Movie.game_modes.values_list('id', flat=True))
                new_mode_ids = [mid for mid in mode_ids if mid not in existing_mode_ids]

                if new_mode_ids:
                    mode_objects = GameMode.objects.filter(id__in=new_mode_ids)
                    if mode_objects.exists():
                        Movie.game_modes.add(*mode_objects)
                        added_elements += len(new_mode_ids)
                        if self.verbose:
                            print(f"      ✅ Добавлены режимы: {[m.name for m in mode_objects]}")

            if added_elements > 0:
                updated_count += 1
                # Обновляем время модификации игры
                Movie.updated_at = timezone.now()
                Movie.save(update_fields=['updated_at'])
                if self.verbose:
                    print(f"   ✅ Игра {Movie.id} обновлена: добавлено {added_elements} элементов")
            else:
                if self.verbose:
                    print(f"   ❌ Игра {Movie.id} НЕ обновлена: added_elements = {added_elements}")

        if self.verbose:
            print(f"\n📊 _update_criteria_batch вернул: {updated_count} обновленных игр из {len(criteria_movies)}")
        return updated_count

    @transaction.atomic
    def _execute_batch_update(self) -> int:
        """Выполняет обновление накопленного батча"""
        if not self.movies_to_update:
            return 0

        from movies.models import Movie, Keyword, Genre, Theme, PlayerPerspective, GameMode
        from django.utils import timezone

        # Запоминаем сколько игр в батче
        movies_in_batch = len(self.movies_to_update)

        # Инициализируем прогресс-бар для обновлений
        if not self.verbose:
            self.progress_bar = UnifiedProgressBar(
                total=movies_in_batch,
                desc="Обновление батча",
                bar_length=30,
                update_interval=0.1,
                stat_width=5,
                emoji_spacing=1,
                is_batch=True
            )

        updated_movies_count = 0
        updated_elements_count = 0

        # Получаем все игры одним запросом
        game_ids = [game_data['game_id'] for game_data in self.movies_to_update]
        movies_dict = {Movie.id: Movie for Movie in Movie.objects.filter(id__in=game_ids).prefetch_related(
            'keywords', 'genres', 'themes', 'player_perspectives', 'game_modes'
        )}

        for i, game_data in enumerate(self.movies_to_update):
            try:
                # Обновляем прогресс-бар обновлений
                if self.progress_bar:
                    current_time = time.time()
                    if current_time - self.last_update_time > 0.1 or i == 0:
                        self.progress_bar.update(1)
                        self.last_update_time = current_time

                Movie = movies_dict.get(game_data['game_id'])
                if not Movie:
                    continue

                added_elements = 0

                if game_data['is_keywords']:
                    keywords = game_data['results'].get('keywords', {}).get('items', [])
                    if keywords:
                        keyword_ids = [k['id'] for k in keywords]
                        existing_keyword_ids = set(Movie.keywords.values_list('id', flat=True))
                        new_keyword_ids = [kid for kid in keyword_ids if kid not in existing_keyword_ids]

                        if new_keyword_ids:
                            keyword_objects = Keyword.objects.filter(id__in=new_keyword_ids)
                            if keyword_objects.exists():
                                Movie.keywords.add(*keyword_objects)
                                added_elements += len(new_keyword_ids)
                else:
                    # Жанры
                    genres = game_data['results'].get('genres', {}).get('items', [])
                    if genres:
                        genre_ids = [g['id'] for g in genres]
                        existing_genre_ids = set(Movie.genres.values_list('id', flat=True))
                        new_genre_ids = [gid for gid in genre_ids if gid not in existing_genre_ids]

                        if new_genre_ids:
                            genre_objects = Genre.objects.filter(id__in=new_genre_ids)
                            if genre_objects.exists():
                                Movie.genres.add(*genre_objects)
                                added_elements += len(new_genre_ids)

                    # Темы
                    themes = game_data['results'].get('themes', {}).get('items', [])
                    if themes:
                        theme_ids = [t['id'] for t in themes]
                        existing_theme_ids = set(Movie.themes.values_list('id', flat=True))
                        new_theme_ids = [tid for tid in theme_ids if tid not in existing_theme_ids]

                        if new_theme_ids:
                            theme_objects = Theme.objects.filter(id__in=new_theme_ids)
                            if theme_objects.exists():
                                Movie.themes.add(*theme_objects)
                                added_elements += len(new_theme_ids)

                    # Перспективы
                    perspectives = game_data['results'].get('perspectives', {}).get('items', [])
                    if perspectives:
                        perspective_ids = [p['id'] for p in perspectives]
                        existing_perspective_ids = set(Movie.player_perspectives.values_list('id', flat=True))
                        new_perspective_ids = [pid for pid in perspective_ids if pid not in existing_perspective_ids]

                        if new_perspective_ids:
                            perspective_objects = PlayerPerspective.objects.filter(id__in=new_perspective_ids)
                            if perspective_objects.exists():
                                Movie.player_perspectives.add(*perspective_objects)
                                added_elements += len(new_perspective_ids)

                    # Режимы игры
                    game_modes = game_data['results'].get('game_modes', {}).get('items', [])
                    if game_modes:
                        mode_ids = [m['id'] for m in game_modes]
                        existing_mode_ids = set(Movie.game_modes.values_list('id', flat=True))
                        new_mode_ids = [mid for mid in mode_ids if mid not in existing_mode_ids]

                        if new_mode_ids:
                            mode_objects = GameMode.objects.filter(id__in=new_mode_ids)
                            if mode_objects.exists():
                                Movie.game_modes.add(*mode_objects)
                                added_elements += len(new_mode_ids)

                if added_elements > 0:
                    updated_movies_count += 1
                    updated_elements_count += added_elements
                    Movie._needs_save = True

            except Exception:
                pass

        # Batch save всех измененных игр
        movies_to_save = [Movie for Movie in movies_dict.values() if hasattr(Movie, '_needs_save') and Movie._needs_save]
        if movies_to_save:
            # Обновляем поле updated_at на текущее время
            current_time = timezone.now()
            for Movie in movies_to_save:
                Movie.updated_at = current_time

            # Массово сохраняем игры с обновленным полем updated_at
            Movie.objects.bulk_update(movies_to_save, ['updated_at'])

        # Завершаем прогресс-бар обновлений
        if self.progress_bar:
            final_message = None
            if updated_movies_count > 0:
                final_message = f"💾 Обновлено {updated_movies_count} игр ({updated_elements_count} элементов)"
            else:
                final_message = "💾 Игры не нуждались в обновлении"

            self.progress_bar.finish(final_message)
            self.progress_bar = None

        # Очищаем батч
        self.movies_to_update.clear()

        return updated_movies_count