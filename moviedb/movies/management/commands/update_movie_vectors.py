from django.core.management.base import BaseCommand
from django.db import transaction
from movies.models import Movie
from tqdm import tqdm


class Command(BaseCommand):
    help = 'Обновляет материализованные векторы (genre_ids, keyword_ids, recommendation_ids) для всех фильмов'

    def handle(self, *args, **options):
        self.stdout.write('🔄 ЗАПУСК ОБНОВЛЕНИЯ МАТЕРИАЛИЗОВАННЫХ ВЕКТОРОВ')
        self.stdout.write('=' * 60)

        # Получаем все фильмы
        total_movies = Movie.objects.count()
        self.stdout.write(f'📊 Всего фильмов в базе: {total_movies}')

        if total_movies == 0:
            self.stdout.write(self.style.WARNING('⚠️  Нет фильмов для обновления'))
            return

        # Статистика
        updated_count = 0
        error_count = 0
        genre_updates = 0
        keyword_updates = 0
        recommendation_updates = 0

        # Компактный прогресс-бар
        with tqdm(total=total_movies, desc="Обновление", unit="фильмов",
                  bar_format='{l_bar}{bar:10}{r_bar}{bar:-10b}') as pbar:
            for movie in Movie.objects.all().iterator(chunk_size=100):
                try:
                    # Сохраняем старые значения для статистики
                    old_genre_ids = len(movie.genre_ids) if movie.genre_ids else 0
                    old_keyword_ids = len(movie.keyword_ids) if movie.keyword_ids else 0
                    old_recommendation_ids = len(movie.recommendation_ids) if movie.recommendation_ids else 0

                    # Обновляем векторы (genre_ids + keyword_ids)
                    with transaction.atomic():
                        movie.update_materialized_vectors(force=True)
                        movie.refresh_from_db()

                    updated_count += 1

                    # Считаем изменения
                    new_genre_ids = len(movie.genre_ids) if movie.genre_ids else 0
                    new_keyword_ids = len(movie.keyword_ids) if movie.keyword_ids else 0
                    new_recommendation_ids = len(movie.recommendation_ids) if movie.recommendation_ids else 0

                    if new_genre_ids > old_genre_ids:
                        genre_updates += (new_genre_ids - old_genre_ids)
                    if new_keyword_ids > old_keyword_ids:
                        keyword_updates += (new_keyword_ids - old_keyword_ids)
                    if new_recommendation_ids > old_recommendation_ids:
                        recommendation_updates += (new_recommendation_ids - old_recommendation_ids)

                except Exception as e:
                    error_count += 1
                    self.stdout.write(self.style.ERROR(f'\n❌ Ошибка для фильма {movie.id}: {str(e)}'))

                pbar.update(1)

        # Финальная статистика
        self.stdout.write('\n' + '=' * 60)
        self.stdout.write('📊 ИТОГОВАЯ СТАТИСТИКА')
        self.stdout.write('=' * 60)
        self.stdout.write(f'✅ Успешно обновлено: {updated_count}/{total_movies}')
        self.stdout.write(f'❌ Ошибок: {error_count}')

        if genre_updates > 0:
            self.stdout.write(f'🎭 Добавлено ID жанров: {genre_updates}')
        if keyword_updates > 0:
            self.stdout.write(f'🔑 Добавлено ID ключевых слов: {keyword_updates}')
        if recommendation_updates > 0:
            self.stdout.write(f'🎬 Добавлено ID рекомендаций: {recommendation_updates}')

        if error_count == 0:
            self.stdout.write(self.style.SUCCESS('\n✅ Команда выполнена успешно'))
        else:
            self.stdout.write(self.style.WARNING(f'\n⚠️  Команда выполнена с {error_count} ошибками'))