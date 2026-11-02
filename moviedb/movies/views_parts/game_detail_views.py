# movies/views_parts/game_detail_views.py
"""Movie detail view (Movie-only)."""

from django.shortcuts import render, get_object_or_404
from django.http import HttpRequest, HttpResponse
from django.db.models import Prefetch

from ..models import (
    Movie, Genre, Theme, Company, Keyword, Image,
)

# breadcrumb — опционально: модуль может быть игровым/переименованным.
try:
    from ..breadcrumb import generate_game_breadcrumb  # type: ignore
except Exception:  # noqa: BLE001
    generate_game_breadcrumb = None

try:
    from ..breadcrumb import generate_movie_breadcrumb  # type: ignore
except Exception:  # noqa: BLE001
    generate_movie_breadcrumb = None


def game_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Страница деталей фильма с оптимизированными запросами и похожими фильмами.

    Похожие фильмы берутся из поля recommendation_ids, которое хранит ID
    самых похожих фильмов в порядке убывания схожести.
    """
    movie = get_object_or_404(
        Movie.objects.prefetch_related(
            Prefetch('genres', queryset=Genre.objects.only('id', 'name')),
            Prefetch('themes', queryset=Theme.objects.only('id', 'name')),
            Prefetch('production_companies', queryset=Company.objects.only('id', 'name')),
            Prefetch(
                'images',
                queryset=Image.objects.filter(image_type='backdrop').order_by('-vote_average', 'id')[:20],
                to_attr='backdrops_top',
            ),
            Prefetch(
                'images',
                queryset=Image.objects.filter(image_type='poster').order_by('-vote_average', 'id')[:12],
                to_attr='posters_top',
            ),

        ),
        pk=pk
    )

    seo_text = _generate_game_seo_text(movie)

    similar_movies = []
    recommendation_ids = getattr(movie, 'recommendation_ids', None) or []
    if recommendation_ids:
        similar_movies = list(
            Movie.objects.filter(id__in=recommendation_ids).prefetch_related(
                Prefetch('genres', queryset=Genre.objects.only('id', 'name')),
                Prefetch('themes', queryset=Theme.objects.only('id', 'name')),
                Prefetch('production_companies', queryset=Company.objects.only('id', 'name')),

                Prefetch('images', queryset=Image.objects.filter(image_type='backdrop').order_by('-vote_average', 'id')[:5], to_attr='card_backdrops'),
            ).only(
                'id', 'name', 'rating', 'rating_count',
                'first_release_date', 'cover_url',
            )
        )
        id_to_movie = {m.id: m for m in similar_movies}
        similar_movies = [id_to_movie[mid] for mid in recommendation_ids if mid in id_to_movie]

    first_genre = movie.genres.first()
    genre_name = first_genre.name if first_genre else None

    # platforms в Movie-only проекте нет
    platform_name = None

    breadcrumb_json_ld = None
    breadcrumb_fn = generate_movie_breadcrumb or generate_game_breadcrumb
    if breadcrumb_fn is not None:
        try:
            breadcrumb_json_ld = breadcrumb_fn(
                game_title=movie.name,
                platform_name=platform_name,
                genre_name=genre_name,
                base_url="https://moviespeek.dpdns.org",
            )
        except Exception:  # noqa: BLE001
            breadcrumb_json_ld = None

    return render(request, 'movies/movie_detail.html', {
        'Movie': movie,
        'movie': movie,
        'seo_text': seo_text,
        'similar_movies': similar_movies,
        'current_page': 1,
        'breadcrumb_json_ld': breadcrumb_json_ld,
    })


def _generate_game_seo_text(movie: Movie) -> str:
    """
    Генерирует краткий SEO-текст для страницы фильма (максимум 155 символов).
    """
    parts = []

    parts.append(movie.name)
    parts.append("is a movie")

    genres = list(movie.genres.all())
    if genres:
        genre_names = [g.name for g in genres[:2]]
        if len(genre_names) == 1:
            parts.append(f"in the {genre_names[0]} genre")
        else:
            parts.append(f"in {genre_names[0]} and {genre_names[1]} genres")

    if movie.first_release_date:
        parts.append(f"from {movie.first_release_date.year}")

    if movie.rating:
        parts.append(f"rated {round(movie.rating, 1)}/100")

    companies = list(movie.production_companies.all())
    if companies:
        parts.append(f"by {companies[0].name}")

    parts.append("Find similar movies in our database")

    full_text = " ".join(parts)

    if len(full_text) > 155:
        full_text = full_text[:152] + "..."

    return full_text






