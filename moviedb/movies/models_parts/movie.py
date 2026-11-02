# movies/models_parts/movie.py
"""Main Movie model for TMDB."""

from django.db import models
from django.utils import timezone
from django.urls import reverse
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex

from .managers import MovieManager


class Movie(models.Model):
    """Movie model based on TMDB API."""

    MEDIA_TYPE_CHOICES = (
        ('movie', 'Movie'),
        ('tv', 'TV Show'),
    )

    # ===== TMDB CORE =====
    tmdb_id = models.IntegerField(unique=True, db_index=True)
    imdb_id = models.CharField(max_length=20, blank=True, null=True, db_index=True)
    name = models.CharField(max_length=255, db_index=True)
    original_title = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    summary = models.TextField(blank=True, null=True)
    tagline = models.CharField(max_length=500, blank=True, null=True)
    homepage = models.URLField(max_length=500, blank=True, null=True)
    original_language = models.CharField(max_length=10, blank=True, null=True, db_index=True)
    status = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    adult = models.BooleanField(default=False, db_index=True)

    # ===== MEDIA TYPE / TV FIELDS =====
    media_type = models.CharField(
        max_length=10,
        choices=MEDIA_TYPE_CHOICES,
        default='movie',
        db_index=True,
    )
    number_of_seasons = models.IntegerField(null=True, blank=True)
    number_of_episodes = models.IntegerField(null=True, blank=True)
    episode_run_time = models.IntegerField(null=True, blank=True)

    # ===== DATES / NUMBERS =====
    first_release_date = models.DateTimeField(null=True, blank=True, db_index=True)
    runtime = models.IntegerField(null=True, blank=True, db_index=True)
    budget = models.BigIntegerField(null=True, blank=True)
    revenue = models.BigIntegerField(null=True, blank=True)
    popularity = models.FloatField(null=True, blank=True, db_index=True)
    rating = models.FloatField(blank=True, null=True, db_index=True)
    rating_count = models.IntegerField(default=0, db_index=True)

    # ===== MEDIA =====
    cover_url = models.URLField(blank=True, null=True, max_length=500)
    backdrop_url = models.URLField(blank=True, null=True, max_length=500)
    poster_path = models.CharField(max_length=255, blank=True, null=True)
    backdrop_path = models.CharField(max_length=255, blank=True, null=True)

    # ===== RELATIONS =====
    collection = models.ForeignKey(
        'Collection', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='movies', db_index=True
    )
    series = models.ForeignKey(
        'Series', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='movies', db_index=True
    )
    genres = models.ManyToManyField('Genre', blank=True, related_name='movies')
    keywords = models.ManyToManyField('Keyword', blank=True, related_name='movies')
    themes = models.ManyToManyField('Theme', blank=True, related_name='movies')
    production_companies = models.ManyToManyField(
        'Company', blank=True, related_name='movies'
    )

    # ===== MATERIALIZED VECTORS =====
    genre_ids = ArrayField(models.IntegerField(), default=list, blank=True, db_index=True)
    keyword_ids = ArrayField(models.IntegerField(), default=list, blank=True, db_index=True)
    recommendation_ids = ArrayField(models.IntegerField(), default=list, blank=True, db_index=True)

    # ===== META =====
    date_added = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    objects = MovieManager()

    class Meta:
        ordering = ['-rating_count']
        indexes = [
            models.Index(fields=['-rating_count']),
            models.Index(fields=['-rating']),
            models.Index(fields=['name']),
            models.Index(fields=['-first_release_date']),
            models.Index(fields=['tmdb_id']),
            models.Index(fields=['imdb_id']),
            models.Index(fields=['popularity']),
            models.Index(fields=['status']),
            models.Index(fields=['original_language']),
            models.Index(fields=['-date_added']),
            models.Index(fields=['rating_count', 'rating']),
            models.Index(fields=['media_type']),
            GinIndex(fields=['genre_ids'], name='movie_genre_ids_gin'),
            GinIndex(fields=['keyword_ids'], name='movie_keyword_ids_gin'),
            GinIndex(fields=['recommendation_ids'], name='movie_recommendation_ids_gin'),
        ]

    def save(self, *args, **kwargs):
        if self.first_release_date and timezone.is_naive(self.first_release_date):
            self.first_release_date = timezone.make_aware(
                self.first_release_date, timezone.get_current_timezone()
            )
        super().save(*args, **kwargs)
        self.update_materialized_vectors()

    def update_materialized_vectors(self, force: bool = False) -> None:
        if getattr(self, '_skip_vector_update', False):
            return
        new_genre_ids = list(self.genres.values_list('tmdb_id', flat=True))
        new_keyword_ids = list(self.keywords.values_list('tmdb_id', flat=True))
        needs_update = force or any([
            set(new_genre_ids) != set(self.genre_ids or []),
            set(new_keyword_ids) != set(self.keyword_ids or []),
        ])
        if needs_update:
            self.genre_ids = new_genre_ids
            self.keyword_ids = new_keyword_ids
            Movie.objects.filter(id=self.id).update(
                genre_ids=new_genre_ids, keyword_ids=new_keyword_ids,
            )

    @property
    def get_full_title(self) -> str:
        return self.original_title or self.name

    def get_absolute_url(self):
        return reverse('game_detail', kwargs={'pk': self.id})

    def __str__(self) -> str:
        year = self.first_release_date.year if self.first_release_date else '?'
        return f"{self.name} ({year})"
