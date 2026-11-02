# movies/models.py
"""TMDB-based models."""

from .models_parts import (
    MovieManager,
    Movie,
    Company,
    Collection,
    Series,
    Keyword,
    Genre,
    Theme,
    MovieRecommendation,
    MovieCountsCache,
    Screenshot,
    Image,
    Video,
    MovieCardCache,
)

__all__ = [
    'MovieManager',
    'Movie',
    'Company',
    'Collection',
    'Series',
    'Keyword',
    'Genre',
    'Theme',
    'MovieRecommendation',
    'MovieCountsCache',
    'Screenshot',
    'Image',
    'Video',
    'MovieCardCache',
]