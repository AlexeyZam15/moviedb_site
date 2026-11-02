# movies/urls.py

from django.urls import path
from . import views
from .views_parts.movie_list_views import ajax_load_keywords

from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('', views.home, name='home'),
    path('movies/', views.game_list, name='game_list'),
    path('search/', views.search_results, name='search_results'),
    path('movies/<int:pk>/', views.game_detail, name='game_detail'),
    path('movies/compare/<int:pk2>/', views.game_comparison, name='game_comparison'),
    path('ajax/load-movies-page/', views.ajax_load_movies_page, name='ajax_load_movies_page'),
    path('ajax/load-filters/', views.ajax_load_filters, name='ajax_load_filters'),
    path('ajax/load-keywords/', ajax_load_keywords, name='ajax_load_keywords'),
    path('admin-auto-login/', views.auto_login_admin, name='auto_login_admin'),
    path('movies/<int:game_id>/remove-theme/<int:theme_id>/', views.remove_theme_from_game,
         name='remove_theme_from_game'),
    path('send-feedback/', views.send_feedback, name='send_feedback'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)