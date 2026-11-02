# movies/management/commands/find_game_offset.py
from django.core.management.base import BaseCommand
from django.db.models import Q
from movies.models import Movie
import math


class Command(BaseCommand):
    """Команда для определения позиции игры в базе данных по названию"""

    help = 'Находит позицию игры в базе данных для использования в offset'

    def add_arguments(self, parser):
        parser.add_argument('game_name', type=str,
                            help='Название игры для поиска (можно часть названия)')
        parser.add_argument('--exact', action='store_true',
                            help='Точный поиск (по умолчанию частичное совпадение)')
        parser.add_argument('--order-by', type=str, default='id',
                            choices=['id', 'name', 'rating', '-id', '-name', '-rating'],
                            help='Поле для сортировки (по умолчанию id)')
        parser.add_argument('--verbose', action='store_true',
                            help='Показать детальную информацию об игре')
        parser.add_argument('--page-size', type=int, default=100,
                            help='Размер страницы для расчета (по умолчанию 100)')

    def handle(self, *args, **options):
        game_name = options['game_name']
        exact = options.get('exact', False)
        order_by = options.get('order_by', 'id')
        verbose = options.get('verbose', False)
        page_size = options.get('page_size', 100)

        self.stdout.write('\n' + '=' * 70)
        self.stdout.write(f'🔍 ПОИСК ПОЗИЦИИ ИГРЫ: "{game_name}"')
        self.stdout.write('=' * 70)

        # Поиск игры
        if exact:
            movies = Movie.objects.filter(name__iexact=game_name)
        else:
            movies = Movie.objects.filter(name__icontains=game_name)

        total_found = movies.count()

        if total_found == 0:
            self.stdout.write(self.style.ERROR(f'❌ Игра "{game_name}" не найдена в базе данных'))
            return

        if total_found > 1:
            self.stdout.write(self.style.WARNING(f'⚠️ Найдено несколько игр ({total_found}):'))

            # Показываем первые 20 для выбора
            for i, Movie in enumerate(movies[:20], 1):
                self.stdout.write(f'   {i}. {Movie.name} (ID: {Movie.igdb_id})')

            if total_found > 20:
                self.stdout.write(f'   ... и еще {total_found - 20}')

            self.stdout.write('\n💡 Используйте более точное название или --exact для точного поиска')

            # Спрашиваем, какую игру выбрать
            if total_found <= 20:
                choice = input('\nВведите номер игры для детального просмотра (или Enter для выхода): ').strip()
                if choice and choice.isdigit():
                    choice_idx = int(choice) - 1
                    if 0 <= choice_idx < total_found:
                        Movie = movies[choice_idx]
                        self._show_game_position(Movie, order_by, page_size, verbose)
            return

        # Найдена одна игра
        Movie = movies.first()
        self._show_game_position(Movie, order_by, page_size, verbose)

    def _show_game_position(self, Movie, order_by, page_size, verbose):
        """Показывает позицию игры в отсортированном списке"""

        self.stdout.write(f'\n🎮 НАЙДЕНА ИГРА:')
        self.stdout.write(f'   • Название: {Movie.name}')
        self.stdout.write(f'   • IGDB ID: {Movie.igdb_id}')
        self.stdout.write(f'   • ID в базе: {Movie.id}')

        if verbose:
            self.stdout.write(f'   • Рейтинг: {Movie.rating if Movie.rating else "Нет"}')
            self.stdout.write(f'   • Дата релиза: {Movie.first_release_date if Movie.first_release_date else "Нет"}')
            self.stdout.write(f'   • Обложка: {"✅ Есть" if Movie.cover_url else "❌ Нет"}')
            self.stdout.write(f'   • Описание: {"✅ Есть" if Movie.summary and Movie.summary.strip() else "❌ Нет"}')
            self.stdout.write(f'   • Жанры: {Movie.genres.count()}')
            self.stdout.write(f'   • Платформы: {Movie.platforms.count()}')
            self.stdout.write(f'   • Скриншоты: {Movie.screenshots.count()}')

        self.stdout.write('\n' + '=' * 70)
        self.stdout.write('📊 ПОЗИЦИЯ В БАЗЕ ДАННЫХ')
        self.stdout.write('=' * 70)

        # Общее количество игр
        total_movies = Movie.objects.count()
        self.stdout.write(f'📦 Всего игр в базе: {total_movies}')

        # Определяем поле для сортировки и направление
        order_desc = order_by.startswith('-')
        order_field = order_by.lstrip('-')

        order_display = {
            'id': 'ID (по умолчанию)',
            'name': 'названию',
            'rating': 'рейтингу'
        }.get(order_field, order_field)

        direction = 'по убыванию' if order_desc else 'по возрастанию'
        self.stdout.write(f'🔽 Сортировка по {order_display} {direction}')

        # Создаем запрос для подсчета позиции
        if order_desc:
            # По убыванию
            if order_field == 'id':
                position = Movie.objects.filter(id__gt=Movie.id).count()
            elif order_field == 'name':
                position = Movie.objects.filter(
                    Q(name__gt=Movie.name) |
                    Q(name=Movie.name, id__gt=Movie.id)
                ).count()
            elif order_field == 'rating':
                position = Movie.objects.filter(
                    Q(rating__gt=Movie.rating) |
                    Q(rating=Movie.rating, id__gt=Movie.id)
                ).count()
            else:
                position = 0
        else:
            # По возрастанию
            if order_field == 'id':
                position = Movie.objects.filter(id__lt=Movie.id).count()
            elif order_field == 'name':
                position = Movie.objects.filter(
                    Q(name__lt=Movie.name) |
                    Q(name=Movie.name, id__lt=Movie.id)
                ).count()
            elif order_field == 'rating':
                position = Movie.objects.filter(
                    Q(rating__lt=Movie.rating) |
                    Q(rating=Movie.rating, id__lt=Movie.id)
                ).count()
            else:
                position = 0

        # Позиция (0-based или 1-based?)
        position_0based = position
        position_1based = position + 1

        self.stdout.write(f'\n📍 ПОЗИЦИЯ ИГРЫ:')
        self.stdout.write(f'   • 0-based позиция (для offset): {position_0based}')
        self.stdout.write(f'   • 1-based позиция: {position_1based} из {total_movies}')

        # Проценты
        percentage_before = (position_0based / total_movies * 100) if total_movies > 0 else 0
        percentage_after = ((total_movies - position_1based) / total_movies * 100) if total_movies > 0 else 0

        self.stdout.write(f'   • Игр до: {position_0based} ({percentage_before:.1f}%)')
        self.stdout.write(f'   • Игр после: {total_movies - position_1based} ({percentage_after:.1f}%)')

        # Расчет страниц
        if page_size > 0:
            page_number = position_0based // page_size + 1
            total_pages = math.ceil(total_movies / page_size)
            position_on_page = position_0based % page_size + 1

            self.stdout.write(f'\n📄 ИНФОРМАЦИЯ ДЛЯ ПАГИНАЦИИ (размер страницы: {page_size}):')
            self.stdout.write(f'   • Номер страницы: {page_number} из {total_pages}')
            self.stdout.write(f'   • Позиция на странице: {position_on_page}')

        # Рекомендации для команд
        self.stdout.write('\n' + '=' * 70)
        self.stdout.write('🚀 РЕКОМЕНДАЦИИ ДЛЯ ЗАПУСКА КОМАНД')
        self.stdout.write('=' * 70)

        # Для load_movies
        self.stdout.write('\n📥 ДЛЯ ЗАГРУЗКИ ИГР (load_movies):')

        if position_0based > 0:
            self.stdout.write(f'   python manage.py load_movies --offset {position_0based} [другие параметры]')
            self.stdout.write(f'   (начнет загрузку с этой игры)')
        else:
            self.stdout.write(f'   ⚠️ Игра уже в начале списка (offset 0)')

        # Для обновления данных
        self.stdout.write('\n🔄 ДЛЯ ОБНОВЛЕНИЯ ДАННЫХ (update-missing-data):')

        # Вариант 1: начать с этой игры
        self.stdout.write(f'   Вариант 1 (начать с этой игры):')
        self.stdout.write(f'   python manage.py load_movies --update-missing-data --offset {position_0based}')

        # Вариант 2: обновить только эту игру
        self.stdout.write(f'\n   Вариант 2 (только эта игра):')
        self.stdout.write(f'   python manage.py load_movies --update-missing-data --Movie-names "{Movie.name}"')

        # Для обновления обложек
        self.stdout.write('\n🖼️  ДЛЯ ОБНОВЛЕНИЯ ОБЛОЖЕК (update-covers):')
        self.stdout.write(f'   python manage.py load_movies --update-covers --offset {position_0based}')

        # Для повторного запуска с сохранением offset
        if position_0based > 0:
            self.stdout.write('\n💾 ДЛЯ ПРОДОЛЖЕНИЯ С СОХРАНЕННЫМ OFFSET:')
            self.stdout.write(f'   Текущий offset для сохранения: {position_0based}')
            self.stdout.write(f'   (offset автоматически сохраняется при использовании --repeat)')

        # Дополнительная информация
        self.stdout.write('\n📌 ПРИМЕРЫ ПОЛНЫХ КОМАНД:')

        # Пример 1: продолжить загрузку популярных игр
        self.stdout.write(f'\n   Пример 1: Продолжить загрузку популярных игр')
        self.stdout.write(f'   python manage.py load_movies --offset {position_0based} --repeat 0')

        # Пример 2: продолжить обновление данных
        self.stdout.write(f'\n   Пример 2: Продолжить обновление данных')
        self.stdout.write(f'   python manage.py load_movies --update-missing-data --offset {position_0based} --repeat 0')

        self.stdout.write('\n' + '=' * 70)