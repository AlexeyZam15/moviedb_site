# movies/views.py
"""Optimized views for Movie similarity search with updated models."""

# Re-export all views from parts
from .views_parts.movie_list_views import (
    ajax_load_movies_page,
    ajax_load_filters,
    movie_list,
    game_list,  # алиас movie_list — нужен urls.py и reverse('game_list')
    search_results,
    get_similar_movies_for_criteria,
    get_similar_movies_for_movie,
    get_source_movie,
    clear_movie_list_cache_specific,
    ajax_load_keywords,
)

from .views_parts.game_detail_views import (
    game_detail,
)

from .views_parts.comparison_views import (
    game_comparison,
)

from .views_parts.other_views import (
    home,
    keyword_category_view,
    auto_login_admin,
    remove_theme_from_game,
    send_feedback,
)

# analyze_views отключён: view не зарегистрирован в urls.py; файл содержит
# ссылки на отсутствующие в Movie-модели поля. См. отдельную задачу.

from .views_parts.base_views import (
    # Helper classes
    SimpleSourceGame,

    # Cache management
    warm_cache_for_home_page,
    clear_game_list_cache,
    get_cache_stats,

    # Cache decorators
    cache_view,
    cache_method,

    # Cache functions
    get_cache_key,
    cache_get_or_set,
    invalidate_cache_group,
    cache_multi_get,
    cache_multi_set,

    # Helper functions
    extract_request_params,
    convert_params_to_lists,
    _apply_filters,
    get_objects_by_ids,

    # Year range
    get_release_years_range,
)

# Export everything
__all__ = [
    # Views
    'ajax_load_movies_page',
    'ajax_load_filters',
    'movie_list',
    'game_list',
    'search_results',
    'game_detail',
    'game_comparison',
    'home',
    'keyword_category_view',
    'auto_login_admin',
    'remove_theme_from_game',
    'send_feedback',

    # Helper classes
    'SimpleSourceGame',

    # Cache management
    'warm_cache_for_home_page',
    'clear_game_list_cache',
    'get_cache_stats',
    'clear_movie_list_cache_specific',

    # Cache decorators
    'cache_view',
    'cache_method',

    # Cache functions
    'get_cache_key',
    'cache_get_or_set',
    'invalidate_cache_group',
    'cache_multi_get',
    'cache_multi_set',

    # Helper functions
    'extract_request_params',
    'convert_params_to_lists',
    '_apply_filters',
    'get_objects_by_ids',

    # Similarity functions
    'get_similar_movies_for_criteria',
    'get_similar_movies_for_movie',
    'get_source_movie',

    # Year range
    'get_release_years_range',
]