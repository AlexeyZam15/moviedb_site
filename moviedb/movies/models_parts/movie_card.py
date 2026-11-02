"""Movie card caching model."""

from django.db import models, transaction
from django.utils import timezone
from django.core.cache import cache
from typing import Dict, List, Optional, Tuple
import hashlib
import logging

logger = logging.getLogger(__name__)


class MovieCardCache(models.Model):
    """Model for caching pre-rendered movie cards."""

    CARD_CACHE_VERSION = 'v3'

    movie = models.OneToOneField(
        'Movie', on_delete=models.CASCADE, related_name='card_cache', db_index=True
    )

    rendered_card = models.TextField(verbose_name="Rendered HTML card")
    compressed_card = models.BinaryField(null=True, blank=True)

    movie_name = models.CharField(max_length=255, db_index=True)
    movie_rating = models.FloatField(null=True, blank=True, db_index=True)
    movie_cover_url = models.URLField(max_length=500, blank=True, null=True)

    genres_json = models.JSONField(default=list)
    keywords_json = models.JSONField(default=list)
    screenshots_json = models.JSONField(default=list)

    is_active = models.BooleanField(default=True, db_index=True)
    cache_key = models.CharField(max_length=64, unique=True, db_index=True)
    card_hash = models.CharField(max_length=64, db_index=True)
    template_version = models.CharField(max_length=10, default=CARD_CACHE_VERSION)

    hit_count = models.IntegerField(default=0)
    last_accessed = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Movie card cache"
        verbose_name_plural = "Movie card caches"
        ordering = ['-last_accessed']
        indexes = [
            models.Index(fields=['movie', 'is_active']),
            models.Index(fields=['cache_key', 'is_active']),
            models.Index(fields=['movie_rating', 'is_active']),
            models.Index(fields=['created_at', 'is_active']),
            models.Index(fields=['hit_count', 'is_active']),
            models.Index(fields=['template_version', 'is_active']),
        ]

    def __str__(self) -> str:
        return f"Card cache for {self.movie_name}"

    def save(self, *args, **kwargs) -> None:
        if not self.cache_key:
            self.cache_key = self.generate_cache_key()
        if not self.card_hash:
            self.card_hash = self.generate_card_hash()
        if not self.template_version:
            self.template_version = self.CARD_CACHE_VERSION
        self.updated_at = timezone.now()
        super().save(*args, **kwargs)

    @classmethod
    def get_card_for_movie(cls, movie_id: int, movie=None) -> Optional['MovieCardCache']:
        try:
            card = cls.objects.select_related('movie').get(movie_id=movie_id, is_active=True)
            if card.template_version != cls.CARD_CACHE_VERSION:
                card.is_active = False
                card.save(update_fields=['is_active'])
                return None
            if movie:
                if (card.movie_name != movie.name or
                        card.movie_rating != getattr(movie, 'rating', None) or
                        card.movie_cover_url != getattr(movie, 'cover_url', None)):
                    card.is_active = False
                    card.save(update_fields=['is_active'])
                    return None
            return card
        except cls.DoesNotExist:
            return None

    @classmethod
    def get_card_for_game(cls, movie_id: int, movie=None) -> Optional['MovieCardCache']:
        """Backward-compatible alias for get_card_for_movie."""
        return cls.get_card_for_movie(movie_id, movie=movie)

    @classmethod
    def get_or_create_card(cls, Movie, rendered_card: str, **related_data) -> Tuple['MovieCardCache', bool]:
        """
        Create or update a card for the given Movie.

        related_data keys (from MovieCardCreator._extract_related_data):
          - genres: List[Dict]      -> genres_json
          - keywords: List[Dict]    -> keywords_json
          - screenshots: List[Dict] -> screenshots_json
          - themes: List[Dict]      -> IGNORED (no field in model)
        """
        if Movie is None or not rendered_card:
            raise ValueError("get_or_create_card: Movie and rendered_card are required")

        genres = related_data.get('genres') or []
        keywords = related_data.get('keywords') or []
        screenshots = related_data.get('screenshots') or []

        if related_data.get('themes'):
            logger.debug(
                "MovieCardCache.get_or_create_card: 'themes' is not stored "
                "(no themes_json field in model); ignored for movie_id=%s",
                getattr(Movie, 'id', None),
            )

        defaults = {
            'rendered_card': rendered_card,
            'movie_name': Movie.name,
            'movie_rating': getattr(Movie, 'rating', None),
            'movie_cover_url': getattr(Movie, 'cover_url', None),
            'genres_json': genres,
            'keywords_json': keywords,
            'screenshots_json': screenshots,
            'is_active': True,
            'template_version': cls.CARD_CACHE_VERSION,
        }

        card, created = cls.objects.update_or_create(
            movie=Movie,
            defaults=defaults,
        )
        return card, created

    @classmethod
    def bulk_create_or_update_cards(cls, cards: List[Tuple], batch_size: int = 50) -> Dict[str, int]:
        """
        Bulk create/update cards.

        Input: list of tuples (Movie, rendered_card, related_data).
        Output: dict(created, updated, skipped, errors).

        Uses update_or_create per item, batched in transaction.atomic()
        chunks of `batch_size` to keep transactions short.
        """
        stats = {'created': 0, 'updated': 0, 'skipped': 0, 'errors': 0}

        if not cards:
            return stats

        if not batch_size or batch_size <= 0:
            batch_size = 50

        for start in range(0, len(cards), batch_size):
            chunk = cards[start:start + batch_size]
            try:
                with transaction.atomic():
                    for item in chunk:
                        try:
                            if not item or len(item) < 3:
                                stats['skipped'] += 1
                                continue

                            movie, rendered_card, related_data = item[0], item[1], item[2] or {}

                            if movie is None or not rendered_card:
                                stats['skipped'] += 1
                                continue

                            _, created = cls.get_or_create_card(
                                Movie=movie,
                                rendered_card=rendered_card,
                                **related_data,
                            )
                            if created:
                                stats['created'] += 1
                            else:
                                stats['updated'] += 1
                        except Exception as exc:
                            stats['errors'] += 1
                            logger.error(
                                "bulk_create_or_update_cards: item failed: %s",
                                exc, exc_info=True,
                            )
            except Exception as exc:
                # If the whole chunk transaction failed, count remaining as errors.
                logger.error(
                    "bulk_create_or_update_cards: chunk failed: %s",
                    exc, exc_info=True,
                )
                stats['errors'] += len(chunk)

        return stats

    @classmethod
    def generate_cache_key_for_movie(cls, movie_id: int) -> str:
        return f"movie_card_{movie_id}"

    def generate_cache_key(self) -> str:
        return self.generate_cache_key_for_movie(self.movie_id)

    def generate_card_hash(self) -> str:
        content = (self.rendered_card or "")
        return hashlib.md5(content.encode()).hexdigest()

    @staticmethod
    def _calculate_card_hash(rendered_card: str) -> str:
        return hashlib.md5((rendered_card or "").encode()).hexdigest()

    def increment_hit(self) -> None:
        self.hit_count += 1
        self.last_accessed = timezone.now()
        MovieCardCache.objects.filter(id=self.id).update(
            hit_count=self.hit_count, last_accessed=self.last_accessed
        )

    @classmethod
    def invalidate_movie_cards(cls, movie_id: int) -> int:
        updated = cls.objects.filter(movie_id=movie_id, is_active=True).update(
            is_active=False, updated_at=timezone.now()
        )
        for key in cls.objects.filter(movie_id=movie_id).values_list('cache_key', flat=True):
            cache.delete(key)
        return updated

    @classmethod
    def cleanup_old_cards(cls, days_old: int = 30) -> int:
        cutoff = timezone.now() - timezone.timedelta(days=days_old)
        old = cls.objects.filter(is_active=False, updated_at__lt=cutoff)
        count = old.count()
        old.delete()
        return count

    @classmethod
    def bump_cache_version(cls, new_version: str = None) -> str:
        if new_version:
            cls.CARD_CACHE_VERSION = new_version
        else:
            cur = cls.CARD_CACHE_VERSION
            cls.CARD_CACHE_VERSION = f'v{int(cur[1:]) + 1}' if cur.startswith('v') and cur[1:].isdigit() else 'v3'
        return cls.CARD_CACHE_VERSION
