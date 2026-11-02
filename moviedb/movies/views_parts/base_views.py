# movies/views_parts/base_views.py
"""Base views with common functions and configurations (Movie-only).

Кэш-инфраструктура вынесена в `cache_utils.py` и реэкспортируется здесь
для обратной совместимости: `from .base_views import get_cache_key, ...`
продолжает работать.
"""

import time
import json
import hashlib
import logging
from functools import lru_cache, wraps
from typing import Dict, List, Tuple, Any, Optional, Union
from urllib.parse import urlencode

from django.shortcuts import render, get_object_or_404
from django.db.models import Count, Prefetch, Q
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse, HttpResponseServerError, JsonResponse
from django.db import models
from django.utils import timezone
from datetime import timedelta
from django.template.loader import render_to_string
from django.conf import settings

# ===== LOCAL IMPORTS =====
from ..models import (
    Movie, Genre, Keyword, Theme, Company, Series,
)
from ..helpers import generate_compact_url_params

# Кэш-инфраструктура (реэкспортируется для обратной совместимости).
from .cache_utils import (  # noqa: F401
    CACHE_TIMES,
    CACHE_VERSION,
    redis_client,
    logger,
    _cached_string_to_int_list,
    _generate_cache_key,
    get_cache_key,
    cache_get_or_set,
    invalidate_cache_group,
    cache_multi_get,
    cache_multi_set,
    cache_view,
    cache_method,
    warm_cache_for_home_page,
    clear_movie_list_cache,
    clear_game_list_cache,
    get_cache_stats,
    get_release_years_range,
    _get_cached_years_range,
    _fetch_optimized_filter_data,
    _get_optimized_filter_data,
    _get_cached_movie,
    _get_cached_game,
    _get_cached_genres_list,
    _get_cached_filter_data,
)

# Реэкспорт для обратной совместимости: comparison_views.py и др.
# исторически импортировали moviesimilarity из base_views.
from ..similarity import moviesimilarity  # noqa: F401


# ===== HELPER CLASSES =====

class SimpleSourceMovie:
    """Simple wrapper for source Movie data with compatibility for template tags."""

    def __init__(self, movie_obj=None, criteria=None, display_name=None):
        self.movie_obj = movie_obj
        self.criteria = criteria or {}
        self.display_name = display_name

        if movie_obj:
            self.id = movie_obj.id
            self.name = movie_obj.name
            self.is_movie = True
            self.display_name = display_name or movie_obj.name
            self._cache_movie_ids()
        else:
            self.id = None
            self.name = display_name or "Search Criteria"
            self.is_movie = False
            self.display_name = display_name or "Search Criteria"

            self._genre_ids = criteria.get('genres', []) if criteria else []
            self._keyword_ids = criteria.get('keywords', []) if criteria else []
            self._theme_ids = criteria.get('themes', []) if criteria else []
            self._developer_ids = criteria.get('developers', []) if criteria else []
            self._series_id = criteria.get('series_id') if criteria else None

    def _cache_movie_ids(self):
        if not self.movie_obj:
            return

        if hasattr(self.movie_obj, '_cached_genre_ids'):
            self._genre_ids = self.movie_obj._cached_genre_ids
        elif hasattr(self.movie_obj, 'genres') and hasattr(self.movie_obj.genres, 'all'):
            self._genre_ids = [g.id for g in self.movie_obj.genres.all()]
        else:
            self._genre_ids = []

        if hasattr(self.movie_obj, '_cached_keyword_ids'):
            self._keyword_ids = self.movie_obj._cached_keyword_ids
        elif hasattr(self.movie_obj, 'keywords') and hasattr(self.movie_obj.keywords, 'all'):
            self._keyword_ids = [k.id for k in self.movie_obj.keywords.all()]
        else:
            self._keyword_ids = []

        if hasattr(self.movie_obj, '_cached_theme_ids'):
            self._theme_ids = self.movie_obj._cached_theme_ids
        elif hasattr(self.movie_obj, 'themes') and hasattr(self.movie_obj.themes, 'all'):
            self._theme_ids = [t.id for t in self.movie_obj.themes.all()]
        else:
            self._theme_ids = []

        if hasattr(self.movie_obj, '_cached_developer_ids'):
            self._developer_ids = self.movie_obj._cached_developer_ids
        elif hasattr(self.movie_obj, 'production_companies') and hasattr(self.movie_obj.production_companies, 'all'):
            self._developer_ids = [d.id for d in self.movie_obj.production_companies.all()]
        else:
            self._developer_ids = []

        self._series_id = getattr(self.movie_obj, 'series_id', None)

    def genres_list(self):
        return self._genre_ids

    def keywords_list(self):
        return self._keyword_ids

    def themes_list(self):
        return self._theme_ids

    def developers_list(self):
        return self._developer_ids

    @property
    def genres_ids(self):
        return self._genre_ids

    @property
    def keywords_ids(self):
        return self._keyword_ids

    @property
    def themes_ids(self):
        return self._theme_ids

    @property
    def developers_ids(self):
        return self._developer_ids

    @property
    def series_id(self):
        return self._series_id

    def all(self):
        return []

    def get(self, *args, **kwargs):
        return None

    def __str__(self):
        return self.display_name or self.name

    def __repr__(self):
        if self.is_movie:
            return f"<SimpleSourceMovie: {self.name} (ID: {self.id})>"
        return f"<SimpleSourceMovie: {self.name} (Criteria)>"


# Алиас для обратной совместимости с другими view-модулями
SimpleSourceGame = SimpleSourceMovie


# ===== HELPER FUNCTIONS =====

def extract_request_params(request: HttpRequest) -> Dict[str, str]:
    """Extract parameters from request efficiently."""
    get_params = request.GET

    params = {}
    for key in [
        'find_similar', 'g', 'k', 't', 'd', 'yr', 'ys', 'ye',
        'source_movie', 'source_game', 'sort', 'page', 'search_k', 'q', 'seed',
    ]:
        value = get_params.get(key, '')
        params[key] = value

    params['_present'] = set(get_params.keys())
    return params


def convert_params_to_lists(params_dict: Dict[str, str]) -> Dict[str, List[int]]:
    """Convert query parameters to lists of integers."""

    def parse_int_list(param_value):
        if not param_value or param_value is None:
            return []
        result = []
        try:
            for part in str(param_value).split(','):
                part = part.strip()
                if part and part.isdigit():
                    result.append(int(part))
        except (ValueError, AttributeError):
            return []
        return result

    release_year_start = None
    release_year_end = None

    year_range = params_dict.get('yr')
    if year_range and '-' in year_range:
        try:
            parts = year_range.split('-')
            if parts[0].strip():
                release_year_start = int(parts[0].strip())
            if len(parts) > 1 and parts[1].strip():
                release_year_end = int(parts[1].strip())
        except (ValueError, IndexError):
            pass

    if not release_year_start and params_dict.get('ys'):
        try:
            release_year_start = int(params_dict['ys'])
        except ValueError:
            pass

    if not release_year_end and params_dict.get('ye'):
        try:
            release_year_end = int(params_dict['ye'])
        except ValueError:
            pass

    k_value = params_dict.get('k')
    if not k_value:
        k_value = params_dict.get('search_k', '')

    series_raw = params_dict.get('series') or params_dict.get('s')
    try:
        series_id = int(series_raw) if series_raw else None
    except (ValueError, TypeError):
        series_id = None

    result = {
        'genres': parse_int_list(params_dict.get('g')),
        'keywords': parse_int_list(k_value),
        'themes': parse_int_list(params_dict.get('t')),
        'developers': parse_int_list(params_dict.get('d')),
        'series_id': series_id,
        'release_years': [],
        'release_year_start': release_year_start,
        'release_year_end': release_year_end,
    }

    return result


def _apply_filters(queryset: models.QuerySet, selected_criteria: Dict[str, List[int]]) -> models.QuerySet:
    """Apply filters to queryset (Movie-only)."""
    main_filters = Q()
    has_main_filters = False

    other_fields = [
        ('genres', 'genres__id__in'),
        ('themes', 'themes__id__in'),
        ('developers', 'production_companies__id__in'),
    ]

    for field, model_field in other_fields:
        field_value = selected_criteria.get(field, [])
        if field_value:
            main_filters &= Q(**{model_field: field_value})
            has_main_filters = True

    if selected_criteria.get('keywords'):
        keyword_ids = selected_criteria['keywords']
        main_filters &= Q(keywords__id__in=keyword_ids)
        has_main_filters = True

    if selected_criteria.get('series_id'):
        main_filters &= Q(series_id=selected_criteria['series_id'])
        has_main_filters = True

    year_start = selected_criteria.get('release_year_start')
    year_end = selected_criteria.get('release_year_end')

    if year_start or year_end:
        date_filter = Q()
        if year_start:
            start_date = f"{year_start}-01-01"
            date_filter &= Q(first_release_date__gte=start_date)
        if year_end:
            end_date = f"{year_end}-12-31"
            date_filter &= Q(first_release_date__lte=end_date)
        main_filters &= date_filter
        has_main_filters = True

    if has_main_filters:
        queryset = queryset.filter(main_filters).distinct()

    return queryset


def _apply_search_filters(queryset: models.QuerySet, search_filters: Dict[str, List[int]]) -> models.QuerySet:
    """Apply search filters (Movie-only).

    BETWEEN groups: AND; WITHIN a group: OR (кроме genres/themes — там AND).
    """
    filter_groups = []

    # ========== ТЕКСТОВЫЙ ПОИСК ==========
    text_query = search_filters.get('text_query')
    if text_query:
        words = text_query.lower().split()
        if len(words) == 1:
            filter_groups.append(Q(name__icontains=words[0]))
        else:
            combined_text_filter = Q()
            for word in words:
                combined_text_filter &= Q(name__icontains=word)
            if combined_text_filter:
                filter_groups.append(combined_text_filter)

    # ========== ОСТАЛЬНЫЕ ФИЛЬТРЫ ==========
    if search_filters.get('genres'):
        genres_filter = Q()
        for genre_id in search_filters['genres']:
            genres_filter &= Q(genres__id=genre_id)
        filter_groups.append(genres_filter)

    if search_filters.get('keywords'):
        filter_groups.append(Q(keywords__id__in=search_filters['keywords']))

    if search_filters.get('themes'):
        themes_filter = Q()
        for theme_id in search_filters['themes']:
            themes_filter &= Q(themes__id=theme_id)
        filter_groups.append(themes_filter)

    if search_filters.get('developers'):
        filter_groups.append(
            Q(production_companies__id__in=search_filters['developers'])
        )

    if search_filters.get('series_id'):
        filter_groups.append(Q(series_id=search_filters['series_id']))

    year_start = search_filters.get('release_year_start')
    year_end = search_filters.get('release_year_end')

    if year_start or year_end:
        date_filter = Q()
        if year_start:
            date_filter &= Q(first_release_date__gte=f"{year_start}-01-01")
        if year_end:
            date_filter &= Q(first_release_date__lte=f"{year_end}-12-31")
        filter_groups.append(date_filter)

    if filter_groups:
        combined_filter = Q()
        for group_filter in filter_groups:
            combined_filter &= group_filter
        queryset = queryset.filter(combined_filter).distinct()

    return queryset


def get_objects_by_ids(model_class, ids: List[int], only_fields: List[str] = None) -> List:
    """Get model objects by their IDs efficiently."""
    if not ids:
        return []

    queryset = model_class.objects.filter(id__in=ids)
    if only_fields:
        queryset = queryset.only(*only_fields)

    id_to_obj = {obj.id: obj for obj in queryset}
    return [id_to_obj[id] for id in ids if id in id_to_obj]


def _filter_by_platforms(movies_data: List, platform_ids: List[int]) -> List:
    """DEPRECATED: Movie-only проект больше не использует platforms.

    Оставлено как no-op для обратной совместимости с другими view-модулями.
    """
    return movies_data


def _prefetch_similar_movies(similar_movies: List) -> List:
    """Prefetch related data for similar movies (Movie-only)."""
    movie_ids = []
    for item in similar_movies:
        movie = item.get('Movie') if isinstance(item, dict) else item
        if movie is not None and hasattr(movie, 'id'):
            movie_ids.append(movie.id)

    if not movie_ids:
        return similar_movies

    movies_dict = {}
    movies_with_prefetch = Movie.objects.filter(id__in=movie_ids).prefetch_related(
        Prefetch('genres', queryset=Genre.objects.only('id', 'name')),
        Prefetch('themes', queryset=Theme.objects.only('id', 'name')),
        Prefetch('production_companies', queryset=Company.objects.only('id', 'name')),
    ).only(
        'id', 'name', 'rating', 'rating_count',
        'first_release_date', 'cover_url',
    )

    for movie in movies_with_prefetch:
        movies_dict[movie.id] = movie

    updated_movies = []
    for item in similar_movies:
        if isinstance(item, dict):
            movie = item.get('Movie')
            if movie is not None and hasattr(movie, 'id') and movie.id in movies_dict:
                item['Movie'] = movies_dict[movie.id]
            updated_movies.append(item)
        elif hasattr(item, 'id') and item.id in movies_dict:
            updated_movies.append(movies_dict[item.id])
        else:
            updated_movies.append(item)

    return updated_movies


def _format_similar_movies_data(similar_movies_data: List) -> List[Dict[str, Any]]:
    """Format similar movies data (Movie-only)."""
    if not similar_movies_data:
        return []

    movie_ids = []
    similarity_map = {}

    for item in similar_movies_data:
        if isinstance(item, dict):
            movie = item.get('Movie') or item.get('movie')
            similarity = item.get('similarity', 0)
        else:
            movie = item
            similarity = 0

        if movie is not None and hasattr(movie, 'id'):
            movie_ids.append(movie.id)
            similarity_map[movie.id] = similarity

    movies_dict = {}
    if movie_ids:
        movies_with_prefetch = Movie.objects.filter(id__in=movie_ids).prefetch_related(
            Prefetch('genres', queryset=Genre.objects.only('id', 'name')),
            Prefetch('themes', queryset=Theme.objects.only('id', 'name')),
            Prefetch('production_companies', queryset=Company.objects.only('id', 'name')),
        ).only(
            'id', 'name', 'rating', 'rating_count',
            'first_release_date', 'cover_url',
        )

        for movie in movies_with_prefetch:
            movies_dict[movie.id] = movie

    formatted = []
    for item in similar_movies_data:
        if isinstance(item, dict):
            movie = item.get('Movie') or item.get('movie')
            similarity = item.get('similarity', 0)
        else:
            movie = item
            similarity = similarity_map.get(getattr(movie, 'id', None), 0)

        if movie is not None and hasattr(movie, 'id') and movie.id in movies_dict:
            movie = movies_dict[movie.id]

        if movie is not None and similarity:
            movie.similarity = similarity

        formatted.append({
            'Movie': movie,
            'movie': movie,
            'similarity': similarity,
        })

    return formatted


def _sort_similar_movies(movies_with_similarity: List[Dict[str, Any]], current_sort: str,
                         seed: Optional[str] = None) -> None:
    """Sort similar movies.

    Для current_sort == 'random' — детерминированное перемешивание на основе seed.
    """
    if current_sort == 'random':
        import random as _random
        import time as _time

        if seed:
            rng = _random.Random(str(seed))
        else:
            rng = _random.Random(_time.time_ns())

        rng.shuffle(movies_with_similarity)
        return

    def _movie_of(item):
        return item.get('Movie') or item.get('movie')

    if current_sort == '-rating_count':
        movies_with_similarity.sort(
            key=lambda x: (_movie_of(x).rating_count or 0) if _movie_of(x) else 0,
            reverse=True,
        )
    elif current_sort == '-rating':
        movies_with_similarity.sort(
            key=lambda x: (_movie_of(x).rating or 0) if _movie_of(x) else 0,
            reverse=True,
        )
    elif current_sort == 'name':
        movies_with_similarity.sort(
            key=lambda x: (_movie_of(x).name.lower()) if _movie_of(x) else ''
        )
    elif current_sort == '-name':
        movies_with_similarity.sort(
            key=lambda x: (_movie_of(x).name.lower()) if _movie_of(x) else '',
            reverse=True,
        )
    elif current_sort == '-first_release_date':
        movies_with_similarity.sort(
            key=lambda x: (_movie_of(x).first_release_date or '') if _movie_of(x) else '',
            reverse=True,
        )
    else:  # Default to similarity
        movies_with_similarity.sort(key=lambda x: x.get('similarity', 0), reverse=True)