# movies/management/commands/analyze_game_criteria_fast_src/analyzer.py

import os
import sys
import re
import threading
from typing import Dict, Any, List

from movies.models import Movie, Genre, Theme


class AnalyzerMixin:
    """Анализ одного фильма (критерии или ключевые слова)."""

    def _get_game_text(self, Movie_obj) -> str:
        """Максимально быстрое получение текста.

        В TMDB-модели доступны только summary и tagline.
        """
        parts = []
        if Movie_obj.summary:
            parts.append(Movie_obj.summary)
        if Movie_obj.tagline:
            parts.append(Movie_obj.tagline)
        return ' '.join(parts)

    def _get_keyword_trie(self):
        """Ленивая потокобезопасная инициализация KeywordTrie (один раз на процесс)."""
        if getattr(self, '_keyword_trie_initialized', False):
            return getattr(self, '_keyword_trie', None)

        lock = getattr(self, '_keyword_trie_lock', None)
        if lock is None:
            lock = threading.Lock()
            self._keyword_trie_lock = lock

        with lock:
            if getattr(self, '_keyword_trie_initialized', False):
                return getattr(self, '_keyword_trie', None)

            keyword_ids_filter = getattr(self, 'keyword_ids_filter', None)
            trie = None

            if keyword_ids_filter is not None:
                try:
                    from movies.analyze.keyword_trie import KeywordTrieManager
                    trie_manager = KeywordTrieManager()
                    trie = trie_manager.get_trie(
                        verbose=False,
                        keyword_ids=keyword_ids_filter,
                    )
                except TypeError:
                    sys.stderr.write(
                        f"   ℹ️ KeywordTrieManager не поддерживает keyword_ids — "
                        f"используем прямой поиск по {len(keyword_ids_filter)} ключевым словам\n"
                    )
                    sys.stderr.flush()
                    trie = None
                except Exception as e:
                    sys.stderr.write(
                        f"   ⚠️ Ошибка построения Trie с фильтром: {e} — "
                        f"используем прямой поиск\n"
                    )
                    sys.stderr.flush()
                    trie = None
            else:
                try:
                    from movies.analyze.keyword_trie import KeywordTrieManager
                    trie_manager = KeywordTrieManager()
                    trie = trie_manager.get_trie(verbose=False)
                except Exception as e:
                    sys.stderr.write(f"   ⚠️ Ошибка построения Trie: {e}\n")
                    sys.stderr.flush()
                    trie = None

            self._keyword_trie = trie
            self._keyword_trie_initialized = True
            return trie

    def _get_stopword_pattern_cache(self) -> dict:
        local = getattr(self, '_stopword_cache_local', None)
        if local is None:
            local = threading.local()
            self._stopword_cache_local = local
        cache = getattr(local, 'cache', None)
        if cache is None:
            cache = {}
            local.cache = cache
        return cache

    def _debug_keyword_game_id(self) -> int:
        try:
            return int(os.environ.get('DEBUG_KEYWORD_GAME_ID', '0') or '0')
        except Exception:
            return 0

    def _analyze_game_fast(self, game_dict: Dict, existing_relations: Dict[str, set] = None) -> Dict[str, Any]:
        """Максимально быстрый анализ одного фильма с проверкой стоп-слов на уровне критерия.

        В TMDB-модели: только genres/themes/keywords. Нет perspectives/game_modes.
        """
        collect_details = bool(getattr(self, 'collect_pattern_details', False))

        # Текст: только summary (+ tagline), как в TextPreparer.
        summary = game_dict.get('summary', '') or ''
        tagline = game_dict.get('tagline', '') or ''
        if summary or tagline:
            text = f"{summary} {tagline}".strip()
        else:
            text = ''

        if not text or len(text.strip()) < 10:
            return {
                'id': game_dict['id'],
                'name': game_dict['name'],
                'has_results': False,
                'skipped': True,
                'reason': 'no_text',
                'count': 0,
                'found': {'genres': [], 'themes': [], 'keywords': []},
                'pattern_info': {},
                'has_new': False
            }

        text_lower = text.lower()
        game_id = game_dict['id']
        debug_game_id = self._debug_keyword_game_id()

        if self.keywords_mode:
            trie = self._get_keyword_trie()

            found_ids = set()
            pattern_info = {'keywords': []}

            if trie is not None:
                trie_results = trie.find_all_in_text(text, unique_only=True)

                for result in trie_results:
                    keyword_id = result['id']
                    if self.keyword_ids_filter is not None and keyword_id not in self.keyword_ids_filter:
                        continue
                    if keyword_id not in found_ids:
                        found_ids.add(keyword_id)
                        if collect_details:
                            pattern_info['keywords'].append({
                                'name': result['name'],
                                'matched_text': result['text'],
                                'position': result['position'],
                                'status': 'found',
                                'pattern': 'trie_match'
                            })
            else:
                keywords_map = self.criteria_by_id.get('keywords', {})
                for kw_id, kw_name in keywords_map.items():
                    if self.keyword_ids_filter is not None and kw_id not in self.keyword_ids_filter:
                        continue
                    if not kw_name:
                        continue
                    kw_name_lower = kw_name.lower()
                    if kw_name_lower in text_lower:
                        if kw_id not in found_ids:
                            found_ids.add(kw_id)
                            if collect_details:
                                pos = text_lower.find(kw_name_lower)
                                pattern_info['keywords'].append({
                                    'name': kw_name,
                                    'matched_text': kw_name,
                                    'position': pos if pos >= 0 else 0,
                                    'status': 'found',
                                    'pattern': 'direct_match'
                                })

            has_new = False
            found = {'genres': [], 'themes': [], 'keywords': []}

            existing_keywords_for_game = None
            if found_ids:
                if existing_relations:
                    keywords_by_game = existing_relations.get('keywords_by_game')
                    if keywords_by_game is not None:
                        existing_keywords_for_game = keywords_by_game.get(game_id, set())

                if debug_game_id and game_id == debug_game_id:
                    try:
                        sys.stderr.write(
                            f"\n[DEBUG_KW] game_id={game_id}, name={game_dict.get('name')!r}, "
                            f"found_ids={len(found_ids)}, "
                            f"existing_keywords_for_game="
                            f"{'None' if existing_keywords_for_game is None else len(existing_keywords_for_game)}, "
                            f"keywords_by_game_has_game="
                            f"{bool(existing_relations and existing_relations.get('keywords_by_game') is not None and game_id in existing_relations['keywords_by_game'])}\n"
                        )
                        if existing_keywords_for_game:
                            sample_existing = sorted(existing_keywords_for_game)[:5]
                            sys.stderr.write(f"[DEBUG_KW] sample existing ids: {sample_existing}\n")
                        sample_found = sorted(found_ids)[:5]
                        sys.stderr.write(f"[DEBUG_KW] sample found ids: {sample_found}\n")
                        sys.stderr.flush()
                    except Exception:
                        pass

                if existing_keywords_for_game:
                    for kw_id in found_ids:
                        is_new = kw_id not in existing_keywords_for_game
                        if is_new:
                            has_new = True
                        found['keywords'].append({
                            'id': kw_id,
                            'name': self.criteria_by_id['keywords'].get(kw_id, 'Unknown'),
                            'is_new': is_new
                        })
                elif existing_relations and 'keywords' in existing_relations and existing_relations['keywords']:
                    for kw_id in found_ids:
                        is_new = (game_id, kw_id) not in existing_relations['keywords']
                        if is_new:
                            has_new = True
                        found['keywords'].append({
                            'id': kw_id,
                            'name': self.criteria_by_id['keywords'].get(kw_id, 'Unknown'),
                            'is_new': is_new
                        })
                elif self.update_game:
                    from django.db import connection
                    movie_table = Movie._meta.db_table  # 'movies_movie'
                    with connection.cursor() as cursor:
                        cursor.execute(f"SELECT keyword_ids FROM {movie_table} WHERE id = %s", [game_id])
                        row = cursor.fetchone()
                        existing_keyword_ids = set(row[0] or []) if row else set()

                    if debug_game_id and game_id == debug_game_id:
                        try:
                            sys.stderr.write(
                                f"[DEBUG_KW] (db fallback) game_id={game_id}, "
                                f"db keyword_ids={len(existing_keyword_ids)}\n"
                            )
                            sys.stderr.flush()
                        except Exception:
                            pass

                    for kw_id in found_ids:
                        is_new = kw_id not in existing_keyword_ids
                        if is_new:
                            has_new = True
                        found['keywords'].append({
                            'id': kw_id,
                            'name': self.criteria_by_id['keywords'].get(kw_id, 'Unknown'),
                            'is_new': is_new
                        })
                else:
                    for kw_id in found_ids:
                        found['keywords'].append({
                            'id': kw_id,
                            'name': self.criteria_by_id['keywords'].get(kw_id, 'Unknown'),
                            'is_new': True
                        })
                    has_new = len(found_ids) > 0

                if debug_game_id and game_id == debug_game_id:
                    try:
                        sys.stderr.write(
                            f"[DEBUG_KW] RESULT game_id={game_id}: found={len(found_ids)}, "
                            f"has_new={has_new}, "
                            f"new_count={sum(1 for x in found['keywords'] if x.get('is_new'))}\n"
                        )
                        sys.stderr.flush()
                    except Exception:
                        pass

            return {
                'id': game_id,
                'name': game_dict['name'],
                'has_results': len(found_ids) > 0,
                'skipped': False,
                'count': len(found_ids),
                'found': found,
                'pattern_info': pattern_info,
                'has_new': has_new
            }

        # ========== ОБЫЧНЫЙ РЕЖИМ ==========
        found_ids = {
            'genres': set(),
            'themes': set(),
        }

        pattern_info = {
            'genres': [],
            'themes': [],
        }

        occupied_positions = []
        processed_criteria = {
            'genres': set(),
            'themes': set(),
        }

        total_found = 0

        def is_position_occupied(start, end, occupied_list):
            for occ_start, occ_end in occupied_list:
                if not (end <= occ_start or start >= occ_end):
                    return True
            return False

        def get_sentence_context(full_text, match_start, match_end):
            sentence_start = match_start
            while sentence_start > 0:
                prev_char = full_text[sentence_start - 1]
                if prev_char in '.!?':
                    break
                sentence_start -= 1

            sentence_end = match_end
            while sentence_end < len(full_text):
                if full_text[sentence_end] in '.!?':
                    sentence_end += 1
                    break
                sentence_end += 1

            sentence = full_text[sentence_start:sentence_end].strip()

            if len(sentence) > 500:
                context_before = max(0, match_start - 100)
                context_after = min(len(full_text), match_end + 100)
                sentence = full_text[context_before:context_after]
                if context_before > 0:
                    sentence = "..." + sentence
                if context_after < len(full_text):
                    sentence = sentence + "..."

            return sentence

        def has_negation_before(text, match_start):
            negations = {'not', "isn't", 'aren\'t', 'wasn\'t', 'weren\'t', 'no', 'never', 'nor', 'without'}
            before_start = max(0, match_start - 30)
            before_text = text[before_start:match_start].lower()

            for neg in negations:
                if neg in before_text:
                    return True
            return False

        pattern_cache = self._get_stopword_pattern_cache()

        def has_stop_word_in_text(full_text_lower: str, stop_words: list) -> bool:
            if not stop_words:
                return False

            for stop_word in stop_words:
                is_regex = False

                if any(regex_char in stop_word for regex_char in r'\.*+?{}[]()|^$\\'):
                    if stop_word not in pattern_cache:
                        try:
                            re.compile(stop_word)
                            is_regex = True
                        except re.error:
                            is_regex = False
                elif stop_word.startswith('(?') or stop_word.startswith('(\\?'):
                    is_regex = True
                elif '\\b' in stop_word or '\\s' in stop_word or '\\d' in stop_word or '\\w' in stop_word:
                    is_regex = True

                if is_regex:
                    if stop_word not in pattern_cache:
                        try:
                            pattern_cache[stop_word] = re.compile(
                                stop_word,
                                re.IGNORECASE | re.UNICODE
                            )
                        except re.error:
                            pattern_cache[stop_word] = None

                    compiled = pattern_cache.get(stop_word)
                    if compiled and compiled.search(full_text_lower):
                        return True
                else:
                    if stop_word in full_text_lower:
                        return True

            return False

        stop_word_check_cache = {}

        for p in self.compiled_patterns:
            try:
                is_case_sensitive = p.get('is_case_sensitive', False)
                crit_type = p['type']
                crit_id = p['id']
                crit_name = p['name']

                criteria_key = (crit_type, crit_id, crit_name)

                if criteria_key not in stop_word_check_cache:
                    stop_words = self.criteria_stop_words_cache.get(criteria_key, [])
                    stop_word_check_cache[criteria_key] = has_stop_word_in_text(text_lower, stop_words)

                if stop_word_check_cache[criteria_key]:
                    continue

                if not self.collect_all_patterns and crit_id in processed_criteria[crit_type]:
                    continue

                search_start = 0
                first_match_for_criteria = True
                pattern_match_count = 0

                while True:
                    if is_case_sensitive:
                        match = p['pattern'].search(text, search_start)
                    else:
                        match = p['pattern'].search(text_lower, search_start)

                    if not match:
                        break

                    match_start_pos = match.start()
                    match_end_pos = match.end()

                    if has_negation_before(text, match_start_pos):
                        search_start = match_end_pos
                        continue

                    pattern_match_count += 1

                    if collect_details and self.collect_all_patterns and is_position_occupied(
                            match_start_pos, match_end_pos, occupied_positions):
                        search_start = match_end_pos
                        continue

                    is_existing = False
                    if existing_relations and crit_type in existing_relations:
                        is_existing = (game_id, crit_id) in existing_relations[crit_type]

                    if collect_details:
                        pattern_key = (crit_type, p['name'], p['pattern_str'])
                        if is_existing:
                            self.pattern_match_counter_existing[pattern_key] += 1
                        else:
                            self.pattern_match_counter_new[pattern_key] += 1

                    if first_match_for_criteria and crit_id not in found_ids[crit_type]:
                        found_ids[crit_type].add(crit_id)
                        total_found += 1

                    if collect_details and (self.collect_all_patterns or first_match_for_criteria):
                        if is_case_sensitive:
                            word_start = match_start_pos
                            while word_start > 0 and (text[word_start - 1].isalnum() or text[word_start - 1] in '-_'):
                                word_start -= 1

                            word_end = match_end_pos
                            while word_end < len(text) and (text[word_end].isalnum() or text[word_end] in '-_'):
                                word_end += 1

                            matched_word = text[word_start:word_end]
                            context = get_sentence_context(text, match_start_pos, match_end_pos)

                            pattern_info[crit_type].append({
                                'name': crit_name,
                                'id': crit_id,
                                'matched_text': matched_word[:100],
                                'context': context[:500],
                                'pattern': p['pattern_str'],
                                'status': 'found',
                                'position': match_start_pos
                            })
                        else:
                            word_start = match_start_pos
                            while word_start > 0 and (text[word_start - 1].isalnum() or text[word_start - 1] in '-_'):
                                word_start -= 1

                            word_end = match_end_pos
                            while word_end < len(text) and (text[word_end].isalnum() or text[word_end] in '-_'):
                                word_end += 1

                            full_word = text[word_start:word_end]
                            context = get_sentence_context(text, match_start_pos, match_end_pos)

                            pattern_info[crit_type].append({
                                'name': crit_name,
                                'id': crit_id,
                                'matched_text': full_word[:100],
                                'context': context[:500],
                                'pattern': p['pattern_str'],
                                'status': 'found',
                                'position': match_start_pos
                            })

                        if collect_details and self.collect_all_patterns:
                            occupied_positions.append((match_start_pos, match_end_pos))

                    first_match_for_criteria = False
                    search_start = match_end_pos

                    if not self.collect_all_patterns:
                        processed_criteria[crit_type].add(crit_id)
                        break

            except Exception:
                continue

        found = {'genres': [], 'themes': [], 'keywords': []}
        has_new = False

        if total_found > 0 and self.update_game:
            from django.db import connection

            # Имена таблиц и колонок — из _meta (не хардкодим game_id/movie_id).
            movie_table = Movie._meta.db_table  # 'movies_movie'
            genres_through = Movie.genres.through
            themes_through = Movie.themes.through

            genres_table = genres_through._meta.db_table
            genres_movie_col = next(
                f.column for f in genres_through._meta.fields
                if f.remote_field and f.remote_field.model is Movie
            )
            genres_genre_col = next(
                f.column for f in genres_through._meta.fields
                if f.remote_field and f.remote_field.model is Genre
            )

            themes_table = themes_through._meta.db_table
            themes_movie_col = next(
                f.column for f in themes_through._meta.fields
                if f.remote_field and f.remote_field.model is Movie
            )
            themes_theme_col = next(
                f.column for f in themes_through._meta.fields
                if f.remote_field and f.remote_field.model is Theme
            )

            for crit_type in ['genres', 'themes']:
                if not found_ids[crit_type]:
                    continue

                if crit_type == 'genres':
                    table = genres_table
                    movie_col = genres_movie_col
                    field = genres_genre_col
                elif crit_type == 'themes':
                    table = themes_table
                    movie_col = themes_movie_col
                    field = themes_theme_col
                else:
                    continue

                crit_ids_list = list(found_ids[crit_type])
                placeholders = ','.join(['%s'] * len(crit_ids_list))

                with connection.cursor() as cursor:
                    cursor.execute(f"""
                        SELECT DISTINCT {field}
                        FROM {table}
                        WHERE {movie_col} = %s AND {field} IN ({placeholders})
                    """, [game_id] + crit_ids_list)

                    existing_ids = {row[0] for row in cursor.fetchall()}

                for crit_id in found_ids[crit_type]:
                    is_new = crit_id not in existing_ids
                    if is_new:
                        has_new = True

                    found[crit_type].append({
                        'id': crit_id,
                        'name': self.criteria_by_id[crit_type].get(crit_id, 'Unknown'),
                        'is_new': is_new
                    })
        else:
            for crit_type in ['genres', 'themes']:
                for crit_id in found_ids[crit_type]:
                    found[crit_type].append({
                        'id': crit_id,
                        'name': self.criteria_by_id[crit_type].get(crit_id, 'Unknown'),
                        'is_new': True
                    })
            has_new = total_found > 0

        return {
            'id': game_id,
            'name': game_dict['name'],
            'has_results': total_found > 0,
            'skipped': False,
            'count': total_found,
            'found': found,
            'pattern_info': pattern_info,
            'has_new': has_new
        }
