# movies/views_parts/other_views.py
"""Other views (home, keyword category, feedback, admin auto-login) — Movie-only."""

import time
import json
import logging
from datetime import timedelta
from typing import Dict, List

from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.db.models import Count, Prefetch
from django.utils import timezone
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.conf import settings
from django.contrib import messages
from django.urls import reverse
from django.contrib.admin.views.decorators import staff_member_required
from django.core.mail import send_mail
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from ..models import (
    Movie, Genre, Keyword,
    Theme, Company, MovieCardCache, Image,
)
from ..utils.movie_card_utils import MovieCardCreator
from .base_views import cache_get_or_set, get_cache_key, CACHE_TIMES

logger = logging.getLogger(__name__)


@staff_member_required
def remove_theme_from_game(request, game_id, theme_id):
    """Удаляет тему из фильма и возвращает обратно в админку."""
    movie = get_object_or_404(Movie, id=game_id)
    theme = get_object_or_404(Theme, id=theme_id)

    movie.themes.remove(theme)

    messages.success(
        request,
        f'Тема "{theme.name}" успешно удалена из фильма "{movie.name}"'
    )

    # URL админки мог остаться от старой модели Game — пробуем оба варианта.
    for url_name in ('admin:movies_movie_changelist', 'admin:movies_game_changelist'):
        try:
            return redirect(reverse(url_name))
        except Exception:
            continue
    return redirect(reverse('admin:index'))


def home(request: HttpRequest) -> HttpResponse:
    """Optimized home page with cached Movie cards."""
    context = _get_home_context()

    response = render(request, 'movies/home.html', context)

    if 'query_count' in context:
        response['X-DB-Queries'] = str(context['query_count'])
    if 'execution_time' in context:
        response['X-Response-Time'] = f"{context['execution_time']:.3f}s"

    return response


def _get_home_context() -> Dict:
    """Get context for home page with cached Movie cards and SEO data (Movie-only)."""
    from django.db import connection

    total_start = time.time()

    try:
        two_years_ago = timezone.now() - timedelta(days=730)

        popular_ids = list(Movie.objects.filter(
            rating_count__gt=10,
            rating__gte=3.0
        ).order_by('-rating_count', '-rating')[:20].values_list('id', flat=True))

        recent_ids = list(Movie.objects.filter(
            first_release_date__gte=two_years_ago,
            first_release_date__lte=timezone.now()
        ).order_by('-first_release_date')[:20].values_list('id', flat=True))

        added_ids = list(
            Movie.objects.order_by('-date_added')[:20].values_list('id', flat=True)
        )

        all_ids = list(set(popular_ids + recent_ids + added_ids))

        movies_with_prefetch = list(Movie.objects.filter(
            id__in=all_ids
        ).prefetch_related(
            'genres', 'themes', 'production_companies',
            Prefetch('images', queryset=Image.objects.filter(image_type='backdrop').order_by('-vote_average', 'id')[:5], to_attr='card_backdrops'),
        ).only(
            'id', 'name', 'rating', 'rating_count',
            'first_release_date', 'cover_url',
        ))

        movies_dict = {movie.id: movie for movie in movies_with_prefetch}

        cards = MovieCardCache.objects.filter(
            movie_id__in=all_ids,
            is_active=True
        )
        cards_dict = {card.movie_id: card for card in cards}

        missing_ids = [gid for gid in all_ids if gid not in cards_dict]

        if missing_ids:
            try:
                MovieCardCreator.create_cards_for_movies(
                    movie_ids=missing_ids,
                    show_similarity=False,
                    batch_size=100,
                    force=False,
                )
            except Exception as e:
                logger.warning(f"Home: card creation failed for {len(missing_ids)} movies: {e}")

            new_cards = MovieCardCache.objects.filter(
                movie_id__in=missing_ids,
                is_active=True
            )
            for card in new_cards:
                cards_dict[card.movie_id] = card

        def _collect_cards(ids):
            result = []
            for gid in ids:
                if gid in cards_dict:
                    result.append(cards_dict[gid])
                elif gid in movies_dict:
                    movie = movies_dict[gid]

                    class SimpleCard:
                        def __init__(self, m):
                            self.rendered_card = f'<div>Movie ID: {m.id}</div>'

                    result.append(SimpleCard(movie))
            return result

        popular_cards = _collect_cards(popular_ids)
        recent_release_cards = _collect_cards(recent_ids)
        recently_added_cards = _collect_cards(added_ids)

        # Movie-only: поля cached_usage_count нет. Просто первые 20 ключевых слов по имени.
        popular_keywords = list(Keyword.objects.only(
            'id', 'name'
        ).order_by('name')[:20])

        popular_genres = list(Genre.objects.annotate(
            total_movies=Count('movies')
        ).filter(
            total_movies__gt=0
        ).order_by('-total_movies', 'name').only('id', 'name')[:20])

        total_time = time.time() - total_start

        context = {
            'popular_cards': popular_cards,
            'recent_release_cards': recent_release_cards,
            'recently_added_cards': recently_added_cards,
            'popular_keywords': popular_keywords,
            'popular_genres': popular_genres,
            'popular_platforms': [],
            'execution_time': round(total_time, 3),
            'query_count': len(connection.queries),
            'cached': len(missing_ids) == 0,
            'show_similarity': False,
            'source_game': None,
            'source_movie': None,
            'selected_genres': [],
            'selected_keywords': [],
            'selected_themes': [],
            'selected_developers': [],
        }

        return context

    except Exception as e:
        logger.error(f"Home page error: {str(e)}", exc_info=True)

        return {
            'popular_cards': [],
            'recent_release_cards': [],
            'recently_added_cards': [],
            'popular_keywords': [],
            'popular_genres': [],
            'popular_platforms': [],
            'show_similarity': False,
            'source_game': None,
            'source_movie': None,
            'selected_genres': [],
            'selected_keywords': [],
            'selected_themes': [],
            'selected_developers': [],
            'cached': False,
        }


def keyword_category_view(request: HttpRequest, category_id: int) -> HttpResponse:
    """DEPRECATED: KeywordCategory удалена из проекта (Movie-only).

    Функция сохранена как заглушка, потому что импортируется в movies/views.py.
    В urls.py маршрут отсутствует. Перенаправляем на список фильмов.
    """
    logger.warning(
        "keyword_category_view called, but KeywordCategory model no longer exists "
        "(category_id=%s). Redirecting to game_list.", category_id,
    )
    return redirect('game_list')


def game_search(request: HttpRequest) -> HttpResponse:
    """Search movies by name - redirects to movie_list with search parameter."""
    search_query = request.GET.get('q', '').strip()
    start_time = time.time()

    if not search_query:
        execution_time = (time.time() - start_time) * 1000
        logger.info(f"SEARCH: empty query - redirect to game_list - {execution_time:.2f}ms")
        return redirect('game_list')

    base_url = reverse('game_list')
    params = {
        'search_k': search_query,
        'find_similar': '0',
        'page': '1',
    }
    from urllib.parse import urlencode
    redirect_url = f"{base_url}?{urlencode(params)}"

    execution_time = (time.time() - start_time) * 1000
    logger.info(f"SEARCH: '{search_query}' - redirect to {redirect_url} - {execution_time:.2f}ms")

    return redirect(redirect_url)


@csrf_exempt
@require_http_methods(["POST"])
def send_feedback(request: HttpRequest) -> JsonResponse:
    """Send feedback email to moviespeek@mail.ru with optional user email for reply."""
    try:
        data = json.loads(request.body)
        message_text = data.get('message', '').strip()
        user_email = data.get('email', '').strip()

        if not message_text:
            return JsonResponse(
                {'status': 'error', 'message': 'Please enter your feedback'},
                status=400,
            )

        if len(message_text) < 5:
            return JsonResponse(
                {'status': 'error', 'message': 'Message too short (min 5 chars)'},
                status=400,
            )

        if user_email:
            from django.core.validators import validate_email
            from django.core.exceptions import ValidationError
            try:
                validate_email(user_email)
            except ValidationError:
                return JsonResponse(
                    {'status': 'error', 'message': 'Please enter a valid email address'},
                    status=400,
                )

        subject = "moviesPeek Feedback"

        body = f"Message: {message_text}\n\n"
        if user_email:
            body += f"From Email: {user_email}\n"
        else:
            body += "From Email: Not provided (anonymous feedback)\n"
        body += f"From IP: {request.META.get('REMOTE_ADDR', 'Unknown')}\n"
        body += f"User Agent: {request.META.get('HTTP_USER_AGENT', 'Unknown')}"

        logger.info("Attempting to send feedback email to moviespeek@mail.ru")
        logger.info(f"EMAIL_HOST_USER: {settings.EMAIL_HOST_USER}")
        logger.info(f"EMAIL_HOST_PASSWORD set: {bool(settings.EMAIL_HOST_PASSWORD)}")

        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=['moviespeek@mail.ru'],
            fail_silently=False,
        )

        logger.info("Feedback email sent successfully")
        return JsonResponse({'status': 'success', 'message': 'Feedback sent successfully!'})

    except Exception as e:
        logger.error(f"Feedback error: {str(e)}", exc_info=True)
        return JsonResponse(
            {'status': 'error', 'message': f'Failed to send feedback: {str(e)}'},
            status=500,
        )


def auto_login_admin(request: HttpRequest) -> JsonResponse:
    """Автоматическая авторизация в админке (только DEBUG)."""
    if not settings.DEBUG:
        return JsonResponse(
            {'status': 'error', 'message': 'Auto login only available in DEBUG mode'},
            status=403,
        )

    if request.GET.get('test'):
        return JsonResponse({'status': 'test', 'message': 'Test endpoint working'})

    try:
        username = 'admin'
        password = 'admin'

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                'email': 'admin@example.com',
                'is_staff': True,
                'is_superuser': True,
                'is_active': True,
            },
        )

        if created:
            user.set_password(password)
            user.save()
        elif not user.check_password(password):
            user.set_password(password)
            user.save()

        user.backend = 'django.contrib.auth.backends.ModelBackend'
        login(request, user)

        return JsonResponse({
            'status': 'success',
            'message': f'Successfully logged in as {username}',
            'admin_url': '/admin/',
            'username': username,
            'created': created,
        })

    except Exception as e:
        logger.error(f"Error in auto_login_admin: {e}", exc_info=True)
        return JsonResponse(
            {'status': 'error', 'message': f'Error: {str(e)}'},
            status=500,
        )

