# movies/models_parts/theme.py
"""Theme model (TMDB)."""

from django.db import models


class Theme(models.Model):
    """Theme from TMDB (flat, no categories)."""

    tmdb_id = models.IntegerField(unique=True, null=True, blank=True, db_index=True)
    name = models.CharField(max_length=255, db_index=True)
    slug = models.SlugField(max_length=255, blank=True, null=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Theme'
        verbose_name_plural = 'Themes'
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