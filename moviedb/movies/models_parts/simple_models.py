"""Simple models for TMDB."""

from django.db import models


class Genre(models.Model):
    """Genre model (TMDB)."""

    tmdb_id = models.IntegerField(unique=True, db_index=True)
    name = models.CharField(max_length=100, db_index=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['name']),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def movies_count(self) -> int:
        return self.movies.count()