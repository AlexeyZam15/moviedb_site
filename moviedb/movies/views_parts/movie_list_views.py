# movies/views_parts/movie_list_views.py
"""
Views for movie list, filtering, search and similarity.
Rewritten for the Movie-only domain (no games, no VirtualGame).
"""

import time
import json
import hashlib
import logging
from typing import Dict, List, Any, Optional, Tuple
from urllib.parse import urlencode

from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.db.models import Count, Prefetch, Q
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.core.cache import cache
from django.utils import timezone
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe
from django.conf import settings

from ..models import (
    Movie, Genre, Keyword, Company, Collection, Theme, Image,
    MovieCardCache, MovieCountsCache,
)
from ..similarity import moviesimilarity as movieSimilarity
from ..utils.movie_card_utils import MovieCardCreator
from .base_views import (
    CACHE_TIMES,
    CACHE_VERSION,
    extract_request_params,
    convert_params_to_lists,
    _apply_filters,
    _apply_search_filters,
    get_objects_by_ids,
    get_cache_key,
    cache_get_or_set,
    invalidate_cache_group,
    _get_optimized_filter_data,
    _get_cached_years_range,
    get_release_years_range,
    _sort_similar_movies as _sort_similar_movies_base,
    _format_similar_movies_data,
    _prefetch_similar_movies,
    logger as base_logger,
)

logger = logging.getLogger('movie_similarity')
logger.setLevel(logging.DEBUG)

redis_client = getattr(settings, 'redis_client', None)


# ===== HELPER: PAGINATION =====

def _paginate_queryset(queryset, page_number: int, per_page: int = 24):
    """Paginate a queryset, returning (page_obj, paginator)."""
    paginator = Paginator(queryset, per_page)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    return page_obj, paginator


def _build_pagination_context(page_obj, paginator, request: HttpRequest) -> Dict[str, Any]:
    """Build pagination context for templates."""
    get_params = request.GET.copy()
    get_params.pop('page', None)
    base_query = get_params.urlencode()

    return {
        'page_obj': page_obj,
        'paginator': paginator,
        'current_page': page_obj.number,
        'has_previous': page_obj.has_previous(),
        'has_next': page_obj.has_next(),
        'previous_page': page_obj.previous_page_number() if page_obj.has_previous() else None,
        'next_page': page_obj.next_page_number() if page_obj.has_next() else None,
        'total_pages': paginator.num_pages,
        'total_count': paginator.count,
        'base_query': base_query,
    }


# ===== SOURCE MOVIE RESOLUTION =====

def get_source_movie(request: HttpRequest) -> Optional[Movie]:
    """Resolve the source Movie from request parameters."""
    source_movie_id = request.GET.get('source_movie', '').strip()
    if not source_movie_id:
        return None

    try:
        movie_id = int(source_movie_id)
    except (ValueError, TypeError):
        return None

    try:
        return Movie.objects.only(
            'id', 'name', 'rating', 'rating_count',
            'first_release_date', 'cover_url',
        ).prefetch_related(
            'genres', 'themes', 'production_companies',
            Prefetch('images', queryset=Image.objects.filter(image_type='backdrop').order_by('-vote_average', 'id')[:5], to_attr='card_backdrops'),
        ).get(pk=movie_id)
    except Movie.DoesNotExist:
        return None


# ===== SIMILARITY RESULT NORMALIZATION =====

def _normalize_similar_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Приводит результат find_similar_movies к формату с ключами 'Movie' и 'movie'."""
    if not results:
        return []

    normalized = []
    for item in results:
        movie_obj = item.get('movie') or item.get('Movie')
        if movie_obj is None:
            continue

        new_item = dict(item)
        new_item['movie'] = movie_obj
        new_item['Movie'] = movie_obj
        normalized.append(new_item)

    return normalized


# ===== SIMILARITY: BY CRITERIA =====

def get_similar_movies_for_criteria(
        selected_criteria: Dict[str, List[int]],
        sort: str = '-rating_count',
        limit: int = 500,
        search_filters: Optional[Dict] = None,
) -> List[Dict[str, Any]]:
    """Find movies similar to a set of selected criteria."""
    override_criteria = {
        'genres': selected_criteria.get('genres', []),
        'keywords': selected_criteria.get('keywords', []),
        'themes': selected_criteria.get('themes', []),
        'production_companies': selected_criteria.get('developers', []),
        'series_id': selected_criteria.get('series_id'),
    }

    engine = movieSimilarity(verbose=False)
    results = engine.find_similar_movies(
        source_movie=None,
        min_similarity=0,
        limit=limit,
        search_filters=search_filters,
        override_criteria=override_criteria,
    )

    normalized = _normalize_similar_results(results)
    formatted = _format_similar_movies_data(normalized)
    _sort_similar_movies_base(formatted, sort)
    return formatted


# ===== SIMILARITY: BY MOVIE =====

def get_similar_movies_for_movie(
        source_movie: Movie,
        sort: str = '-rating_count',
        limit: int = 500,
        search_filters: Optional[Dict] = None,
        override_criteria: Optional[Dict[str, List[int]]] = None,
) -> List[Dict[str, Any]]:
    """Find movies similar to a specific source movie."""
    engine = movieSimilarity(verbose=False)
    results = engine.find_similar_movies(
        source_movie=source_movie,
        min_similarity=0,
        limit=limit,
        search_filters=search_filters,
        override_criteria=override_criteria,
    )

    normalized = _normalize_similar_results(results)
    formatted = _format_similar_movies_data(normalized)
    _sort_similar_movies_base(formatted, sort)
    return formatted


# ===== MAIN MOVIE LIST VIEW =====


def movie_list(request: HttpRequest) -> HttpResponse:
    """Main movie list view with filtering, sorting, pagination."""
    # [DBG] TEMP: movie_list DB diagnostics (extended)
    try:
        from django.db import connection as _dbg_conn
        _c = _dbg_conn.cursor()
        _c.execute("SELECT current_user, current_database(), current_schema()")
        print(f"[DBG /movies/] user/db/schema = {_c.fetchone()}")
        _c.execute("SELECT inet_server_addr(), inet_server_port()")
        print(f"[DBG /movies/] inet_server_addr/port = {_c.fetchone()}")
        _c.execute("SHOW search_path")
        print(f"[DBG /movies/] SHOW search_path = {_c.fetchone()}")
        _c.execute("SELECT current_setting('search_path')")
        print(f"[DBG /movies/] current_setting(search_path) = {_c.fetchone()}")
        _c.execute("SELECT table_schema, table_name FROM information_schema.tables WHERE table_name='movies_movie_themes'")
        print(f"[DBG /movies/] information_schema.tables = {_c.fetchall()}")
        _c.execute("SELECT to_regclass('public.movies_movie_themes')")
        print(f"[DBG /movies/] to_regclass(public...) = {_c.fetchone()}")
        _c.execute("SELECT to_regclass('movies_movie_themes')")
        print(f"[DBG /movies/] to_regclass(...) = {_c.fetchone()}")
        try:
            _c.execute("SELECT count(*) FROM public.movies_movie_themes")
            print(f"[DBG /movies/] count(public.movies_movie_themes) = {_c.fetchone()}")
        except Exception as _e1:
            print(f"[DBG /movies/] count(public...) FAIL: {_e1}")
        try:
            _c.execute("SELECT count(*) FROM movies_movie_themes")
            print(f"[DBG /movies/] count(movies_movie_themes) = {_c.fetchone()}")
        except Exception as _e2:
            print(f"[DBG /movies/] count(movies_movie_themes) FAIL: {_e2}")
        print(f"[DBG /movies/] settings NAME={_dbg_conn.settings_dict.get('NAME')}, USER={_dbg_conn.settings_dict.get('USER')}, HOST={_dbg_conn.settings_dict.get('HOST')}, PORT={_dbg_conn.settings_dict.get('PORT')}, CONN_MAX_AGE={_dbg_conn.settings_dict.get('CONN_MAX_AGE')}")
    except Exception as _e:
        print(f"[DBG /movies/] FAIL: {_e}")
    start_time = time.time()

    params = extract_request_params(request)
    selected_criteria = convert_params_to_lists(params)
    sort = params.get('sort') or '-rating_count'
    page_number = params.get('page') or '1'
    seed = params.get('seed') or ''

    find_similar = params.get('find_similar') == '1'
    source_movie = get_source_movie(request)

    similarity_keys = ['genres', 'keywords', 'themes', 'developers']
    if find_similar and (source_movie or any(selected_criteria.get(k) for k in similarity_keys)):
        mode = 'similarity'
    else:
        mode = 'regular'

    cache_key_data = {
        'params': {k: v for k, v in params.items() if k != '_present'},
        'sort': sort,
        'page': page_number,
        'mode': mode,
        'source_movie_id': source_movie.id if source_movie else None,
        'seed': seed,
    }
    cache_key = get_cache_key('movie_list_data', cache_key_data)

    cached_data = cache.get(cache_key)
    if cached_data:
        context = cached_data
        context['execution_time'] = round(time.time() - start_time, 3)
        context['cached'] = True
        return render(request, 'movies/movie_list.html', context)

    if mode == 'similarity':
        search_filters = {
            'genres': selected_criteria.get('genres', []),
            'keywords': selected_criteria.get('keywords', []),
            'themes': selected_criteria.get('themes', []),
            'release_year_start': selected_criteria.get('release_year_start'),
            'release_year_end': selected_criteria.get('release_year_end'),
        }

        if source_movie:
            similar = get_similar_movies_for_movie(
                source_movie=source_movie,
                sort=sort,
                limit=500,
                search_filters=search_filters,
            )
        else:
            similar = get_similar_movies_for_criteria(
                selected_criteria=selected_criteria,
                sort=sort,
                limit=500,
                search_filters=search_filters,
            )

        movie_ids = []
        similarity_map = {}
        for item in similar:
            mv = item.get('Movie') or item.get('movie')
            if mv is not None and hasattr(mv, 'id'):
                movie_ids.append(mv.id)
                similarity_map[mv.id] = item.get('similarity', 0)

        movies_qs = Movie.objects.filter(id__in=movie_ids).prefetch_related(
            Prefetch('genres', queryset=Genre.objects.only('id', 'name')),
            Prefetch('themes', queryset=Theme.objects.only('id', 'name')),
            Prefetch('production_companies', queryset=Company.objects.only('id', 'name')),
            Prefetch('images', queryset=Image.objects.filter(image_type='backdrop').order_by('-vote_average', 'id')[:5], to_attr='card_backdrops'),
        ).only(
            'id', 'name', 'rating', 'rating_count',
            'first_release_date', 'cover_url',
        )
        movie_by_id = {m.id: m for m in movies_qs}
        ordered_movies = []
        for mid in movie_ids:
            if mid in movie_by_id:
                m = movie_by_id[mid]
                m.similarity = similarity_map.get(mid, 0)
                ordered_movies.append(m)

        page_obj, paginator = _paginate_queryset(ordered_movies, int(page_number), 24)
        movies_page = page_obj.object_list
        show_similarity = True

    else:
        queryset = Movie.objects.all().prefetch_related(
            Prefetch('genres', queryset=Genre.objects.only('id', 'name')),
            Prefetch('themes', queryset=Theme.objects.only('id', 'name')),
            Prefetch('production_companies', queryset=Company.objects.only('id', 'name')),
            Prefetch('images', queryset=Image.objects.filter(image_type='backdrop').order_by('-vote_average', 'id')[:5], to_attr='card_backdrops'),
        ).only(
            'id', 'name', 'rating', 'rating_count',
            'first_release_date', 'cover_url',
        )

        queryset = _apply_filters(queryset, selected_criteria)

        search_text = params.get('q') or params.get('search_k') or ''
        if search_text:
            search_filters = {'text_query': search_text}
            queryset = _apply_search_filters(queryset, search_filters)

        sort_map = {
            '-rating_count': '-rating_count',
            '-rating': '-rating',
            'name': 'name',
            '-name': '-name',
            '-first_release_date': '-first_release_date',
            '-date_added': '-date_added',
        }
        queryset = queryset.order_by(sort_map.get(sort, '-rating_count'))

        page_obj, paginator = _paginate_queryset(queryset, int(page_number), 24)
        movies_page = page_obj.object_list
        show_similarity = False

    movie_ids = [m.id for m in movies_page]
    missing_ids = [
        mid for mid in movie_ids
        if not MovieCardCache.objects.filter(movie_id=mid, is_active=True).exists()
    ]
    if missing_ids:
        try:
            MovieCardCreator.create_cards_for_movies(
                movie_ids=missing_ids,
                show_similarity=show_similarity,
                batch_size=100,
                force=False,
            )
        except Exception as e:
            logger.warning(f"Card creation failed for {len(missing_ids)} movies: {e}")

    cards = MovieCardCache.objects.filter(
        movie_id__in=movie_ids, is_active=True
    )
    cards_map = {c.movie_id: c for c in cards}

    movies_with_cards = []
    for m in movies_page:
        movies_with_cards.append({
            'Movie': m,
            'movie': m,
            'card': cards_map.get(m.id),
            'similarity': getattr(m, 'similarity', None),
        })

    filter_data = _get_optimized_filter_data(selected_criteria.get('keywords', []))
    years_range = _get_cached_years_range()

    pagination_ctx = _build_pagination_context(page_obj, paginator, request)

    context = {
        'movies_with_cards': movies_with_cards,
        'selected_criteria': selected_criteria,
        'selected_genres': selected_criteria.get('genres', []),
        'selected_keywords': selected_criteria.get('keywords', []),
        'selected_themes': selected_criteria.get('themes', []),
        'selected_developers': selected_criteria.get('developers', []),
        'selected_release_year_start': selected_criteria.get('release_year_start'),
        'selected_release_year_end': selected_criteria.get('release_year_end'),
        'filter_data': filter_data,
        'years_range': years_range,
        'sort': sort,
        'mode': mode,
        'find_similar': find_similar,
        'source_movie': source_movie,
        'show_similarity': show_similarity,
        'seed': seed,
        'search_text': params.get('q') or params.get('search_k') or '',
        **pagination_ctx,
        'execution_time': round(time.time() - start_time, 3),
        'cached': False,
    }

    try:
        cache.set(cache_key, context, CACHE_TIMES['medium']['filtered_movies'])
    except Exception as e:
        logger.warning(f"Cache set failed: {e}")

    return render(request, 'movies/movie_list.html', context)


# ===== SEARCH RESULTS =====

def search_results(request: HttpRequest) -> HttpResponse:
    """Search movies by name. Redirects to movie_list with search parameter."""
    search_query = request.GET.get('q', '').strip()
    if not search_query:
        return redirect('game_list')

    from django.urls import reverse
    base_url = reverse('game_list')
    params = {
        'search_k': search_query,
        'find_similar': '0',
        'page': '1',
    }
    return redirect(f"{base_url}?{urlencode(params)}")


# ===== AJAX: LOAD MOVIES PAGE =====


def ajax_load_movies_page(request: HttpRequest) -> JsonResponse:
    """AJAX endpoint: returns rendered movie cards HTML for a given page."""
    try:
        params = extract_request_params(request)
        selected_criteria = convert_params_to_lists(params)
        sort = params.get('sort') or '-rating_count'
        page_number = int(params.get('page') or '1')
        find_similar = params.get('find_similar') == '1'
        source_movie = get_source_movie(request)
        seed = params.get('seed') or ''

        similarity_keys = ['genres', 'keywords', 'themes', 'developers']
        if find_similar and (source_movie or any(selected_criteria.get(k) for k in similarity_keys)):
            mode = 'similarity'
        else:
            mode = 'regular'

        if mode == 'similarity':
            search_filters = {
                'genres': selected_criteria.get('genres', []),
                'keywords': selected_criteria.get('keywords', []),
                'themes': selected_criteria.get('themes', []),
                'release_year_start': selected_criteria.get('release_year_start'),
                'release_year_end': selected_criteria.get('release_year_end'),
            }

            if source_movie:
                similar = get_similar_movies_for_movie(
                    source_movie=source_movie,
                    sort=sort,
                    limit=500,
                    search_filters=search_filters,
                )
            else:
                similar = get_similar_movies_for_criteria(
                    selected_criteria=selected_criteria,
                    sort=sort,
                    limit=500,
                    search_filters=search_filters,
                )

            movie_ids = []
            similarity_map = {}
            for item in similar:
                mv = item.get('Movie') or item.get('movie')
                if mv is not None and hasattr(mv, 'id'):
                    movie_ids.append(mv.id)
                    similarity_map[mv.id] = item.get('similarity', 0)

            movies_qs = Movie.objects.filter(id__in=movie_ids).prefetch_related(
                Prefetch('genres', queryset=Genre.objects.only('id', 'name')),
                Prefetch('themes', queryset=Theme.objects.only('id', 'name')),
                Prefetch('production_companies', queryset=Company.objects.only('id', 'name')),
                Prefetch('images', queryset=Image.objects.filter(image_type='backdrop').order_by('-vote_average', 'id')[:5], to_attr='card_backdrops'),
            ).only(
                'id', 'name', 'rating', 'rating_count',
                'first_release_date', 'cover_url',
            )
            movie_by_id = {m.id: m for m in movies_qs}
            ordered = []
            for mid in movie_ids:
                if mid in movie_by_id:
                    m = movie_by_id[mid]
                    m.similarity = similarity_map.get(mid, 0)
                    ordered.append(m)

            page_obj, paginator = _paginate_queryset(ordered, page_number, 24)
            movies_page = page_obj.object_list
            show_similarity = True
        else:
            queryset = Movie.objects.all().prefetch_related(
                Prefetch('genres', queryset=Genre.objects.only('id', 'name')),
                Prefetch('themes', queryset=Theme.objects.only('id', 'name')),
                Prefetch('production_companies', queryset=Company.objects.only('id', 'name')),
                Prefetch('images', queryset=Image.objects.filter(image_type='backdrop').order_by('-vote_average', 'id')[:5], to_attr='card_backdrops'),
            ).only(
                'id', 'name', 'rating', 'rating_count',
                'first_release_date', 'cover_url',
            )

            queryset = _apply_filters(queryset, selected_criteria)

            search_text = params.get('q') or params.get('search_k') or ''
            if search_text:
                queryset = _apply_search_filters(queryset, {'text_query': search_text})

            sort_map = {
                '-rating_count': '-rating_count',
                '-rating': '-rating',
                'name': 'name',
                '-name': '-name',
                '-first_release_date': '-first_release_date',
                '-date_added': '-date_added',
            }
            queryset = queryset.order_by(sort_map.get(sort, '-rating_count'))

            page_obj, paginator = _paginate_queryset(queryset, page_number, 24)
            movies_page = page_obj.object_list
            show_similarity = False

        movie_ids = [m.id for m in movies_page]
        missing_ids = [
            mid for mid in movie_ids
            if not MovieCardCache.objects.filter(movie_id=mid, is_active=True).exists()
        ]
        if missing_ids:
            try:
                MovieCardCreator.create_cards_for_movies(
                    movie_ids=missing_ids,
                    show_similarity=show_similarity,
                    batch_size=100,
                    force=False,
                )
            except Exception as e:
                logger.warning(f"AJAX card creation failed: {e}")

        cards = MovieCardCache.objects.filter(movie_id__in=movie_ids, is_active=True)
        cards_map = {c.movie_id: c for c in cards}

        cards_html = []
        for idx, m in enumerate(movies_page):
            card = cards_map.get(m.id)
            if card:
                cards_html.append(card.rendered_card)
            else:
                cards_html.append(
                    render_to_string('movies/partials/_movie_card.html', {
                        'Movie': m,
                        'movie': m,
                        'show_similarity': show_similarity,
                        'current_page': page_number,
                        'game_index': idx,
                        'game_index_offset': (page_number - 1) * 24,
                        'forloop': {'counter0': idx, 'counter': idx + 1},
                    })
                )

        pagination_ctx = _build_pagination_context(page_obj, paginator, request)

        # Рендерим полный блок результатов: карточки + пагинация + hidden-поля
        results_context = {
            'movies': movies_page,
            'games_with_similarity': movies_page if show_similarity else None,
            'show_similarity': show_similarity,
            'source_game': None,
            'current_page': page_number,
            'total_pages': pagination_ctx['total_pages'],
            'total_count': pagination_ctx['total_count'],
            'page_obj': page_obj,
            'paginator': paginator,
            'is_paginated': paginator.num_pages > 1,
            'start_index': page_obj.start_index(),
            'end_index': page_obj.end_index(),
            'items_per_page': 24,
        }
        html = render_to_string('movies/movie_list/_movies_results.html', results_context)

        return JsonResponse({
            'success': True,
            'html': html,
            'pagination': {
                'current_page': pagination_ctx['current_page'],
                'total_pages': pagination_ctx['total_pages'],
                'has_previous': pagination_ctx['has_previous'],
                'has_next': pagination_ctx['has_next'],
                'previous_page': pagination_ctx['previous_page'],
                'next_page': pagination_ctx['next_page'],
                'total_count': pagination_ctx['total_count'],
            },
            'mode': mode,
        })

    except Exception as e:
        logger.error(f"ajax_load_movies_page error: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e),
        }, status=500)


# ===== AJAX: LOAD FILTERS =====

def ajax_load_filters(request: HttpRequest) -> JsonResponse:
    """AJAX endpoint: returns rendered filter sections HTML (Movie-only)."""
    try:
        params = extract_request_params(request)
        selected_criteria = convert_params_to_lists(params)

        filter_data = _get_optimized_filter_data(selected_criteria.get('keywords', []))
        years_range = _get_cached_years_range()

        current_year = timezone.now().year

        from ..utils.filter_renderer import FilterRenderer

        def _render(method_name: str, data, selected) -> str:
            """Безопасный вызов метода FilterRenderer; пустая строка если метода нет."""
            method = getattr(FilterRenderer, method_name, None)
            if method is None:
                return ''
            try:
                return method(data, selected)
            except Exception as exc:
                logger.warning(f"FilterRenderer.{method_name} failed: {exc}")
                return ''

        # Собираем ВСЕ секции (search + similarity) в словарь для _real_filters.html
        cached_filter_sections = {
            'search_genres':     _render('render_search_genres',     filter_data.get('genres', []),   selected_criteria.get('genres', [])),
            'search_keywords':   _render('render_search_keywords',   filter_data.get('keywords', []), selected_criteria.get('keywords', [])),
            'search_themes':     _render('render_search_themes',     filter_data.get('themes', []),   selected_criteria.get('themes', [])),
            'search_date':       _render('render_search_date_filter', years_range, params),
            'similarity_genres':   _render('render_similarity_genres',   filter_data.get('genres', []),   selected_criteria.get('genres', [])),
            'similarity_keywords': _render('render_similarity_keywords', filter_data.get('keywords', []), selected_criteria.get('keywords', [])),
            'similarity_themes':   _render('render_similarity_themes',   filter_data.get('themes', []),   selected_criteria.get('themes', [])),
        }

        # Контекст для _real_filters.html (табы, панели, hidden-поля, кнопки)
        find_similar_raw = params.get('find_similar', '0') if hasattr(params, 'get') else '0'
        find_similar_val = str(find_similar_raw) in ('1', 'true', 'True')
        source_game_val = params.get('source_game', '') if hasattr(params, 'get') else ''
        current_sort_val = params.get('sort', '') if hasattr(params, 'get') else ''

        context = {
            'cached_filter_sections': cached_filter_sections,
            'find_similar': find_similar_val,
            'current_sort': current_sort_val,
            'show_similarity': find_similar_val or bool(source_game_val),
            'source_game': source_game_val,
            'years_range': years_range,
            'current_year': current_year,
            'request': request,
        }

        html = render_to_string('movies/movie_list/_real_filters.html', context)

        return JsonResponse({
            'success': True,
            'html': html,
            'years_range': years_range,
            'current_year': current_year,
        })

    except Exception as e:
        logger.error(f"ajax_load_filters error: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e),
        }, status=500)


# ===== AJAX: LOAD KEYWORDS =====

def ajax_load_keywords(request: HttpRequest) -> JsonResponse:
    """AJAX endpoint: returns filtered keywords list for the keyword selector."""
    try:
        query = request.GET.get('q', '').strip()
        selected_ids = request.GET.get('selected', '')
        selected_id_list = [
            int(x) for x in selected_ids.split(',') if x.strip().isdigit()
        ] if selected_ids else []

        qs = (
            Keyword.objects.filter(movies__isnull=False)
            .annotate(usage_count=Count('movies', distinct=True))
        )

        if query:
            qs = qs.filter(name__icontains=query)

        qs = qs.order_by('-usage_count', 'name')[:200]

        results = []
        for kw in qs:
            results.append({
                'id': kw.id,
                'name': kw.name,
                'category': '',
                'usage_count': kw.usage_count,
                'selected': kw.id in selected_id_list,
            })

        return JsonResponse({
            'success': True,
            'keywords': results,
            'count': len(results),
        })

    except Exception as e:
        logger.error(f"ajax_load_keywords error: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e),
        }, status=500)


# ===== CACHE CLEARING =====

def clear_movie_list_cache_specific(request: HttpRequest) -> JsonResponse:
    """Clear movie list cache for specific groups."""
    try:
        groups = request.GET.getlist('group') or [
            'movie_list_pages',
            'movie_list_data',
            'movie_list_data_first_page',
            'filter_data',
            'similar_movies',
            'all_movies',
            'static_data',
        ]

        results = {}
        for group in groups:
            try:
                deleted = invalidate_cache_group(group)
                results[group] = f'deleted {deleted} keys'
            except Exception as e:
                results[group] = f'error: {str(e)}'

        return JsonResponse({
            'success': True,
            'results': results,
        })

    except Exception as e:
        logger.error(f"clear_movie_list_cache_specific error: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e),
        }, status=500)

game_list = movie_list

# На случай, если где-то ещё используется старое имя:
get_similar_movies_for_game = get_similar_movies_for_movie
get_source_game = get_source_movie


