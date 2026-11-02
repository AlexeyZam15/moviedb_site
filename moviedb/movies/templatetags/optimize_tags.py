# movies/templatetags/optimize_tags.py
from django import template

register = template.Library()


@register.filter
def optimize_queryset(queryset, model_name=None):
    if not hasattr(queryset, 'only'):
        return queryset

    if model_name in ('genres', 'themes', 'keywords'):
        return queryset.only('id', 'name')

    return queryset
