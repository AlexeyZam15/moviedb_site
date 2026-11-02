# movies/analyze/game_analyzer_api.py
"""
Главный API класс для анализа игр - УПРОЩЕННАЯ ВЕРСИЯ
Только анализ, без логики подготовки текста
"""

import time
from typing import Dict, Any, List, Optional

from movies.models import Movie
from .text_analyzer import TextAnalyzer
from .utils import update_game_criteria
from .sync_patterns_to_db import ensure_patterns_in_db
from .range_cache import RangeCacheManager
from django.utils import timezone


class GameAnalyzerAPI:
    """Главный API для анализа игр с оптимизированными ключевыми словами"""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.debug = False
        self.text_analyzer = TextAnalyzer(verbose=verbose)
        self.text_analyzer.debug = self.debug
        self.force_restart = False

        if verbose:
            print("=== Инициализация GameAnalyzerAPI ===")
            print("=== Проверяем наличие паттернов в базе данных ===")

        ensure_patterns_in_db(verbose=verbose)

        # СИНХРОННАЯ загрузка Trie при инициализации, чтобы не тормозить первую игру
        if verbose:
            print("=== Предзагружаем Trie ключевых слов ===")
        self.text_analyzer._ensure_trie_loaded()
        if verbose:
            print("=== Trie загружен ===")

    def mark_new_keywords_added(self):
        """Вызывать при добавлении новых ключевых слов - очищает кэш Trie"""
        # Очищаем кэш Trie
        from .keyword_trie import KeywordTrieManager
        KeywordTrieManager().clear_cache()

        # Также помечаем критерии как новые
        self.mark_new_criteria_added('keywords')

        if self.verbose:
            print("⚠️ Кэш Trie ключевых слов очищен (добавлены новые ключевые слова)")

    def _preload_trie_async(self):
        """Асинхронная предзагрузка Trie для быстрого старта"""
        import threading

        def load_trie():
            try:
                self.text_analyzer._ensure_trie_loaded()
            except Exception:
                pass

        # Запускаем в фоновом потоке
        thread = threading.Thread(target=load_trie)
        thread.daemon = True
        thread.start()

    def analyze_game_text(
            self,
            text: str,
            game_id: Optional[int] = None,
            analyze_keywords: bool = False,
            existing_game=None,
            detailed_patterns: bool = False,
            exclude_existing: bool = False
    ) -> Dict[str, Any]:
        """
        ОПТИМИЗИРОВАННЫЙ: Анализирует текст игры с поддержкой кэша и быстрыми ключевыми словами
        """
        start_time = time.time()

        if not text:
            return {
                'success': False,
                'error': 'Пустой текст для анализа',
                'game_id': game_id,
                'processing_time': time.time() - start_time,
                'has_results': False
            }

        # ПРОВЕРКА КЭША
        should_use_cache = (
                game_id and
                not self.verbose and
                not exclude_existing
        )

        if should_use_cache and RangeCacheManager.is_game_checked(game_id):
            return {
                'success': True,
                'error': None,
                'processing_time': 0.001,
                'text_length': len(text),
                'analysis_mode': 'keywords' if analyze_keywords else 'criteria',
                'results': {},
                'summary': {'found_count': 0, 'has_results': False, 'mode': 'cached'},
                'has_results': False,
                'exclude_existing': exclude_existing,
                'cached': True,
                'game_id': game_id,
            }

        # ВЫБОР МЕТОДА АНАЛИЗА
        if analyze_keywords:
            # Используем оптимизированный метод анализа ключевых слов
            # text_analyzer уже использует Trie внутри analyze() метода
            analysis_result = self.text_analyzer.analyze(
                text=text,
                analyze_keywords=True,
                existing_game=existing_game,
                detailed_patterns=detailed_patterns,
                exclude_existing=exclude_existing
            )
        else:
            # Анализ критериев
            analysis_result = self.text_analyzer.analyze(
                text=text,
                analyze_keywords=False,
                existing_game=existing_game,
                detailed_patterns=detailed_patterns,
                exclude_existing=exclude_existing
            )

        processing_time = time.time() - start_time

        # Формируем ответ
        response = {
            'success': analysis_result.get('success', True),
            'error': analysis_result.get('error'),
            'processing_time': processing_time,
            'text_length': len(text),
            'analysis_mode': 'keywords' if analyze_keywords else 'criteria',
            'results': analysis_result.get('results', {}),
            'summary': analysis_result.get('summary', {
                'found_count': 0,
                'has_results': False
            }),
            'has_results': analysis_result.get('has_results', False),
            'exclude_existing': exclude_existing,
            'cached': False
        }

        if detailed_patterns and 'pattern_info' in analysis_result:
            response['pattern_info'] = analysis_result['pattern_info']

        # ОБНОВЛЕНИЕ КЭША
        if response['success'] and game_id and not self.verbose and not exclude_existing:
            RangeCacheManager.update_game_range(game_id, game_id)
            response['cached'] = True

        if game_id:
            response['game_id'] = game_id

        return response

    def analyze_game_text_comprehensive(
            self,
            text: str,
            game_id: Optional[int] = None,
            existing_game=None,
            detailed_patterns: bool = True,
            exclude_existing: bool = False
    ) -> Dict[str, Any]:
        """
        ОПТИМИЗИРОВАННЫЙ: Комплексный анализ с быстрыми ключевыми словами
        """
        start_time = time.time()

        if not text:
            return {
                'success': False,
                'error': 'Пустой текст для анализа',
                'game_id': game_id,
                'processing_time': time.time() - start_time,
                'has_results': False
            }

        # ПРОВЕРКА КЭША
        if game_id and not self.verbose:
            if RangeCacheManager.is_game_checked(game_id):
                return {
                    'success': True,
                    'error': None,
                    'processing_time': 0.001,
                    'text_length': len(text),
                    'analysis_mode': 'comprehensive',
                    'results': {},
                    'summary': {
                        'found_count': 0,
                        'has_results': False,
                        'mode': 'cached',
                        'total_matches': 0
                    },
                    'pattern_info': {},
                    'has_results': False,
                    'total_matches': 0,
                    'cached': True,
                    'game_id': game_id,
                    'message': f'Игра {game_id} уже проверена (используется кэш)'
                }

        # Используем оптимизированный комплексный анализ
        analysis_result = self.text_analyzer.analyze_comprehensive(
            text=text,
            existing_game=existing_game,
            detailed_patterns=detailed_patterns,
            exclude_existing=exclude_existing
        )

        response = {
            'success': analysis_result.get('success', False),
            'error': analysis_result.get('error'),
            'processing_time': time.time() - start_time,
            'text_length': len(text),
            'analysis_mode': 'comprehensive',
            'results': analysis_result.get('results', {}),
            'summary': analysis_result.get('summary', {}),
            'pattern_info': analysis_result.get('pattern_info', {}),
            'has_results': analysis_result.get('has_results', False),
            'total_matches': analysis_result.get('total_matches', 0),
            'cached': False
        }

        # ДОБАВЛЯЕМ КЭШИРОВАНИЕ
        if response['success'] and game_id and not self.verbose:
            RangeCacheManager.update_game_range(game_id, game_id)

        if game_id:
            response['game_id'] = game_id

        return response

    def clear_all_cache(self):
        """Очищает весь кэш анализатора и диапазонов"""
        # Очищаем кэш анализатора текста
        self.text_analyzer.clear_cache()

        # Очищаем кэш диапазонов
        RangeCacheManager.clear_all_cache()

        if self.verbose:
            print("✅ Весь кэш анализатора очищен")

    def force_analyze_game_text(
            self,
            text: str,
            game_id: Optional[int] = None,
            analyze_keywords: bool = False,
            existing_game=None,
            detailed_patterns: bool = False,
            exclude_existing: bool = True
    ) -> Dict[str, Any]:
        """
        Принудительный анализ текста игры (игнорирует кэш)
        """
        start_time = time.time()

        if not text:
            return {
                'success': False,
                'error': 'Пустой текст для анализа',
                'game_id': game_id,
                'processing_time': time.time() - start_time,
                'has_results': False
            }

        # Отладка только если включен debug
        if self.debug:
            import sys
            sys.stderr.write(f"\n=== ОТЛАДКА force_analyze_game_text ===\n")
            sys.stderr.write(f"game_id: {game_id}\n")
            sys.stderr.write(f"analyze_keywords: {analyze_keywords}\n")
            sys.stderr.write(f"existing_game: {existing_game.id if existing_game else None}\n")
            sys.stderr.write(f"detailed_patterns: {detailed_patterns}\n")
            sys.stderr.write(f"exclude_existing: {exclude_existing}\n")
            sys.stderr.flush()

        # ВРЕМЕННО отключаем verbose во время анализа
        original_verbose = self.verbose
        self.verbose = False

        try:
            # ВСЕГДА используем analyze_comprehensive для получения pattern_info
            if self.debug:
                import sys
                sys.stderr.write("→ вызываем analyze_comprehensive\n")
                sys.stderr.flush()

            analysis_result = self.text_analyzer.analyze_comprehensive(
                text=text,
                existing_game=existing_game,
                detailed_patterns=detailed_patterns,
                exclude_existing=exclude_existing
            )

            # Если нужны только ключевые слова - фильтруем результаты
            if analyze_keywords and 'keywords' in analysis_result.get('results', {}):
                analysis_result['results'] = {'keywords': analysis_result['results']['keywords']}

            # Если нужны только критерии - убираем ключевые слова из результатов
            elif not analyze_keywords and 'keywords' in analysis_result.get('results', {}):
                # Создаем копию results без keywords
                filtered_results = {}
                for key, value in analysis_result['results'].items():
                    if key != 'keywords':
                        filtered_results[key] = value
                analysis_result['results'] = filtered_results

            processing_time = time.time() - start_time

            # Получаем pattern_info из результата анализа
            pattern_info = analysis_result.get('pattern_info', {})

            # Убеждаемся, что pattern_info - это словарь
            if not isinstance(pattern_info, dict):
                pattern_info = {}

            # Формируем стандартизированный ответ
            response = {
                'success': analysis_result.get('success', True),
                'error': analysis_result.get('error'),
                'processing_time': processing_time,
                'text_length': len(text),
                'analysis_mode': 'keywords' if analyze_keywords else 'criteria',
                'results': analysis_result.get('results', {}),
                'summary': analysis_result.get('summary', {
                    'found_count': 0,
                    'has_results': False
                }),
                'pattern_info': pattern_info,  # Всегда словарь
                'has_results': analysis_result.get('has_results', False),
                'exclude_existing': exclude_existing,
                'cached': False,
                'force_analysis': True,
                'bypass_cache': True,
                'analyzed_text': text
            }

            # Добавляем ID игры
            if game_id:
                response['game_id'] = game_id

            if self.debug:
                import sys
                sys.stderr.write(f"→ response keys: {list(response.keys())}\n")
                sys.stderr.write(f"→ pattern_info type: {type(response['pattern_info'])}\n")
                sys.stderr.write(f"→ pattern_info keys: {list(response['pattern_info'].keys())}\n")
                sys.stderr.write(f"→ has_results: {response['has_results']}\n")
                sys.stderr.flush()

            return response

        finally:
            # Восстанавливаем original_verbose
            self.verbose = original_verbose

    def _analyze_criteria_only(
            self,
            text: str,
            existing_game=None,
            detailed_patterns: bool = False,
            exclude_existing: bool = True
    ) -> Dict[str, Any]:
        """Быстрый анализ ТОЛЬКО критериев (жанры, темы) БЕЗ ключевых слов."""
        start_time = time.time()

        if len(text) > 5000:
            text = text[:5000]

        if not text:
            return {
                'success': False,
                'error': 'Empty text',
                'results': {},
                'summary': {'found_count': 0, 'has_results': False},
                'processing_time': time.time() - start_time,
                'has_results': False
            }

        text_lower = text.lower()

        from .pattern_manager import PatternManager
        patterns = PatternManager.get_all_patterns()

        existing_items = {}
        if existing_game and exclude_existing:
            existing_items = {
                'genres': set(existing_game.genres.values_list('name', flat=True)),
                'themes': set(existing_game.themes.values_list('name', flat=True)),
            }

        results = {}
        pattern_info = {}
        total_found = 0

        for criteria_type in ['genres', 'themes']:
            model = self._get_model_for_criteria(criteria_type)
            found_items = []
            patterns_for_type = patterns[criteria_type]

            for name, pattern_list in patterns_for_type.items():
                if exclude_existing:
                    existing_names_lower = {n.lower() for n in existing_items.get(criteria_type, set())}
                    if name.lower() in existing_names_lower:
                        continue

                for pattern in pattern_list:
                    if pattern.search(text_lower):
                        try:
                            obj = model.objects.filter(name__iexact=name).first()
                            if obj and obj not in found_items:
                                found_items.append(obj)
                                break
                        except Exception:
                            pass

            if found_items:
                results[criteria_type] = {
                    'count': len(found_items),
                    'items': [{'id': i.id, 'name': i.name} for i in found_items]
                }
                total_found += len(found_items)

        processing_time = time.time() - start_time

        return {
            'success': True,
            'results': results,
            'summary': {
                'found_count': total_found,
                'has_results': total_found > 0,
                'mode': 'criteria_only'
            },
            'has_results': total_found > 0,
            'processing_time': processing_time
        }

    def _get_model_for_criteria(self, criteria_type: str):
        """Возвращает модель для типа критерия"""
        from movies.models import Genre, Theme

        models = {
            'genres': Genre,
            'themes': Theme,
        }
        return models.get(criteria_type)

    def clear_analysis_cache(self):
        """Очищает кэш анализатора"""
        # Очищаем кэш анализатора текста
        self.text_analyzer.clear_cache()

        # Очищаем кэш диапазонов
        RangeCacheManager.clear_all_cache()

        if self.verbose:
            print("✅ Весь кэш анализатора очищен")

    def analyze_game_text_combined(
            self,
            text: str,
            game_id: Optional[int] = None,
            existing_game=None,
            detailed_patterns: bool = False,
            exclude_existing: bool = False
    ) -> Dict[str, Any]:
        """Анализирует текст игры в комбинированном режиме (критерии + ключевые слова)."""
        start_time = time.time()

        if not text:
            return {
                'success': False,
                'error': 'Пустой текст для анализа',
                'game_id': game_id,
                'processing_time': time.time() - start_time,
                'has_results': False
            }

        if game_id and not self.verbose and not exclude_existing:
            if RangeCacheManager.is_game_checked(game_id):
                if self.verbose:
                    print(f"ℹ️ Игра {game_id} уже проверена, возвращаем пустой результат из кэша")

                return {
                    'success': True,
                    'error': None,
                    'processing_time': 0.001,
                    'text_length': len(text),
                    'analysis_mode': 'combined',
                    'results': {},
                    'summary': {
                        'found_count': 0,
                        'has_results': False,
                        'mode': 'cached'
                    },
                    'has_results': False,
                    'exclude_existing': exclude_existing,
                    'cached': True,
                    'game_id': game_id,
                    'message': f'Игра {game_id} уже проверена (используется кэш)'
                }

        if self.verbose:
            print(f"=== GameAnalyzerAPI.analyze_game_text_combined: Starting combined analysis")
            print(f"=== Movie ID: {game_id}")
            print(f"=== Exclude existing: {exclude_existing}")
            print(f"=== Text length: {len(text)}")

        criteria_result = self.text_analyzer.analyze(
            text=text,
            analyze_keywords=False,
            existing_game=existing_game,
            detailed_patterns=detailed_patterns,
            exclude_existing=exclude_existing
        )

        keywords_result = self.text_analyzer.analyze(
            text=text,
            analyze_keywords=True,
            existing_game=existing_game,
            detailed_patterns=detailed_patterns,
            exclude_existing=exclude_existing
        )

        combined_results = {}
        if criteria_result.get('success'):
            criteria_data = criteria_result.get('results', {})
            combined_results.update(criteria_data)

        if keywords_result.get('success'):
            keywords_data = keywords_result.get('results', {})
            if 'keywords' in keywords_data:
                combined_results['keywords'] = keywords_data['keywords']

        combined_pattern_info = {}
        if detailed_patterns:
            if criteria_result.get('pattern_info'):
                combined_pattern_info.update(criteria_result['pattern_info'])
            if keywords_result.get('pattern_info'):
                combined_pattern_info['keywords'] = keywords_result['pattern_info'].get('keywords', [])

        total_found = 0
        for category in ['genres', 'themes', 'keywords']:
            if category in combined_results:
                total_found += combined_results[category].get('count', 0)

        response = {
            'success': criteria_result.get('success', False) and keywords_result.get('success', False),
            'error': criteria_result.get('error') or keywords_result.get('error'),
            'processing_time': time.time() - start_time,
            'text_length': len(text),
            'analysis_mode': 'combined',
            'results': combined_results,
            'summary': {
                'found_count': total_found,
                'has_results': total_found > 0,
                'mode': 'combined',
                'exclude_existing': exclude_existing
            },
            'has_results': total_found > 0,
            'exclude_existing': exclude_existing,
            'cached': False
        }

        if detailed_patterns and combined_pattern_info:
            response['pattern_info'] = combined_pattern_info

        if response['success'] and game_id and not self.verbose and not exclude_existing:
            RangeCacheManager.update_game_range(game_id, game_id)
            if self.verbose:
                print(f"✅ Кэш обновлен для игры {game_id}")

        if game_id:
            response['game_id'] = game_id

        if self.verbose:
            print(f"=== Combined analysis completed. Success: {response['success']}")
            print(f"=== Has results: {response['has_results']}")
            print(f"=== Found count: {total_found}")
            print(f"=== Exclude existing: {exclude_existing}")
            print(f"=== Cached: {response.get('cached', False)}")

        return response

    def mark_new_movies_added(self):
        """Вызывать при добавлении новых игр - помечает все игры как непроверенные"""
        RangeCacheManager.mark_all_movies_as_unchecked()

        if self.verbose:
            print("⚠️ Все игры помечены как непроверенные (добавлены новые игры)")

    def mark_new_criteria_added(self, category: str):
        """Вызывать при добавлении новых критериев - помечает категорию как непроверенную"""
        valid_categories = ['genres', 'themes', 'keywords']
        if category in valid_categories:
            RangeCacheManager.mark_criteria_as_new(category)
            if self.verbose:
                print(f"⚠️ Категория {category} помечена как непроверенная (добавлены новые критерии)")
        else:
            if self.verbose:
                print(f"❌ Неизвестная категория: {category}")

    def update_game_with_combined_results(
            self,
            game_id: int,
            results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Обновляет игру с результатами комбинированного анализа."""
        try:
            Movie = Movie.objects.get(id=game_id)

            updated_categories = []
            total_updated = 0

            for category, data in results.items():
                if category == 'keywords':
                    keywords = data.get('items', [])
                    if keywords:
                        keyword_ids = [k['id'] for k in keywords]
                        from movies.models import Keyword
                        keyword_objects = Keyword.objects.filter(id__in=keyword_ids)
                        Movie.keywords.add(*keyword_objects)
                        updated_categories.append(f"{len(keyword_objects)} keywords")
                        total_updated += len(keyword_objects)

                elif category == 'genres':
                    genres = data.get('items', [])
                    if genres:
                        genre_ids = [g['id'] for g in genres]
                        from movies.models import Genre
                        genre_objects = Genre.objects.filter(id__in=genre_ids)
                        Movie.genres.add(*genre_objects)
                        updated_categories.append(f"{len(genre_objects)} genres")
                        total_updated += len(genre_objects)

                elif category == 'themes':
                    themes = data.get('items', [])
                    if themes:
                        theme_ids = [t['id'] for t in themes]
                        from movies.models import Theme
                        theme_objects = Theme.objects.filter(id__in=theme_ids)
                        Movie.themes.add(*theme_objects)
                        updated_categories.append(f"{len(theme_objects)} themes")
                        total_updated += len(theme_objects)

            if total_updated > 0:
                Movie.save()  # вызовет update_materialized_vectors()

                return {
                    'success': True,
                    'game_id': game_id,
                    'game_name': Movie.name,
                    'updated': True,
                    'total_updated': total_updated,
                    'updated_categories': updated_categories,
                    'message': f'Successfully added {total_updated} elements to Movie'
                }
            else:
                return {
                    'success': True,
                    'game_id': game_id,
                    'game_name': Movie.name,
                    'updated': False,
                    'message': 'No new elements to add'
                }

        except Movie.DoesNotExist:
            return {
                'success': False,
                'error': f'Игра с ID {game_id} не найдена'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'game_id': game_id
            }

    def update_game_with_results(
            self,
            game_id: int,
            results: Dict[str, Any],
            is_keywords: bool
    ) -> Dict[str, Any]:
        """
        Обновляет игру с результатами анализа

        Args:
            game_id: ID игры
            results: Результаты анализа
            is_keywords: Обновлять ключевые слова или критерии

        Returns:
            Результат обновления
        """
        try:
            Movie = Movie.objects.get(id=game_id)

            updated = update_game_criteria(
                Movie=Movie,
                results=results,
                is_keywords=is_keywords
            )

            return {
                'success': True,
                'game_id': game_id,
                'game_name': Movie.name,
                'updated': updated,
                'current_criteria': self._get_current_criteria(Movie, is_keywords)
            }

        except Movie.DoesNotExist:
            return {
                'success': False,
                'error': f'Игра с ID {game_id} не найдена'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'game_id': game_id
            }

    def analyze_batch(
            self,
            movies_data: List[Dict],
            analyze_keywords: bool = False,
            detailed_patterns: bool = False
    ) -> Dict[str, Any]:
        """
        Анализирует несколько игр

        Args:
            movies_data: Список словачей с данными игр {'id': int, 'text': str, 'existing_game': Movie}
            analyze_keywords: Анализировать ключевые слова
            detailed_patterns: Подробная информация о паттернах

        Returns:
            Результаты анализа
        """
        start_time = time.time()
        results = []
        stats = {
            'total': len(movies_data),
            'processed': 0,
            'with_text': 0,
            'with_results': 0,
            'total_found': 0,
            'errors': 0
        }

        for game_data in movies_data:
            try:
                text = game_data.get('text', '')

                if not text:
                    results.append({
                        'game_id': game_data['id'],
                        'success': False,
                        'error': 'Нет текста'
                    })
                    continue

                stats['with_text'] += 1

                # Анализируем
                analysis_result = self.analyze_game_text(
                    text=text,
                    game_id=game_data['id'],
                    analyze_keywords=analyze_keywords,
                    existing_game=game_data.get('existing_game'),
                    detailed_patterns=detailed_patterns
                )

                if analysis_result['success']:
                    stats['processed'] += 1

                    if analysis_result['has_results']:
                        stats['with_results'] += 1
                        stats['total_found'] += analysis_result['summary'].get('found_count', 0)

                results.append(analysis_result)

            except Exception as e:
                stats['errors'] += 1
                results.append({
                    'game_id': game_data.get('id'),
                    'success': False,
                    'error': str(e)
                })
                continue

        return {
            'success': True,
            'processing_time': time.time() - start_time,
            'statistics': stats,
            'results': results
        }

    def _get_current_criteria(self, Movie: Movie, is_keywords: bool) -> Dict[str, List]:
        """Возвращает текущие критерии игры"""
        if is_keywords:
            return {
                'keywords': list(Movie.keywords.values('id', 'name'))
            }
        else:
            return {
                'genres': list(Movie.genres.values('id', 'name')),
                'themes': list(Movie.themes.values('id', 'name')),
            }