# movies/utils/filter_renderer.py
"""Utility functions for rendering filter sections with caching."""

import logging
from typing import List, Optional
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

from ..models import Genre, Keyword, Theme

logger = logging.getLogger(__name__)


class FilterRenderer:
    """Класс для рендеринга секций фильтров без кэширования."""

    # ===== SEARCH SECTIONS =====

    @staticmethod
    def render_search_genres(genres: List[Genre], selected_ids: List[int]) -> str:
        """Рендерит секцию жанров для поиска напрямую."""
        html = render_to_string('movies/movie_list/filter_sections/_search_genres_section.html', {
            'genres': genres,
            'search_selected_genres': selected_ids,
            'search_selected_genres_objects': [
                g for g in genres if g.id in selected_ids
            ]
        })
        return mark_safe(html)

    @staticmethod
    def render_search_keywords(keywords: List[Keyword], selected_ids: List[int]) -> str:
        """Рендерит секцию ключевых слов для поиска напрямую."""
        html = render_to_string('movies/movie_list/filter_sections/_search_keywords_section.html', {
            'keywords': keywords,
            'search_selected_keywords': selected_ids,
            'search_selected_keywords_objects': [
                k for k in keywords if k.id in selected_ids
            ]
        })
        return mark_safe(html)

    @staticmethod
    def render_search_themes(themes: List[Theme], selected_ids: List[int]) -> str:
        """Рендерит секцию тем для поиска напрямую."""
        html = render_to_string('movies/movie_list/filter_sections/_search_themes_section.html', {
            'themes': themes,
            'search_selected_themes': selected_ids,
            'search_selected_themes_objects': [
                t for t in themes if t.id in selected_ids
            ]
        })
        return mark_safe(html)

    @staticmethod
    def render_search_date_filter(year_start: Optional[int], year_end: Optional[int],
                                  min_year: int, max_year: int, current_year: int) -> str:
        """Рендерит секцию фильтра даты для поиска напрямую."""
        html = render_to_string('movies/movie_list/filter_sections/_search_date_section.html', {
            'search_selected_release_year_start': year_start,
            'search_selected_release_year_end': year_end,
            'years_range': {'min_year': min_year, 'max_year': max_year},
            'current_year': current_year
        })
        return mark_safe(html)

    # ===== SIMILARITY SECTIONS =====

    @staticmethod
    def render_similarity_genres(genres: List[Genre], selected_ids: List[int]) -> str:
        """Рендерит секцию жанров для похожести напрямую."""
        html = render_to_string('movies/movie_list/filter_sections/_similarity_genres_section.html', {
            'genres': genres,
            'similarity_selected_genres': selected_ids,
            'similarity_selected_genres_objects': [
                g for g in genres if g.id in selected_ids
            ]
        })
        return mark_safe(html)

    @staticmethod
    def render_similarity_keywords(keywords: List[Keyword], selected_ids: List[int]) -> str:
        """Рендерит секцию ключевых слов для похожести напрямую."""
        html = render_to_string('movies/movie_list/filter_sections/_similarity_keywords_section.html', {
            'keywords': keywords,
            'similarity_selected_keywords': selected_ids,
            'similarity_selected_keywords_objects': [
                k for k in keywords if k.id in selected_ids
            ]
        })
        return mark_safe(html)

    @staticmethod
    def render_similarity_themes(themes: List[Theme], selected_ids: List[int]) -> str:
        """Рендерит секцию тем для похожести напрямую."""
        html = render_to_string('movies/movie_list/filter_sections/_similarity_themes_section.html', {
            'themes': themes,
            'similarity_selected_themes': selected_ids,
            'similarity_selected_themes_objects': [
                t for t in themes if t.id in selected_ids
            ]
        })
        return mark_safe(html)