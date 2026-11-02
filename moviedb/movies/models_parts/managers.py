"""Managers for Movie model."""

from django.db import models
from django.utils import timezone
from django.core.cache import cache
from django.db.models import Prefetch
from typing import List, Dict, Optional

from .simple_models import Genre
from .keywords import Keyword


class MovieManager(models.Manager):
    """Custom manager for Movie model."""

    def movies_only(self):
        """Queryset only regular movies (media_type='movie')."""
        return self.filter(media_type='movie')

    def tv_only(self):
        """Queryset only TV shows (media_type='tv')."""
        return self.filter(media_type='tv')

    def get_home_page_data(self, limit: int = 12):
        """Optimized query for home page data."""
        genre_prefetch = Prefetch('genres', queryset=Genre.objects.only('id', 'name'))

        popular_ids = cache.get('home_popular_movie_ids')
        if not popular_ids:
            popular_ids = list(self.filter(
                rating_count__gt=20, rating__gte=3.0
            ).order_by('-rating_count', '-rating').values_list('id', flat=True)[:limit])
            cache.set('home_popular_movie_ids', popular_ids, 3600)

        recent_ids = cache.get('home_recent_movie_ids')
        if not recent_ids:
            two_years_ago = timezone.now() - timezone.timedelta(days=730)
            recent_ids = list(self.filter(
                first_release_date__gte=two_years_ago
            ).order_by('-first_release_date').values_list('id', flat=True)[:limit])
            cache.set('home_recent_movie_ids', recent_ids, 1800)

        all_ids = set(popular_ids + recent_ids)
        movies_dict = {}
        if all_ids:
            movies = self.filter(id__in=all_ids).prefetch_related(genre_prefetch).only(
                'id', 'name', 'rating', 'rating_count',
                'first_release_date', 'cover_url'
            )
            for movie in movies:
                movies_dict[movie.id] = movie

        return {
            'popular_movies': [movies_dict[i] for i in popular_ids if i in movies_dict],
            'recent_movies': [movies_dict[i] for i in recent_ids if i in movies_dict],
        }

    def bulk_prefetch_for_list(self, movie_ids: List[int]) -> models.QuerySet:
        return self.filter(id__in=movie_ids).prefetch_related(
            Prefetch('genres', queryset=Genre.objects.only('id', 'name')),
            Prefetch('keywords', queryset=Keyword.objects.only('id', 'name')),
        ).only(
            'id', 'name', 'rating', 'rating_count',
            'first_release_date', 'cover_url'
        )

    def bulk_update_overviews(self, overviews: Dict[int, str], batch_size: int = 1000) -> int:
        """Mass update summaries (overviews) from TMDB."""
        if not overviews:
            return 0
        from django.db import transaction
        from django.db.models import Case, When, Value

        movie_ids = list(overviews.keys())
        updated = 0
        for i in range(0, len(movie_ids), batch_size):
            batch_ids = movie_ids[i:i + batch_size]
            whens = [
                When(id=mid, then=Value(desc))
                for mid in batch_ids
                if (desc := overviews.get(mid)) is not None
            ]
            if not whens:
                continue
            with transaction.atomic():
                updated += self.filter(id__in=batch_ids).update(
                    summary=Case(*whens, default='summary')
                )
        return updated
