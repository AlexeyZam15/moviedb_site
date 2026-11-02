# movies/templatetags/movie_card_tags.py
from django import template

register = template.Library()


@register.inclusion_tag('movies/partials/_movie_card.html', takes_context=False)
def render_movie_card(
        Movie,
        show_similarity: bool = False,
        similarity_percent: float = None,
        selected_genres: list = None,
        selected_keywords: list = None,
        selected_themes: list = None,
        selected_production_companies: list = None,
):
    """
    Render Movie card with optional similarity and criteria highlight.
    В Movie-only проекте нет game_modes/perspectives/platforms.
    """
    if show_similarity and similarity_percent is not None:
        try:
            Movie.similarity = similarity_percent
        except Exception:
            pass

    return {
        'Movie': Movie,
        'show_similarity': show_similarity,
        'similarity_percent': similarity_percent,
        'selected_genres': selected_genres or [],
        'selected_keywords': selected_keywords or [],
        'selected_themes': selected_themes or [],
        'selected_production_companies': selected_production_companies or [],
    }
