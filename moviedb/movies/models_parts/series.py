"""Collection model (TMDB belongs_to_collection)."""

from django.db import models
from typing import Optional


class Collection(models.Model):
    """Collection from TMDB."""

    tmdb_id = models.IntegerField(unique=True, db_index=True)
    name = models.CharField(max_length=255, db_index=True)
    overview = models.TextField(blank=True, null=True)
    poster_path = models.CharField(max_length=255, blank=True, null=True)
    backdrop_path = models.CharField(max_length=255, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Collection'
        verbose_name_plural = 'Collections'
        ordering = ['name']
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['tmdb_id']),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def movies_count(self) -> int:
        return self.movies.count()

    @property
    def first_movie(self) -> Optional['Movie']:
        return self.movies.order_by('first_release_date').first()

    @property
    def latest_movie(self) -> Optional['Movie']:
        return self.movies.order_by('-first_release_date').first()