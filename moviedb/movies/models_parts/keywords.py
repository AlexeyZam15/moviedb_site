"""Keyword model (TMDB)."""

from django.db import models


class Keyword(models.Model):
    """Keyword from TMDB (flat, no categories)."""

    tmdb_id = models.IntegerField(unique=True, db_index=True)
    name = models.CharField(max_length=100, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
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