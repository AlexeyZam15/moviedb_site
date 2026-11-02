# movies/admin.py

from django.contrib import admin
from django.utils import timezone
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django.urls import reverse

from .models import (
    Movie, Company, Collection, Keyword, Genre,
    MovieRecommendation, MovieCountsCache,
    Screenshot, Image, Video, MovieCardCache,
)


# ===== CUSTOM FILTERS =====

class HasOverviewFilter(admin.SimpleListFilter):
    """Фильтр по наличию описания"""
    title = _('Описание')
    parameter_name = 'overview'

    def lookups(self, request, model_admin):
        return (
            ('has', _('✅ Есть описание')),
            ('no', _('❌ Нет описания')),
        )

    def queryset(self, request, queryset):
        if self.value() == 'has':
            return queryset.exclude(summary__isnull=True).exclude(summary='')
        elif self.value() == 'no':
            return queryset.filter(summary__isnull=True) | queryset.filter(summary='')
        return queryset


# ===== MOVIE ADMIN =====

@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = [
        'name_link',
        'tmdb_id',
        'imdb_id',
        'rating',
        'rating_count',
        'first_release_date',
        'date_added',
    ]

    list_filter = [
        'adult',
        'status',
        'original_language',
        'genres',
        'collection',
        'date_added',
        HasOverviewFilter,
    ]

    readonly_fields = ['date_added', 'updated_at', 'poster_path', 'backdrop_path']

    search_fields = ['name', 'original_title', 'imdb_id', 'tmdb_id']

    ordering = ['-date_added']

    filter_horizontal = ['genres', 'keywords', 'production_companies']

    fieldsets = (
        ('TMDB', {
            'fields': (
                'tmdb_id',
                'imdb_id',
                'name',
                'original_title',
                'tagline',
                'summary',
                'homepage',
                'original_language',
                'status',
                'adult',
            )
        }),
        ('Даты и цифры', {
            'fields': (
                'first_release_date',
                'runtime',
                'budget',
                'revenue',
                'popularity',
                'rating',
                'rating_count',
            )
        }),
        ('Медиа', {
            'fields': (
                'cover_url',
                'backdrop_url',
                'poster_path',
                'backdrop_path',
            ),
            'classes': ('collapse',),
        }),
        ('Связи', {
            'fields': (
                'collection',
                'genres',
                'keywords',
                'production_companies',
            )
        }),
        ('Служебное', {
            'fields': ('date_added', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    list_per_page = 50

    def name_link(self, obj):
        url = reverse('admin:movies_movie_change', args=[obj.id])
        return format_html('<a href="{}"><strong>{}</strong></a>', url, obj.name)

    name_link.short_description = "Название"
    name_link.admin_order_field = 'name'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('collection')


# ===== KEYWORD ADMIN =====

@admin.register(Keyword)
class KeywordAdmin(admin.ModelAdmin):
    list_display = ['name', 'tmdb_id', 'movies_count', 'created_at']
    search_fields = ['name']
    ordering = ['name']
    readonly_fields = ['created_at']

    fieldsets = (
        ('Основное', {'fields': ('name', 'tmdb_id')}),
        ('Даты', {'fields': ('created_at',), 'classes': ('collapse',)}),
    )

    def movies_count(self, obj):
        count = obj.movies.count()
        if count == 0:
            return format_html('<span style="color:#999">{}</span>', count)
        if count < 10:
            return format_html('<span style="color:#4caf50">{}</span>', count)
        if count < 50:
            return format_html('<span style="color:#ff9800">{}</span>', count)
        return format_html('<span style="color:#f44336"><strong>{}</strong></span>', count)

    movies_count.short_description = "Фильмов"


# ===== COMPANY ADMIN =====

@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ['name', 'tmdb_id', 'origin_country', 'movies_count']
    search_fields = ['name']
    list_filter = ['origin_country']
    ordering = ['name']

    def movies_count(self, obj):
        return obj.movies.count()

    movies_count.short_description = "Фильмов"


# ===== COLLECTION ADMIN =====

@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ['name', 'tmdb_id', 'movies_count']
    search_fields = ['name']
    ordering = ['name']

    def movies_count(self, obj):
        return obj.movies.count()

    movies_count.short_description = "Фильмов"


# ===== GENRE ADMIN =====

@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ['name', 'tmdb_id', 'movies_count']
    search_fields = ['name']
    ordering = ['name']

    def movies_count(self, obj):
        return obj.movies.count()

    movies_count.short_description = "Фильмов"


# ===== MEDIA ADMIN =====

@admin.register(Screenshot)
class ScreenshotAdmin(admin.ModelAdmin):
    list_display = ['id', 'movie', 'url', 'w', 'h', 'primary']
    list_filter = ['primary']
    search_fields = ['movie__name']
    raw_id_fields = ['movie']


@admin.register(Image)
class ImageAdmin(admin.ModelAdmin):
    list_display = ['id', 'movie', 'image_type', 'file_path', 'width', 'height', 'vote_average']
    list_filter = ['image_type', 'language']
    search_fields = ['movie__name', 'file_path']
    raw_id_fields = ['movie']


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ['id', 'movie', 'video_type', 'name', 'site', 'official', 'published_at']
    list_filter = ['video_type', 'site', 'official']
    search_fields = ['movie__name', 'name', 'key']
    raw_id_fields = ['movie']


# ===== RECOMMENDATIONS ADMIN =====

@admin.register(MovieRecommendation)
class MovieRecommendationAdmin(admin.ModelAdmin):
    list_display = ['source_movie', 'target_movie', 'order', 'updated_at']
    search_fields = ['source_movie__name', 'target_movie__name']
    raw_id_fields = ['source_movie', 'target_movie']
    readonly_fields = ['updated_at']


@admin.register(MovieCountsCache)
class MovieCountsCacheAdmin(admin.ModelAdmin):
    list_display = ['movie', 'genres_count', 'keywords_count', 'updated_at']
    search_fields = ['movie__name']
    raw_id_fields = ['movie']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(MovieCardCache)
class MovieCardCacheAdmin(admin.ModelAdmin):
    list_display = ['movie', 'template_version', 'is_active', 'hit_count', 'last_accessed']
    list_filter = ['is_active', 'template_version']
    search_fields = ['movie__name', 'movie_name']
    raw_id_fields = ['movie']
    readonly_fields = ['created_at', 'updated_at', 'last_accessed']


# ===== ADMIN SITE CONFIGURATION =====

admin.site.site_header = "moviesPeek Site Administration"
admin.site.site_title = "moviesPeek Admin"
admin.site.index_title = "Welcome to moviesPeek Admin"