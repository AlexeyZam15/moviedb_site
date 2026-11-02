# movies/analyze/utils.py
"""
Вспомогательные функции для анализа игр (TMDB-модель).
"""

from typing import Dict, Any, List
from movies.models import Movie


def prepare_text_for_display(text: str, analysis_result: Dict = None, mode: str = 'criteria') -> str:
    """Подготавливает текст для отображения с подсветкой."""
    if not text:
        return ''

    if not analysis_result or not analysis_result.get('pattern_info'):
        return text

    from .analyze_views import highlight_matches_in_text
    return highlight_matches_in_text(text, analysis_result, mode)


def get_description_stats(Movie: Movie) -> Dict[str, Dict]:
    """Возвращает статистику по всем описаниям игры.

    В TMDB-модели доступны только summary и tagline.
    """
    descriptions = {
        'summary': Movie.summary or '',
        'tagline': Movie.tagline or '',
    }

    stats = {}
    for key, text in descriptions.items():
        if text.strip():
            stats[key] = {
                'length': len(text),
                'word_count': len(text.split()),
                'lines': text.count('\n') + 1,
                'has_content': True
            }
        else:
            stats[key] = {
                'length': 0,
                'word_count': 0,
                'lines': 0,
                'has_content': False
            }

    return stats


def get_game_text(Movie: Movie, source: str = 'default') -> str:
    """Получает текст игры в зависимости от источника.

    В TMDB-модели доступны только summary и tagline.
    """
    if source == 'all':
        texts = []
        if Movie.summary:
            texts.append(Movie.summary)
        if Movie.tagline:
            texts.append(Movie.tagline)
        return ' '.join(texts) if texts else ''
    else:
        if Movie.summary:
            return Movie.summary
        elif Movie.tagline:
            return Movie.tagline
        else:
            return ''


def update_game_criteria(Movie: Movie, results: Dict, is_keywords: bool) -> bool:
    """Обновляет критерии игры в базе данных.

    В TMDB-модели: genres/themes/keywords. Нет perspectives/game_modes.
    """
    try:
        if is_keywords:
            keywords = results.get('keywords', {}).get('items', [])
            if keywords:
                keyword_ids = [k['id'] for k in keywords]
                from movies.models import Keyword
                keyword_objects = Keyword.objects.filter(id__in=keyword_ids)
                Movie.keywords.add(*keyword_objects)
                return True
        else:
            updated = False

            genres = results.get('genres', {}).get('items', [])
            if genres:
                genre_ids = [g['id'] for g in genres]
                from movies.models import Genre
                genre_objects = Genre.objects.filter(id__in=genre_ids)
                Movie.genres.add(*genre_objects)
                updated = True

            themes = results.get('themes', {}).get('items', [])
            if themes:
                theme_ids = [t['id'] for t in themes]
                from movies.models import Theme
                theme_objects = Theme.objects.filter(id__in=theme_ids)
                Movie.themes.add(*theme_objects)
                updated = True

            return updated
    except Exception as e:
        import logging
        logging.error(f"Ошибка при обновлении игры {Movie.id}: {e}")
        return False

    return False


def format_game_response(Movie: Movie, text: str, text_source: str) -> Dict[str, Any]:
    """Форматирует базовую информацию об игре для ответа."""
    return {
        'Movie': {
            'id': Movie.id,
            'name': Movie.name,
            'tmdb_id': Movie.tmdb_id,
            'first_release_date': Movie.first_release_date.isoformat() if Movie.first_release_date else None,
        },
        'analysis_context': {
            'text_source': text_source,
            'text_length': len(text),
            'has_text': len(text) > 0
        }
    }


def create_error_response(error_type: str, message: str, **kwargs) -> Dict[str, Any]:
    """Создает структурированный ответ об ошибке."""
    import time
    response = {
        'success': False,
        'error_type': error_type,
        'error_message': message,
        'timestamp': time.time()
    }
    response.update(kwargs)
    return response