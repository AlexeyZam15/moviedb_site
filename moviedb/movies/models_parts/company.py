"""Company model (TMDB production company)."""

from django.db import models


class Company(models.Model):
    """Production company from TMDB."""

    tmdb_id = models.IntegerField(unique=True, db_index=True)
    name = models.CharField(max_length=255, db_index=True)
    logo_path = models.CharField(max_length=255, blank=True, null=True)
    origin_country = models.CharField(max_length=10, blank=True, null=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Company'
        verbose_name_plural = 'Companies'
        ordering = ['name']
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['tmdb_id']),
            models.Index(fields=['origin_country']),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def movies_count(self) -> int:
        return self.movies.count()