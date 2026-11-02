# movies/templatetags/movie_tags.py
"""
Templatetags for Movie (TMDB-only) project.
"""
from django import template
from urllib.parse import urlencode

register = template.Library()


def _int_list(values):
    return [str(v) for v in values if v is not None]


@register.simple_tag
def get_find_similar_url(Movie):
    if Movie is None:
        return "/movies/"

    params = {}
    if getattr(Movie, 'pk', None):
        params['source_movie'] = Movie.pk
        params['find_similar'] = 1

    try:
        genres = Movie.genres.all()
        if genres:
            params['g'] = ','.join(_int_list(g.id for g in genres))
    except Exception:
        pass

    try:
        keywords = Movie.keywords.all()
        if keywords:
            params['k'] = ','.join(_int_list(k.id for k in keywords))
    except Exception:
        pass

    try:
        themes = Movie.themes.all()
        if themes:
            params['t'] = ','.join(_int_list(t.id for t in themes))
    except Exception:
        pass

    try:
        companies = Movie.production_companies.all()
        if companies:
            params['pc'] = ','.join(_int_list(c.id for c in companies))
    except Exception:
        pass

    qs = urlencode(params)
    return f"/movies/?{qs}" if qs else "/movies/"


@register.simple_tag
def get_find_similar_url_from_criteria(
        criteria_genres=None,
        criteria_keywords=None,
        criteria_themes=None,
        criteria_production_companies=None,
        selected_genres=None,
        selected_keywords=None,
        selected_themes=None,
        selected_production_companies=None,
):
    params = {'find_similar': 1}

    def add(key, values):
        if values:
            params[key] = ','.join(_int_list(values))

    add('g', criteria_genres or selected_genres)
    add('k', criteria_keywords or selected_keywords)
    add('t', criteria_themes or selected_themes)
    add('pc', criteria_production_companies or selected_production_companies)

    qs = urlencode(params)
    return f"/movies/?{qs}"
