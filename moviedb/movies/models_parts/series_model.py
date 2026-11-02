# movies/models_parts/series_model.py
"""Series model (franchise, separate from Collection)."""

from django.db import models


class Series(models.Model):
    """Series / franchise grouping for movies."""

    tmdb_id = models.IntegerField(unique=True, null=True, blank=True, db_index=True)
    name = models.CharField(max_length=255, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Series'
        verbose_name_plural = 'Series'
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