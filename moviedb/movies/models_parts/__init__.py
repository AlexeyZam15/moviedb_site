# movies/models_parts/__init__.py
"""TMDB-based models organized in modules."""

from .managers import MovieManager
from .movie import Movie
from .company import Company
from .series import Collection
from .series_model import Series
from .keywords import Keyword
from .simple_models import Genre
from .theme import Theme
from .similarity import MovieRecommendation, MovieCountsCache
from .media import Screenshot, Image, Video
from .movie_card import MovieCardCache

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