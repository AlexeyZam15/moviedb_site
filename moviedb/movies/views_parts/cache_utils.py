# movies/views_parts/cache_utils.py
"""Cache utilities for Movie views (Movie-only)."""

import time
import json
import hashlib
import logging
import pickle
from functools import lru_cache, wraps
from typing import Dict, List, Any, Optional

from django.core.cache import cache
from django.db.models import Count
from django.http import HttpResponse
from django.utils import timezone
from django.conf import settings

from ..models import (
    Movie, Genre, Keyword, Theme, Company, Series,
)

redis_client = getattr(settings, 'redis_client', None)

# ===== CACHE CONFIGURATION =====
CACHE_TIMES = {
    'short': {
        'filter_data': 1800,
        'years_range': 3600,
        'genres_list': 7200,
        'static_pages': 3600,
    },
    'medium': {
        'similar_movies': 43200,
        'filtered_movies': 7200,
        'popular_keywords': 14400,
    },
    'long': {
        'themes': 86400 * 3,
        'production_companies': 86400 * 3,
        'series': 86400 * 3,
    },
    'aggressive': {
        'full_page': 900,
        'virtual_search': 1800,
        'similar_for_movie': 10800,
    }
}

CACHE_VERSION = 'v22'

logger = logging.getLogger('movie_similarity')
logger.setLevel(logging.DEBUG)

import sys

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)


# ===== CACHE HELPERS =====

@lru_cache(maxsize=1024)
def _cached_string_to_int_list(param_str: str) -> List[int]:
    """Cached conversion of parameter strings to integer lists."""
    if not param_str:
        return []
    result = []
    for part in param_str.split(','):
        part = part.strip()
        if part and part.isdigit():
            result.append(int(part))
    return result


def _generate_cache_key(data: Dict) -> str:
    """Generate cache key from data."""
    cache_key_str = ''.join(f"{k}:{v}" for k, v in sorted(data.items()))
    return f"cache_{hashlib.md5(cache_key_str.encode()).hexdigest()}"


def get_cache_key(prefix: str, data: Dict = None, version: str = None) -> str:
    """Generate versioned cache key."""
    version = version or CACHE_VERSION
    if data:
        data_str = json.dumps(data, sort_keys=True, default=str)
        key_hash = hashlib.md5(data_str.encode()).hexdigest()
        return f"{prefix}_{version}_{key_hash}"
    return f"{prefix}_{version}"


def cache_get_or_set(key: str, func: callable, timeout: int,
                     cache_group: str = None) -> Any:
    """Get from cache or calculate and set with timeout."""
    cached = cache.get(key)
    if cached is not None:
        if isinstance(cached, dict) and cached.get('__cache_wrapper') is True:
            return cached['data']
        return cached

    result = func()

    if not isinstance(result, (str, int, float, list, dict, tuple)):
        cache_value = {
            '__cache_wrapper': True,
            'data': result,
            'timestamp': time.time()
        }
    else:
        cache_value = result

    cache.set(key, cache_value, timeout)

    if cache_group:
        group_key = f"cache_group_{cache_group}"
        group_members = cache.get(group_key, [])
        if key not in group_members:
            group_members.append(key)
            cache.set(group_key, group_members, timeout + 3600)

    return result


def invalidate_cache_group(cache_group: str) -> int:
    """Invalidate all cache keys in a group."""
    group_key = f"cache_group_{cache_group}"
    group_members = cache.get(group_key, [])

    deleted_count = 0
    for key in group_members:
        if cache.delete(key):
            deleted_count += 1

    cache.delete(group_key)
    return deleted_count


def cache_multi_get(keys: List[str]) -> Dict[str, Any]:
    """Multi-get from cache."""
    if not keys:
        return {}
    cached = cache.get_many(keys)
    result = {}
    for key, value in cached.items():
        if isinstance(value, dict) and value.get('__cache_wrapper'):
            result[key] = value['data']
        else:
            result[key] = value
    return result


def cache_multi_set(items: Dict[str, Any], timeout: int) -> None:
    """Multi-set to cache."""
    if not items:
        return
    cache_items = {}
    for key, value in items.items():
        if not isinstance(value, (str, int, float, list, dict, tuple)):
            cache_items[key] = {
                '__cache_wrapper': True,
                'data': value,
                'timestamp': time.time()
            }
        else:
            cache_items[key] = value
    cache.set_many(cache_items, timeout)


# ===== CACHE DECORATORS =====

def cache_view(timeout: int = 300, vary_on: List[str] = None,
               cache_group: str = None):
    """Decorator to cache view responses."""

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            key_parts = [
                request.path,
                request.GET.urlencode() if vary_on is None else
                '&'.join(f"{k}={request.GET.get(k, '')}" for k in vary_on if k in request.GET)
            ]
            cache_key = get_cache_key('view', {'parts': key_parts})

            cached_response = cache.get(cache_key)
            if cached_response and isinstance(cached_response, HttpResponse):
                cached_response['X-Cache-Hit'] = 'View-Decorator'
                return cached_response

            response = view_func(request, *args, **kwargs)

            if response.status_code == 200:
                cache.set(cache_key, response, timeout)
                if cache_group:
                    group_key = f"cache_group_{cache_group}"
                    group_members = cache.get(group_key, [])
                    if cache_key not in group_members:
                        group_members.append(cache_key)
                        cache.set(group_key, group_members, timeout + 3600)

            response['X-Cache-Hit'] = 'Miss'
            return response

        return _wrapped_view

    return decorator


def cache_method(timeout: int = 300, key_prefix: str = None):
    """Decorator to cache method results."""

    def decorator(method):
        @wraps(method)
        def _wrapped_method(self, *args, **kwargs):
            prefix = key_prefix or f"{self.__class__.__name__}_{method.__name__}"
            key_data = {
                'args': args,
                'kwargs': kwargs,
                'self_id': id(self) if hasattr(self, 'id') else None
            }
            cache_key = get_cache_key(prefix, key_data)
            cached = cache.get(cache_key)
            if cached is not None:
                return cached
            result = method(self, *args, **kwargs)
            cache.set(cache_key, result, timeout)
            return result

        return _wrapped_method

    return decorator


# ===== CACHE MANAGEMENT =====

def warm_cache_for_home_page() -> Dict:
    """Warm cache for home page data."""
    logger.info("Warming cache for home page...")

    data_to_warm = [
        ('years_range', lambda: get_release_years_range()),
        ('optimized_filter_data', _get_optimized_filter_data),
        ('genres_list', lambda: list(Genre.objects.all().only('id', 'name').order_by('name'))),
    ]

    results = {}
    for key, func in data_to_warm:
        try:
            cache_key = get_cache_key(key)
            data = func()
            cache.set(cache_key, data, CACHE_TIMES['short'].get(key, 3600))
            results[key] = 'warmed'
        except Exception as e:
            results[key] = f'error: {str(e)}'

    # Warm popular queries (Movie-only)
    popular_queries = [
        {'sort': '-rating_count'},
        {'sort': '-rating'},
        {'sort': '-first_release_date'},
        {'g': '1,2,3'},
    ]

    from django.test import RequestFactory
    factory = RequestFactory()

    for i, query in enumerate(popular_queries):
        try:
            request = factory.get('/movies/', query)
            params = extract_request_params(request)  # noqa: F821 (импорт в base_views, здесь lazy)
            # Здесь не кэшируем результат — просто прогреваем фильтры/годы.
            results[f'query_{i}'] = 'warmed'
        except Exception as e:
            results[f'query_{i}'] = f'error: {str(e)}'

    return results


def clear_movie_list_cache() -> Dict:
    """Clear all Movie list related cache."""
    logger.info("Clearing Movie list cache...")

    groups_to_clear = [
        'movie_list_pages',
        'movie_list_data',
        'movie_list_data_first_page',
        'filter_data',
        'similar_movies',
        'all_movies',
        'static_data',
    ]

    results = {}
    for group in groups_to_clear:
        try:
            deleted = invalidate_cache_group(group)
            results[group] = f'deleted {deleted} keys'
        except Exception as e:
            results[group] = f'error: {str(e)}'

    return results


# Алиас для обратной совместимости
clear_game_list_cache = clear_movie_list_cache


def get_cache_stats() -> Dict:
    """Get cache statistics."""
    stats = {
        'total_keys_estimated': 'N/A',
        'memory_usage': 'N/A',
        'hit_rate': 'N/A',
    }
    try:
        test_keys = [
            get_cache_key('years_range'),
            get_cache_key('optimized_filter_data'),
            get_cache_key('genres_list'),
        ]
        cached = cache.get_many(test_keys)
        stats['test_keys_cached'] = f"{len(cached)}/{len(test_keys)}"
    except Exception as e:
        stats['error'] = str(e)
    return stats


# ===== YEARS / STATIC DATA =====

@lru_cache(maxsize=1)
def get_release_years_range():
    """Get min and max release years from database."""
    cache_key = 'release_years_range_v1'
    cached_data = cache.get(cache_key)
    if cached_data:
        return cached_data

    try:
        from django.db.models import Min, Max
        years_range = Movie.objects.filter(
            first_release_date__isnull=False
        ).aggregate(
            min_year=Min('first_release_date__year'),
            max_year=Max('first_release_date__year')
        )
        min_year = years_range['min_year'] or 1970
        max_year = years_range['max_year'] or timezone.now().year
        result = {
            'min_year': int(min_year),
            'max_year': int(max_year),
        }
        cache.set(cache_key, result, CACHE_TIMES['short']['years_range'])
        return result
    except Exception as e:
        logger.error(f"Error getting release years range: {e}")
        return {'min_year': 1970, 'max_year': timezone.now().year}


def _get_cached_years_range() -> Dict:
    """Get years range with multi-layer caching."""
    cache_key = get_cache_key('years_range')
    return cache_get_or_set(
        cache_key,
        lambda: get_release_years_range(),
        CACHE_TIMES['short']['years_range'],
        cache_group='static_data'
    )


def _get_cached_genres_list() -> List:
    """Get genres list with caching."""
    cache_key = get_cache_key('genres_list')
    return cache_get_or_set(
        cache_key,
        lambda: list(Genre.objects.all().only('id', 'name').order_by('name')),
        CACHE_TIMES['short']['genres_list'],
        cache_group='static_data'
    )


# ===== FILTER DATA =====

def _fetch_optimized_filter_data(selected_keyword_ids: List[int] = None) -> Dict[str, List]:
    """Загружает данные для фильтров из БД (Movie-only)."""
    print("[FETCH] Loading filter data from database...")

    genres = list(Genre.objects.annotate(
        movie_count=Count('movies', distinct=True)
    ).filter(movie_count__gt=0).only('id', 'name').order_by('name'))

    top_keywords = list(Keyword.objects.filter(movies__isnull=False).only('id', 'name').order_by('name')[:200])

    top_keyword_ids = {k.id for k in top_keywords}
    if selected_keyword_ids:
        selected_keywords = list(Keyword.objects.filter(
            id__in=selected_keyword_ids
        ).only('id', 'name'))
        for kw in selected_keywords:
            if kw.id not in top_keyword_ids:
                top_keywords.append(kw)

    keywords = top_keywords
    popular_keywords = list(Keyword.objects.filter(movies__isnull=False).only('id', 'name').order_by('name')[:100])

    themes = list(Theme.objects.annotate(
        movie_count=Count('movies', distinct=True)
    ).filter(movie_count__gt=0).only('id', 'name').order_by('name'))

    developers = list(Company.objects.annotate(
        movie_count=Count('movies', distinct=True)
    ).filter(movie_count__gt=0).only('id', 'name').order_by('name'))

    series = list(Series.objects.annotate(
        movie_count=Count('movies', distinct=True)
    ).filter(movie_count__gt=0).only('id', 'name').order_by('name'))

    return {
        'genres': genres,
        'keywords': keywords,
        'popular_keywords': popular_keywords,
        'themes': themes,
        'developers': developers,
        'series': series,
    }


def _get_optimized_filter_data(selected_keyword_ids: List[int] = None) -> Dict[str, List]:
    import hashlib as _hashlib
    import json as _json
    import pickle as _pickle

    cache_data = {
        'version': 'v14',
        'selected_keywords': sorted(selected_keyword_ids or []),
    }
    cache_key_str = _json.dumps(cache_data, sort_keys=True)
    cache_key_hash = _hashlib.md5(cache_key_str.encode()).hexdigest()
    cache_key = f'optimized_filter_data_{cache_key_hash}'

    if redis_client is None:
        return _fetch_optimized_filter_data(selected_keyword_ids)

    try:
        cached_data = redis_client.get(cache_key)
        if cached_data:
            print(f"[CACHE HIT] optimized_filter_data for key {cache_key_hash[:8]}")
            return _pickle.loads(cached_data)
    except Exception as e:
        print(f"[CACHE ERROR] redis get failed: {e}; falling back to DB")
        return _fetch_optimized_filter_data(selected_keyword_ids)

    print(f"[CACHE MISS] optimized_filter_data for key {cache_key_hash[:8]}")
    result = _fetch_optimized_filter_data(selected_keyword_ids)

    try:
        redis_client.setex(cache_key, 3600, _pickle.dumps(result))
    except Exception as e:
        print(f"[CACHE ERROR] redis setex failed: {e}")

    return result


def _get_cached_movie(movie_id: str) -> Optional[Movie]:
    """Get Movie from cache or database."""
    cache_key = get_cache_key('movie', {'id': movie_id})

    def fetch_movie():
        try:
            return Movie.objects.only('id', 'name').get(pk=int(movie_id))
        except (Movie.DoesNotExist, ValueError):
            return None

    return cache_get_or_set(
        cache_key,
        fetch_movie,
        3600,
        cache_group='movies'
    )


# Алиас для обратной совместимости
_get_cached_game = _get_cached_movie


def _get_cached_filter_data() -> Dict[str, List]:
    """Получаем кэшированные данные для всех фильтров (Movie-only)."""
    filter_data = cache.get('optimized_filter_data_movie_v1')

    if not filter_data:
        filter_data = {
            'genres': list(Genre.objects.annotate(
                movie_count=Count('movies', distinct=True)
            ).filter(movie_count__gt=0).only('id', 'name').order_by('name')),

            'keywords': list(Keyword.objects.all()
                             .only('id', 'name').order_by('name')),

            'popular_keywords': list(Keyword.objects.filter(movies__isnull=False).only('id', 'name').order_by('name')[:50]),

            'themes': list(Theme.objects.annotate(
                movie_count=Count('movies', distinct=True)
            ).filter(movie_count__gt=0).only('id', 'name').order_by('name')),

            'developers': list(Company.objects.annotate(
                movie_count=Count('movies', distinct=True)
            ).filter(movie_count__gt=0).only('id', 'name').order_by('name')),

            'series': list(Series.objects.annotate(
                movie_count=Count('movies', distinct=True)
            ).filter(movie_count__gt=0).only('id', 'name').order_by('name')),
        }
        cache.set('optimized_filter_data_movie_v1', filter_data, 7200)

    return filter_data