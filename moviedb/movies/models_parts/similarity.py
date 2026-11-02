"""Similarity / recommendation models for TMDB."""

from django.db import models
from typing import List, Tuple


class MovieRecommendation(models.Model):
    """TMDB recommendation: source movie -> target movie with order."""

    source_movie = models.ForeignKey(
        'Movie', on_delete=models.CASCADE,
        related_name='recommendations_as_source', db_index=True
    )
    target_movie = models.ForeignKey(
        'Movie', on_delete=models.CASCADE,
        related_name='recommendations_as_target', db_index=True
    )
    order = models.PositiveIntegerField(default=0, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        unique_together = ['source_movie', 'target_movie']
        indexes = [
            models.Index(fields=['source_movie', 'order']),
            models.Index(fields=['target_movie']),
        ]
        verbose_name = 'Movie recommendation'
        verbose_name_plural = 'Movie recommendations'

    def __str__(self) -> str:
        return f"{self.source_movie.name} -> {self.target_movie.name} (#{self.order})"

    @classmethod
    def get_for_movie(cls, movie_id: int, limit: int = 20) -> List[Tuple['Movie', int]]:
        return list(
            cls.objects.filter(source_movie_id=movie_id)
            .select_related('target_movie')
            .order_by('order')[:limit]
            .values_list('target_movie', 'order')
        )


class MovieCountsCache(models.Model):
    """Cached counts for a movie (genres, keywords)."""

    movie = models.OneToOneField(
        'Movie', on_delete=models.CASCADE,
        related_name='counts_cache', db_index=True
    )
    genres_count = models.IntegerField(default=0)
    keywords_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=['updated_at'])]

    def __str__(self) -> str:
        return f"Counts for {self.movie.name}"

    def update_counts(self) -> None:
        self.genres_count = self.movie.genres.count()
        self.keywords_count = self.movie.keywords.count()
        self.save()