# movies/utils/movie_card_utils.py
"""
Utility functions for Movie card creation and management (Movie-only).
"""

from django.db import transaction
from django.utils import timezone
from django.template.loader import render_to_string
from django.db.models import Prefetch
from typing import List, Dict, Any, Optional, Tuple
import logging

from movies.models import (
    Movie,
    MovieCardCache,
    Genre,
    Keyword,
    Theme,
    Screenshot,
    Image,
)

logger = logging.getLogger(__name__)


class MovieCardCreator:
    """Utility class for creating and managing Movie cards."""

    @classmethod
    def create_card_for_movie(
            cls,
            movie: Movie,
            show_similarity: bool = False,
            similarity_percent: float = None,
            card_size: str = 'normal',
            force: bool = False
    ) -> Tuple[Optional[MovieCardCache], bool]:
        existing_card = MovieCardCache.get_card_for_game(movie.id)

        if existing_card and not force:
            return existing_card, False

        movie_with_data = cls._load_movie_with_data(movie.id)

        if not movie_with_data:
            return None, False

        rendered_card = cls._render_card_html(
            movie_with_data, show_similarity, similarity_percent
        )

        related_data = cls._extract_related_data(movie_with_data)

        try:
            with transaction.atomic():
                card, created = MovieCardCache.get_or_create_card(
                    Movie=movie_with_data,
                    rendered_card=rendered_card,
                    **related_data
                )

            logger.info(
                f"{'Created' if created else 'Updated'} card cache "
                f"for Movie {movie.id} ({movie.name})"
            )

            return card, created

        except Exception as e:
            logger.error(
                f"Error creating/updating card for Movie {movie.id}: {str(e)}",
                exc_info=True,
            )
            return None, False

    @classmethod
    def create_cards_for_movies(
            cls,
            movie_ids: List[int],
            show_similarity: bool = False,
            batch_size: int = 100,
            force: bool = False
    ) -> Dict[str, int]:
        movies_dict = cls._load_movies_with_data(movie_ids)

        batch_cards = []
        for movie_id in movie_ids:
            movie = movies_dict.get(movie_id)
            if not movie:
                continue

            rendered_card = cls._render_card_html(movie, show_similarity)
            related_data = cls._extract_related_data(movie)

            batch_cards.append((
                movie,
                rendered_card,
                related_data
            ))

        if batch_cards:
            try:
                stats = MovieCardCache.bulk_create_or_update_cards(
                    batch_cards, batch_size=batch_size
                )

                logger.info(
                    f"Bulk processed {len(batch_cards)} cards: "
                    f"created={stats['created']}, "
                    f"updated={stats['updated']}, "
                    f"skipped={stats['skipped']}, "
                    f"errors={stats['errors']}"
                )

                return {
                    'total': len(batch_cards),
                    'created': stats['created'],
                    'updated': stats['updated'],
                    'skipped': stats['skipped'],
                    'errors': stats['errors']
                }

            except Exception as e:
                logger.error(f"Error bulk processing cards: {str(e)}", exc_info=True)
                return {
                    'total': len(batch_cards),
                    'created': 0,
                    'updated': 0,
                    'skipped': 0,
                    'errors': len(batch_cards)
                }

        return {
            'total': 0,
            'created': 0,
            'updated': 0,
            'skipped': 0,
            'errors': 0
        }

    @classmethod
    def _load_movie_with_data(cls, movie_id: int) -> Optional[Movie]:
        try:
            genre_prefetch = Prefetch('genres', queryset=Genre.objects.only('id', 'name'))
            theme_prefetch = Prefetch('themes', queryset=Theme.objects.only('id', 'name'))
            keyword_prefetch = Prefetch('keywords', queryset=Keyword.objects.only('id', 'name'))
            screenshot_prefetch = Prefetch(
                'screenshots',
                queryset=Screenshot.objects.order_by('id'),
            )
            backdrop_prefetch = Prefetch(
                'images',
                queryset=Image.objects.filter(image_type='backdrop').order_by('-vote_average', 'id')[:5],
                to_attr='card_backdrops',
            )

            movie = Movie.objects.filter(id=movie_id).prefetch_related(
                genre_prefetch,
                theme_prefetch,
                keyword_prefetch,
                screenshot_prefetch,
                backdrop_prefetch,
            ).only(
                'id', 'name', 'rating', 'rating_count',
                'first_release_date', 'cover_url',
            ).first()

            return movie
        except Exception as e:
            logger.error(f"Error loading Movie {movie_id} with data: {str(e)}", exc_info=True)
            return None

    @classmethod
    def _load_movies_with_data(cls, movie_ids: List[int]) -> Dict[int, Movie]:
        try:
            genre_prefetch = Prefetch('genres', queryset=Genre.objects.only('id', 'name'))
            theme_prefetch = Prefetch('themes', queryset=Theme.objects.only('id', 'name'))
            keyword_prefetch = Prefetch('keywords', queryset=Keyword.objects.only('id', 'name'))
            screenshot_prefetch = Prefetch(
                'screenshots',
                queryset=Screenshot.objects.order_by('id'),
            )
            backdrop_prefetch = Prefetch(
                'images',
                queryset=Image.objects.filter(image_type='backdrop').order_by('-vote_average', 'id')[:5],
                to_attr='card_backdrops',
            )

            movies = Movie.objects.filter(id__in=movie_ids).prefetch_related(
                genre_prefetch,
                theme_prefetch,
                keyword_prefetch,
                screenshot_prefetch,
                backdrop_prefetch,
            ).only(
                'id', 'name', 'rating', 'rating_count',
                'first_release_date', 'cover_url',
            )

            return {movie.id: movie for movie in movies}
        except Exception as e:
            logger.error(f"Error loading movies with data: {str(e)}", exc_info=True)
            return {}

    @staticmethod
    def _render_card_html(
            movie: Movie,
            show_similarity: bool = False,
            similarity_percent: float = None
    ) -> str:
        context = {
            'Movie': movie,
            'movie': movie,
            'show_similarity': show_similarity,
            'current_page': 1,
            'game_index': 0,
            'game_index_offset': 0,
            'forloop': {'counter0': 0, 'counter': 1},
        }

        if show_similarity and similarity_percent is not None:
            if not hasattr(movie, 'similarity'):
                movie.similarity = similarity_percent

        return render_to_string('movies/partials/_movie_card.html', context)

    @staticmethod
    def _extract_related_data(movie: Movie) -> Dict[str, List[Dict]]:
        all_screenshots = list(movie.screenshots.all())
        limited_screenshots = all_screenshots[:8]

        return {
            'genres': [
                {'id': genre.id, 'name': genre.name}
                for genre in movie.genres.all()
            ],
            'keywords': [
                {
                    'id': keyword.id,
                    'name': keyword.name,
                    'category_id': keyword.category.id if getattr(keyword, 'category', None) else None,
                    'category_name': keyword.category.name if getattr(keyword, 'category', None) else None
                }
                for keyword in movie.keywords.all()
            ],
            'themes': [
                {'id': theme.id, 'name': theme.name}
                for theme in movie.themes.all()
            ],
            'screenshots': [
                {'id': screenshot.id, 'url': screenshot.url}
                for screenshot in limited_screenshots
            ],
        }

