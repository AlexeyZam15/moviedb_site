# movies/views_parts/comparison_views.py
"""Views for Movie comparison (Movie-only)."""

import logging
from django.shortcuts import render, get_object_or_404
from django.http import HttpRequest, HttpResponse, HttpResponseServerError
from django.db.models import Prefetch

from .base_views import convert_params_to_lists, SimpleSourceMovie
from ..similarity import moviesimilarity
from ..models import (
    Movie, Genre, Keyword, Theme, Company,
)

logger = logging.getLogger(__name__)


class CriteriaWrapper:
    """Обёртка над критериями поиска для шаблона сравнения."""

    def __init__(self, criteria):
        self.id = None
        self.name = "Search Criteria"
        self.genres = criteria.get('genres', [])
        self.keywords = criteria.get('keywords', [])
        self.themes = criteria.get('themes', [])
        self.production_companies = criteria.get('developers', [])
        self.series_id = criteria.get('series_id')

    def genres_list(self):
        return self.genres

    def keywords_list(self):
        return self.keywords

    def themes_list(self):
        return self.themes

    def production_companies_list(self):
        return self.production_companies


def _build_override_criteria(selected_criteria):
    """Собирает override_criteria для similarity-движка."""
    return {
        'genres': selected_criteria.get('genres', []),
        'keywords': selected_criteria.get('keywords', []),
        'themes': selected_criteria.get('themes', []),
        'production_companies': selected_criteria.get('developers', []),
        'series_id': selected_criteria.get('series_id'),
    }


def game_comparison(request: HttpRequest, pk2: int) -> HttpResponse:
    """Universal comparison: Movie-Movie or criteria-Movie."""
    try:
        movie2 = get_object_or_404(
            Movie.objects.prefetch_related(
                Prefetch('genres', queryset=Genre.objects.only('id', 'name')),
                Prefetch('themes', queryset=Theme.objects.only('id', 'name')),
                Prefetch('production_companies', queryset=Company.objects.only('id', 'name')),
                Prefetch('keywords', queryset=Keyword.objects.only('id', 'name')),
            ),
            pk=pk2
        )

        source_movie_id = (
                request.GET.get('source_movie')
                or request.GET.get('source_game')
        )
        movie1 = None

        if source_movie_id and source_movie_id.strip() and source_movie_id.strip().lower() != 'none':
            try:
                movie1 = Movie.objects.only(
                    'id', 'name',
                ).prefetch_related(
                    'genres', 'themes', 'production_companies', 'keywords',
                ).get(pk=int(source_movie_id))
            except (Movie.DoesNotExist, ValueError):
                movie1 = None

        selected_criteria = convert_params_to_lists(request.GET)

        saved_similarity = request.GET.get('similarity')
        try:
            similarity_score = float(saved_similarity) if saved_similarity else 0
        except (ValueError, TypeError):
            similarity_score = 0

        criteria_genres_objs = (
            Genre.objects.filter(id__in=selected_criteria.get('genres', [])).only('id', 'name')
            if selected_criteria.get('genres') else []
        )
        criteria_keywords_objs = (
            Keyword.objects.filter(id__in=selected_criteria.get('keywords', [])).only('id', 'name')
            if selected_criteria.get('keywords') else []
        )
        criteria_themes_objs = (
            Theme.objects.filter(id__in=selected_criteria.get('themes', [])).only('id', 'name')
            if selected_criteria.get('themes') else []
        )
        criteria_companies_objs = (
            Company.objects.filter(id__in=selected_criteria.get('developers', [])).only('id', 'name')
            if selected_criteria.get('developers') else []
        )

        is_criteria_comparison = movie1 is None
        override_criteria = _build_override_criteria(selected_criteria) if is_criteria_comparison else None

        similarity_data = None
        similarity_engine = moviesimilarity(verbose=False)

        try:
            if is_criteria_comparison:
                similarity_data = similarity_engine.get_similarity_formula(
                    None, movie2, override_criteria=override_criteria,
                )
            else:
                similarity_data = similarity_engine.get_similarity_formula(movie1, movie2)
            similarity_score = similarity_data['total'] if similarity_data else similarity_score
        except Exception as e:
            logger.error(f"Error getting similarity data: {e}")
            similarity_data = {
                'criteria': [],
                'bonus': None,
                'total': similarity_score,
                'total_from_criteria': similarity_score,
                'error': str(e),
            }

        breakdown = None
        try:
            if is_criteria_comparison:
                breakdown = similarity_engine.get_similarity_breakdown(
                    None, movie2, override_criteria=override_criteria,
                )
            else:
                breakdown = similarity_engine.get_similarity_breakdown(movie1, movie2)
        except Exception as e:
            logger.error(f"Error getting breakdown: {e}")

        # ===== SHARED ITEMS =====
        shared_items = {}
        fields_to_compare = ['genres', 'keywords', 'themes', 'production_companies']

        model_map = {
            'genres': Genre,
            'keywords': Keyword,
            'themes': Theme,
            'production_companies': Company,
        }

        if is_criteria_comparison:
            for field in fields_to_compare:
                if field == 'production_companies':
                    criteria_ids = selected_criteria.get('developers', [])
                else:
                    criteria_ids = selected_criteria.get(field, [])
                if not criteria_ids:
                    shared_items[field] = []
                    continue

                if field == 'production_companies':
                    movie_field = movie2.production_companies.all()
                else:
                    movie_field = getattr(movie2, field).all()

                model = model_map[field]
                criteria_objects = model.objects.filter(id__in=criteria_ids)
                shared_items[field] = list(movie_field & criteria_objects)
        else:
            for field in fields_to_compare:
                if field == 'production_companies':
                    field1 = movie1.production_companies.all()
                    field2 = movie2.production_companies.all()
                else:
                    field1 = getattr(movie1, field).all()
                    field2 = getattr(movie2, field).all()
                shared_items[field] = list(field1 & field2)

        # ===== CONTEXT =====
        context = {
            'game1': movie1,
            'game2': movie2,
            'movie1': movie1,
            'movie2': movie2,
            'similarity_score': similarity_score,
            'is_criteria_comparison': is_criteria_comparison,
            'breakdown': breakdown,
            'similarity_data': similarity_data,
            'selected_criteria': selected_criteria,

            'criteria_genres': list(criteria_genres_objs),
            'criteria_keywords': list(criteria_keywords_objs),
            'criteria_themes': list(criteria_themes_objs),
            'criteria_production_companies': list(criteria_companies_objs),

            'criteria_genres_ids': selected_criteria.get('genres', []),
            'criteria_keywords_ids': selected_criteria.get('keywords', []),
            'criteria_themes_ids': selected_criteria.get('themes', []),
            'criteria_production_companies_ids': selected_criteria.get('developers', []),
        }

        if is_criteria_comparison:
            context['criteria_virtual_game'] = CriteriaWrapper(selected_criteria)
            context['criteria_virtual_movie'] = CriteriaWrapper(selected_criteria)
        else:
            context['criteria_virtual_game'] = movie1
            context['criteria_virtual_movie'] = movie1

        for field, items in shared_items.items():
            context[f'shared_{field}'] = items
            context[f'shared_{field}_count'] = len(items)

        context.update({
            'selected_genres': selected_criteria.get('genres', []),
            'selected_keywords': selected_criteria.get('keywords', []),
            'selected_themes': selected_criteria.get('themes', []),
            'selected_production_companies': selected_criteria.get('developers', []),

            'selected_genres_objects': list(criteria_genres_objs),
            'selected_keywords_objects': list(criteria_keywords_objs),
            'selected_themes_objects': list(criteria_themes_objs),
            'selected_production_companies_objects': list(criteria_companies_objs),
        })

        context['average_similarity'] = similarity_score if is_criteria_comparison else None

        return render(request, 'movies/movie_comparison.html', context)

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Error in comparison: {str(e)}")
        logger.error(f"Details: {error_details}")
        return HttpResponseServerError(f"Error in comparison: {str(e)}")
