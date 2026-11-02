# movies/signals.py
"""
Django signals for automatic maintenance of materialized vectors and cached counts.
Ensures Movie.genre_ids, Movie.keyword_ids are always in sync with actual M2M relations.
Also invalidates MovieCardCache when Movie data changes.
"""

from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver
from django.db import transaction
import logging

from .models import Movie, MovieCardCache

logger = logging.getLogger(__name__)


@receiver(m2m_changed, sender=Movie.genres.through)
@receiver(m2m_changed, sender=Movie.keywords.through)
def update_movie_vectors_on_m2m_change(sender, instance, action, reverse, model, pk_set, using, **kwargs):
    """
    Обновляет материализованные векторы (genre_ids, keyword_ids)
    при изменениях ManyToMany связей.
    Инвалидирует кэш карточки.
    """
    if action not in ['post_add', 'post_remove', 'post_clear']:
        return

    if reverse:
        if not pk_set:
            return
        movies = Movie.objects.filter(id__in=pk_set)
        for movie in movies:
            transaction.on_commit(
                lambda m=movie: m.update_materialized_vectors(force=True)
            )
            transaction.on_commit(
                lambda m=movie: invalidate_movie_card_cache(m.id)
            )
    else:
        if not isinstance(instance, Movie):
            return
        transaction.on_commit(
            lambda inst=instance: inst.update_materialized_vectors(force=True)
        )
        transaction.on_commit(
            lambda inst=instance: invalidate_movie_card_cache(inst.id)
        )


@receiver(post_save, sender=Movie)
def invalidate_card_on_movie_save(sender, instance, **kwargs):
    """Инвалидирует кэш карточки при сохранении Movie."""
    transaction.on_commit(
        lambda: invalidate_movie_card_cache(instance.id)
    )


def invalidate_movie_card_cache(movie_id: int) -> None:
    """Помечает кэш карточки как неактивный."""
    try:
        card = MovieCardCache.objects.filter(movie_id=movie_id, is_active=True).first()
        if card:
            card.is_active = False
            card.save(update_fields=['is_active'])
            logger.info(f"Invalidated card cache for Movie {movie_id}")
    except Exception as e:
        logger.error(f"Error invalidating card cache for Movie {movie_id}: {e}")