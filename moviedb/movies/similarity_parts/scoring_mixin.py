# movies/similarity_parts/scoring_mixin.py
"""Scoring methods for moviesimilarity."""

from .utils import timeit


class ScoringMixin:
    """Расчёт схожести и её детализация."""

    # ------------------------------------------------------------------
    # Публичные методы
    # ------------------------------------------------------------------
    def get_similarity_formula(self, source, target, override_criteria=None):
        """Структурированные данные для отображения вклада каждого критерия."""
        try:
            breakdown = self._calculate_breakdown_direct(
                source, target, override_criteria=override_criteria,
            )
            source_data = self._prepare_source_data(source, override_criteria=override_criteria)
            criteria_contributions = []

            if breakdown['genres']['max_score'] > 0:
                common_count = len(breakdown['genres']['common_elements'])
                source_count = source_data['genre_count']
                genre_match_percentage = (
                    (common_count / source_count * 100) if source_count > 0 else 0
                )
                criteria_contributions.append({
                    'icon': '🎬',
                    'name': 'Genres',
                    'map_name': 'genres',
                    'common': common_count,
                    'total': source_count,
                    'weight': breakdown['genres']['max_score'],
                    'contribution': breakdown['genres']['score'],
                    'percentage': genre_match_percentage,
                    'color': 'purple'
                })

            if breakdown['keywords']['max_score'] > 0:
                common_count = len(breakdown['keywords']['common_elements'])
                source_count = source_data['keyword_count']
                keyword_match_percentage = (
                    (common_count / source_count * 100) if source_count > 0 else 0
                )
                criteria_contributions.append({
                    'icon': '🔑',
                    'name': 'Keywords',
                    'map_name': 'keywords',
                    'common': common_count,
                    'total': source_count,
                    'weight': breakdown['keywords']['max_score'],
                    'contribution': breakdown['keywords']['score'],
                    'percentage': keyword_match_percentage,
                    'color': 'success'
                })

            if breakdown['themes']['max_score'] > 0:
                common_count = len(breakdown['themes']['common_elements'])
                source_count = source_data['theme_count']
                theme_match_percentage = (
                    (common_count / source_count * 100) if source_count > 0 else 0
                )
                criteria_contributions.append({
                    'icon': '🎭',
                    'name': 'Themes',
                    'map_name': 'themes',
                    'common': common_count,
                    'total': source_count,
                    'weight': breakdown['themes']['max_score'],
                    'contribution': breakdown['themes']['score'],
                    'percentage': theme_match_percentage,
                    'color': 'orange'
                })

            if breakdown['developers']['max_score'] > 0:
                common_count = len(breakdown['developers']['common_elements'])
                source_count = source_data['developer_count']
                developer_match_percentage = (
                    (common_count / source_count * 100) if source_count > 0 else 0
                )
                criteria_contributions.append({
                    'icon': '🏢',
                    'name': 'Production Companies',
                    'map_name': 'developers',
                    'common': common_count,
                    'total': source_count,
                    'weight': breakdown['developers']['max_score'],
                    'contribution': breakdown['developers']['score'],
                    'percentage': developer_match_percentage,
                    'color': 'secondary'
                })

            if breakdown['series']['max_score'] > 0:
                common_count = len(breakdown['series']['common_elements'])
                criteria_contributions.append({
                    'icon': '🎞️',
                    'name': 'Series',
                    'map_name': 'series',
                    'common': common_count,
                    'total': source_data['series_count'],
                    'weight': breakdown['series']['max_score'],
                    'contribution': breakdown['series']['score'],
                    'percentage': 100 if common_count > 0 else 0,
                    'color': 'info'
                })

            bonus = breakdown.get('bonus', 0) if breakdown.get('bonus', 0) > 0 else None

            return {
                'criteria': criteria_contributions,
                'bonus': bonus,
                'total': breakdown['total_similarity'],
                'total_from_criteria': breakdown.get(
                    'total_without_bonus',
                    sum(c['contribution'] for c in criteria_contributions),
                ),
            }

        except Exception as e:
            if self.verbose:
                print(f"Error generating similarity formula: {str(e)}")
                import traceback
                traceback.print_exc()
            return {
                'criteria': [],
                'bonus': None,
                'total': 0,
                'total_from_criteria': 0,
                'error': str(e)
            }

    def get_similarity_breakdown(self, source, target, override_criteria=None):
        return self._calculate_breakdown_direct(
            source, target, override_criteria=override_criteria,
        )

    def calculate_similarity(self, source, target, override_criteria=None):
        """Универсальный расчёт итоговой схожести (0..100).

        Обёртка над `_calculate_breakdown_direct` для обратной совместимости.
        """
        try:
            breakdown = self._calculate_breakdown_direct(
                source, target, override_criteria=override_criteria,
            )
            return breakdown['total_similarity']
        except Exception as e:
            if self.verbose:
                print(f"Error calculating similarity: {str(e)}")
            return 0.0

    # ------------------------------------------------------------------
    # Детальная разбивка
    # ------------------------------------------------------------------
    def _calculate_breakdown_direct(self, source, target, override_criteria=None):
        """Прямой расчет детальной разбивки похожести без рекурсии."""
        source_data = self._prepare_source_data(source, override_criteria=override_criteria)
        target_raw = self._get_cached_movie_data(target)

        common_genres = len(source_data.get('genres', set()) & target_raw.get('genres', set()))
        common_keywords = len(source_data.get('keywords', set()) & target_raw.get('keywords', set()))
        common_themes = len(source_data.get('themes', set()) & target_raw.get('themes', set()))
        common_developers = len(source_data.get('developers', set()) & target_raw.get('developers', set()))
        common_series = 1 if (source_data.get('series_id') and
                              source_data.get('series_id') == target_raw.get('series_id')) else 0

        target_data = {
            'common_genres': common_genres,
            'common_keywords': common_keywords,
            'common_themes': common_themes,
            'common_developers': common_developers,
            'common_series': common_series,
            'total_genres': len(target_raw.get('genres', set())),
            'total_keywords': len(target_raw.get('keywords', set())),
            'total_themes': len(target_raw.get('themes', set())),
            'total_developers': len(target_raw.get('developers', set())),
        }

        max_scores = {
            'genres': self.GENRES_WEIGHT,
            'keywords': self.KEYWORDS_WEIGHT,
            'themes': self.THEMES_WEIGHT,
            'developers': self.DEVELOPERS_WEIGHT,
            'series': self.SERIES_WEIGHT,
        }

        scores = {}

        if max_scores['genres'] > 0 and source_data['genre_count'] > 0:
            common = target_data['common_genres']
            source_total = source_data['genre_count']
            target_total = target_data['total_genres']
            percent_per_genre = max_scores['genres'] / source_total
            genre_score = common * percent_per_genre
            extra_genres_in_target = target_total - common
            penalty = extra_genres_in_target * self.EXTRA_GENRE_PENALTY
            scores['genres'] = max(0.0, genre_score - penalty)
        else:
            scores['genres'] = 0.0

        if max_scores['keywords'] > 0 and source_data['keyword_count'] > 0:
            if target_data['common_keywords'] > 0:
                scores['keywords'] = min(
                    target_data['common_keywords'] * self.KEYWORDS_ADD_PER_MATCH,
                    max_scores['keywords'],
                )
            else:
                scores['keywords'] = 0.0
        else:
            scores['keywords'] = 0.0

        if max_scores['themes'] > 0 and source_data['theme_count'] > 0:
            if target_data['common_themes'] > 0:
                theme_match_ratio = target_data['common_themes'] / max(source_data['theme_count'], 1)
                scores['themes'] = theme_match_ratio * max_scores['themes']
            else:
                scores['themes'] = 0.0
        else:
            scores['themes'] = 0.0

        if max_scores['developers'] > 0 and source_data['developer_count'] > 0:
            if target_data['common_developers'] > 0:
                developer_match_ratio = (
                        target_data['common_developers'] / max(source_data['developer_count'], 1)
                )
                scores['developers'] = developer_match_ratio * max_scores['developers']
            else:
                scores['developers'] = 0.0
        else:
            scores['developers'] = 0.0

        if max_scores['series'] > 0 and source_data.get('series_id'):
            scores['series'] = max_scores['series'] if common_series > 0 else 0.0
        else:
            scores['series'] = 0.0

        total_without_bonus = sum(scores.values())

        has_any_matches = any([
            target_data['common_genres'] > 0,
            target_data['common_keywords'] > 0,
            target_data['common_themes'] > 0,
            target_data['common_developers'] > 0,
            common_series > 0,
        ])

        active_criteria_count = sum([
            source_data['genre_count'] > 0,
            source_data['keyword_count'] > 0,
            source_data['theme_count'] > 0,
            source_data['developer_count'] > 0,
            bool(source_data.get('series_id')),
        ])

        bonus = 0.0
        if has_any_matches and active_criteria_count > 1:
            bonus = self.BONUS_MULTI_CRITERIA

        final_total = min(100.0, total_without_bonus + bonus)

        common_elements = {
            'genres': list(source_data.get('genres', set()) & target_raw.get('genres', set())),
            'keywords': list(source_data.get('keywords', set()) & target_raw.get('keywords', set())),
            'themes': list(source_data.get('themes', set()) & target_raw.get('themes', set())),
            'developers': list(source_data.get('developers', set()) & target_raw.get('developers', set())),
            'series': [source_data.get('series_id')] if common_series else [],
        }

        return {
            'genres': {
                'score': scores['genres'],
                'max_score': max_scores['genres'],
                'common_elements': common_elements['genres']
            },
            'keywords': {
                'score': scores['keywords'],
                'max_score': max_scores['keywords'],
                'common_elements': common_elements['keywords']
            },
            'themes': {
                'score': scores['themes'],
                'max_score': max_scores['themes'],
                'common_elements': common_elements['themes']
            },
            'developers': {
                'score': scores['developers'],
                'max_score': max_scores['developers'],
                'common_elements': common_elements['developers']
            },
            'series': {
                'score': scores['series'],
                'max_score': max_scores['series'],
                'common_elements': common_elements['series']
            },
            'dynamic_weights': max_scores,
            'total_similarity': final_total,
            'bonus': bonus,
            'total_without_bonus': total_without_bonus
        }

    # ------------------------------------------------------------------
    # Унифицированный расчет
    # ------------------------------------------------------------------
    def _calculate_unified_similarity(self, source_genre_count, source_keyword_count,
                                      source_theme_count, source_developer_count,
                                      source_series_id, target_data):
        """Унифицированный расчет схожести (5 критериев + бонус)."""
        similarity = 0.0

        if self.GENRES_WEIGHT > 0 and source_genre_count > 0:
            common_genres = target_data.get('common_genres', 0)
            source_total = source_genre_count
            target_total = target_data.get('total_genres', 0)
            percent_per_genre = self.GENRES_WEIGHT / source_total
            genre_score = common_genres * percent_per_genre
            extra_genres_in_target = target_total - common_genres
            penalty = extra_genres_in_target * self.EXTRA_GENRE_PENALTY
            similarity += max(0.0, genre_score - penalty)

        if self.KEYWORDS_WEIGHT > 0 and source_keyword_count > 0:
            common_keywords = target_data.get('common_keywords', 0)
            if common_keywords > 0:
                similarity += min(
                    common_keywords * self.KEYWORDS_ADD_PER_MATCH,
                    self.KEYWORDS_WEIGHT,
                )

        if self.THEMES_WEIGHT > 0 and source_theme_count > 0:
            if target_data.get('common_themes', 0) > 0:
                theme_match_ratio = target_data['common_themes'] / max(source_theme_count, 1)
                similarity += theme_match_ratio * self.THEMES_WEIGHT

        if self.DEVELOPERS_WEIGHT > 0 and source_developer_count > 0:
            if target_data.get('common_developers', 0) > 0:
                developer_match_ratio = (
                        target_data.get('common_developers', 0) / max(source_developer_count, 1)
                )
                similarity += developer_match_ratio * self.DEVELOPERS_WEIGHT

        if self.SERIES_WEIGHT > 0 and source_series_id:
            if target_data.get('common_series', 0) > 0:
                similarity += self.SERIES_WEIGHT

        has_any_matches = any([
            target_data.get('common_genres', 0) > 0,
            target_data.get('common_keywords', 0) > 0,
            target_data.get('common_themes', 0) > 0,
            target_data.get('common_developers', 0) > 0,
            target_data.get('common_series', 0) > 0,
        ])

        active_criteria_count = sum([
            source_genre_count > 0,
            source_keyword_count > 0,
            source_theme_count > 0,
            source_developer_count > 0,
            bool(source_series_id),
        ])

        if has_any_matches and active_criteria_count > 1:
            similarity += self.BONUS_MULTI_CRITERIA

        return round(min(100.0, similarity), 2)

    @timeit
    def _calculate_movie_similarity_new(self, source_genre_count, source_keyword_count,
                                        source_theme_count, source_developer_count,
                                        source_series_id, target_data, source_data=None):
        """Расчет схожести фильма (5 критериев + бонус)."""
        similarity = 0.0

        if self.GENRES_WEIGHT > 0 and source_genre_count > 0:
            common_genres = target_data.get('common_genres', 0)
            source_total = source_genre_count
            target_total = target_data.get('total_genres', 0)
            percent_per_genre = self.GENRES_WEIGHT / source_total
            genre_score = common_genres * percent_per_genre
            extra_genres_in_target = target_total - common_genres
            penalty = extra_genres_in_target * self.EXTRA_GENRE_PENALTY
            similarity += max(0.0, genre_score - penalty)

        if self.KEYWORDS_WEIGHT > 0 and source_keyword_count > 0:
            common_keywords = target_data.get('common_keywords', 0)
            if common_keywords > 0:
                similarity += min(
                    common_keywords * self.KEYWORDS_ADD_PER_MATCH,
                    self.KEYWORDS_WEIGHT,
                )

        if self.THEMES_WEIGHT > 0 and source_theme_count > 0:
            if target_data.get('common_themes', 0) > 0:
                theme_match_ratio = target_data['common_themes'] / max(source_theme_count, 1)
                similarity += theme_match_ratio * self.THEMES_WEIGHT

        if self.DEVELOPERS_WEIGHT > 0 and source_developer_count > 0:
            if target_data.get('common_developers', 0) > 0:
                developer_match_ratio = (
                        target_data.get('common_developers', 0) / max(source_developer_count, 1)
                )
                similarity += developer_match_ratio * self.DEVELOPERS_WEIGHT

        if self.SERIES_WEIGHT > 0 and source_series_id:
            if target_data.get('common_series', 0) > 0:
                similarity += self.SERIES_WEIGHT

        has_any_matches = any([
            target_data.get('common_genres', 0) > 0,
            target_data.get('common_keywords', 0) > 0,
            target_data.get('common_themes', 0) > 0,
            target_data.get('common_developers', 0) > 0,
            target_data.get('common_series', 0) > 0,
        ])

        active_criteria_count = sum([
            source_genre_count > 0,
            source_keyword_count > 0,
            source_theme_count > 0,
            source_developer_count > 0,
            bool(source_series_id),
        ])

        if has_any_matches and active_criteria_count > 1:
            similarity += self.BONUS_MULTI_CRITERIA

        return min(100.0, similarity)

    @timeit
    def _calculate_similarity_for_candidates(self, movies_data, source_data,
                                             source_movie, min_similarity=None):
        """Расчет схожести для кандидатов."""
        import time
        from ..models import Movie

        if min_similarity is None:
            min_similarity = self.DEFAULT_MIN_SIMILARITY

        if self.verbose:
            print("Расчет схожести для кандидатов...")
            print(f"min_similarity = {min_similarity}")

        calc_time = time.time()

        similar_movies = []
        source_genre_count = source_data['genre_count']
        source_keyword_count = source_data['keyword_count']
        source_theme_count = source_data['theme_count']
        source_developer_count = source_data['developer_count']
        source_series_id = source_data.get('series_id')

        source_movie_id = getattr(source_movie, 'id', None) if isinstance(source_movie, Movie) else None
        source_movie_name = (
            getattr(source_movie, 'name', 'Source Movie')
            if isinstance(source_movie, Movie) else 'Source Movie'
        )

        if source_movie_id is not None:
            similar_movies.append({
                'movie_id': source_movie_id,
                'movie_name': source_movie_name,
                'similarity': 100.0,
                'common_keywords': source_data['keyword_count'],
                'common_genres': source_data['genre_count'],
                'common_themes': source_data['theme_count'],
                'common_developers': source_data['developer_count'],
                'common_series': source_data.get('series_count', 0),
                'is_source_movie': True,
            })

        for movie_id, data in movies_data.items():
            if self.stop_flag:
                if self.verbose:
                    print("Прерывание: остановка в цикле расчета схожести")
                break

            if source_movie_id and movie_id == source_movie_id:
                continue

            similarity = self._calculate_movie_similarity_new(
                source_genre_count,
                source_keyword_count,
                source_theme_count,
                source_developer_count,
                source_series_id,
                data,
                source_data,
            )

            if similarity >= min_similarity:
                similar_movies.append({
                    'movie_id': movie_id,
                    'movie_name': data['name'],
                    'similarity': similarity,
                    'common_keywords': data['common_keywords'],
                    'common_genres': data['common_genres'],
                    'common_themes': data['common_themes'],
                    'common_developers': data['common_developers'],
                    'common_series': data.get('common_series', 0),
                    'is_source_movie': False,
                })

        if self.verbose:
            print(f"Расчет схожести завершен за {time.time() - calc_time:.2f} сек")
            print(f"Найдено {len(similar_movies)} фильмов выше порога {min_similarity}%")

        return similar_movies