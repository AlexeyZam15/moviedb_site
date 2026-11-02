"""
Команда для полной очистки данных одной игры и перезапуска анализа.

Удаляет для указанной игры:
- rawg_description
- Все связи с жанрами
- Все связи с темами
- Все связи с ключевыми словами (очищает массив keyword_ids)

Затем запускает анализ заново для определения новых жанров, тем и ключевых слов
на основе оставшихся описаний (summary, storyline, wiki_description).
"""

from django.core.management.base import BaseCommand
from django.db import connection
from movies.models import Movie
import subprocess
import sys


class Command(BaseCommand):
    help = 'Полностью очищает данные одной игры и перезапускает анализ (жанры, темы, ключевые слова)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--Movie-name',
            type=str,
            required=True,
            help='ТОЧНОЕ название игры для сброса (регистронезависимо)'
        )
        parser.add_argument(
            '--Movie-id',
            type=int,
            help='ID игры для сброса (альтернатива --Movie-name)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Показать что будет сделано без изменений'
        )
        parser.add_argument(
            '--no-analyze',
            action='store_true',
            help='Не запускать анализ после очистки'
        )
        parser.add_argument(
            '--analyze-keywords-only',
            action='store_true',
            help='Анализировать ТОЛЬКО ключевые слова (без жанров и тем)'
        )
        parser.add_argument(
            '--analyze-criteria-only',
            action='store_true',
            help='Анализировать ТОЛЬКО жанры и темы (без ключевых слов)'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Принудительное выполнение без подтверждения'
        )

    def handle(self, *args, **options):
        game_name = options['game_name']
        game_id = options.get('game_id')
        dry_run = options['dry_run']
        no_analyze = options['no_analyze']
        analyze_keywords_only = options.get('analyze_keywords_only', False)
        analyze_criteria_only = options.get('analyze_criteria_only', False)
        force = options['force']

        self.stdout.write(self.style.SUCCESS('\n' + '=' * 70))
        self.stdout.write(self.style.SUCCESS('🔄 ПОЛНАЯ ОЧИСТКА ДАННЫХ ИГРЫ'))
        self.stdout.write(self.style.SUCCESS('=' * 70))

        if dry_run:
            self.stdout.write(self.style.WARNING('\n🔧 РЕЖИМ ПРОСМОТРА (--dry-run)'))
            self.stdout.write(self.style.WARNING('   Изменения НЕ будут применены\n'))

        # Поиск игры
        if game_id:
            try:
                Movie = Movie.objects.get(id=game_id)
                self._show_game_info(Movie)

                # Подтверждение
                if not self._confirm_action(Movie, dry_run, force):
                    return

                # Выполняем очистку
                self._clear_game_data(Movie, dry_run, no_analyze, analyze_keywords_only, analyze_criteria_only)
                return

            except Movie.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'❌ Игра с ID {game_id} не найдена'))
                return
        else:
            # Поиск по ТОЧНОМУ имени (регистронезависимо)
            movies = Movie.objects.filter(name__iexact=game_name)

            if not movies.exists():
                self.stdout.write(self.style.ERROR(f'❌ Игра с точным названием "{game_name}" не найдена'))
                self.stdout.write(self.style.WARNING('\n💡 Проверьте название. Поиск чувствителен к регистру.'))

                # Показываем похожие игры для подсказки
                similar = Movie.objects.filter(name__icontains=game_name)[:5]
                if similar:
                    self.stdout.write(self.style.WARNING('\n📋 Возможно, вы искали:'))
                    for g in similar:
                        self.stdout.write(f'   • {g.name} (ID: {g.id})')
                return

            if movies.count() == 1:
                Movie = movies.first()
                self._show_game_info(Movie)

                # Подтверждение
                if not self._confirm_action(Movie, dry_run, force):
                    return

                # Выполняем очистку
                self._clear_game_data(Movie, dry_run, no_analyze, analyze_keywords_only, analyze_criteria_only)

            else:
                # Несколько игр с одинаковым именем
                self.stdout.write(self.style.WARNING(f'\n⚠️ Найдено {movies.count()} игр с именем "{game_name}":'))
                self.stdout.write('-' * 70)

                for i, g in enumerate(movies, 1):
                    self.stdout.write(f'\n{i}. {g.name} (ID: {g.id})')
                    self.stdout.write(f'   IGDB ID: {g.igdb_id}')
                    self.stdout.write(f'   Рейтинг: {g.rating or "Нет"}')
                    self.stdout.write(f'   Оценок: {g.rating_count or 0}')
                    self.stdout.write(
                        f'   Дата релиза: {g.first_release_date.year if g.first_release_date else "Неизвестно"}')
                    self.stdout.write(f'   Жанров: {g.genres.count()}')
                    self.stdout.write(f'   Тем: {g.themes.count()}')
                    self.stdout.write(f'   Ключевых слов: {g.keywords.count()}')
                    self.stdout.write(f'   rawg_description: {"✅ Есть" if g.rawg_description else "❌ Нет"}')

                self.stdout.write('\n' + '=' * 70)
                self.stdout.write(self.style.WARNING('⚠️ Найдено несколько игр с одинаковым именем!'))
                self.stdout.write(self.style.WARNING('   Используйте --Movie-id для выбора конкретной игры:'))
                self.stdout.write('\n   Примеры:')
                for g in movies:
                    self.stdout.write(f'   python manage.py clear_and_reanalyze_game --Movie-id {g.id}')
                self.stdout.write('')
                return

    def _show_game_info(self, Movie):
        """Показывает полную информацию об игре"""
        self.stdout.write('\n' + '=' * 70)
        self.stdout.write(self.style.SUCCESS('📋 ИНФОРМАЦИЯ ОБ ИГРЕ'))
        self.stdout.write('=' * 70)
        self.stdout.write(f'\n🎮 Название: {Movie.name}')
        self.stdout.write(f'🆔 ID в базе: {Movie.id}')
        self.stdout.write(f'🆔 IGDB ID: {Movie.igdb_id}')
        self.stdout.write(f'⭐ Рейтинг: {Movie.rating or "Нет"}')
        self.stdout.write(f'📊 Количество оценок: {Movie.rating_count or 0}')
        self.stdout.write(f'📅 Дата релиза: {Movie.first_release_date.year if Movie.first_release_date else "Неизвестно"}')
        self.stdout.write(f'📝 rawg_description: {"✅ Есть" if Movie.rawg_description else "❌ Нет"}')
        self.stdout.write(f'   Длина: {len(Movie.rawg_description) if Movie.rawg_description else 0} символов')
        self.stdout.write(f'\n📊 СВЯЗИ:')
        self.stdout.write(f'   🎭 Жанров: {Movie.genres.count()}')
        if Movie.genres.exists():
            genres_list = ', '.join([g.name for g in Movie.genres.all()[:5]])
            if Movie.genres.count() > 5:
                genres_list += f' ... и еще {Movie.genres.count() - 5}'
            self.stdout.write(f'      {genres_list}')
        self.stdout.write(f'   🎨 Тем: {Movie.themes.count()}')
        if Movie.themes.exists():
            themes_list = ', '.join([t.name for t in Movie.themes.all()[:5]])
            if Movie.themes.count() > 5:
                themes_list += f' ... и еще {Movie.themes.count() - 5}'
            self.stdout.write(f'      {themes_list}')
        self.stdout.write(f'   🔑 Ключевых слов: {Movie.keywords.count()}')
        if Movie.keywords.exists():
            keywords_list = ', '.join([k.name for k in Movie.keywords.all()[:5]])
            if Movie.keywords.count() > 5:
                keywords_list += f' ... и еще {Movie.keywords.count() - 5}'
            self.stdout.write(f'      {keywords_list}')

        # Показываем другие описания
        self.stdout.write(f'\n📚 ДРУГИЕ ОПИСАНИЯ:')
        self.stdout.write(f'   summary: {"✅ Есть" if Movie.summary else "❌ Нет"}')
        if Movie.summary:
            self.stdout.write(f'      Длина: {len(Movie.summary)} символов')
        self.stdout.write(f'   storyline: {"✅ Есть" if Movie.storyline else "❌ Нет"}')
        if Movie.storyline:
            self.stdout.write(f'      Длина: {len(Movie.storyline)} символов')
        self.stdout.write(f'   wiki_description: {"✅ Есть" if Movie.wiki_description else "❌ Нет"}')
        if Movie.wiki_description:
            self.stdout.write(f'      Длина: {len(Movie.wiki_description)} символов')

        self.stdout.write('\n' + '=' * 70)

    def _confirm_action(self, Movie, dry_run, force):
        """Запрашивает подтверждение действия"""
        if dry_run:
            self.stdout.write(self.style.WARNING('\n🔧 РЕЖИМ ПРОСМОТРА (--dry-run)'))
            self.stdout.write(self.style.WARNING('   Изменения НЕ будут применены'))
            return True

        if force:
            self.stdout.write(self.style.WARNING('\n⚠️ РЕЖИМ ПРИНУДИТЕЛЬНОГО ВЫПОЛНЕНИЯ (--force)'))
            return True

        self.stdout.write('\n' + self.style.WARNING('⚠️ ВНИМАНИЕ: Будет выполнена ПОЛНАЯ ОЧИСТКА данных игры:'))
        self.stdout.write(self.style.WARNING(f'   🎮 {Movie.name} (ID: {Movie.id})'))
        self.stdout.write(self.style.WARNING('   Что будет удалено:'))
        self.stdout.write(self.style.WARNING(
            f'   • rawg_description ({len(Movie.rawg_description) if Movie.rawg_description else 0} символов)'))
        self.stdout.write(self.style.WARNING(f'   • {Movie.genres.count()} жанров'))
        self.stdout.write(self.style.WARNING(f'   • {Movie.themes.count()} тем'))
        self.stdout.write(self.style.WARNING(f'   • {Movie.keywords.count()} ключевых слов'))
        self.stdout.write(self.style.WARNING('   Затем будет запущен АНАЛИЗ (жанры, темы, ключевые слова)'))

        confirm = input('\nПродолжить? (yes/no): ')
        if confirm.lower() != 'yes':
            self.stdout.write(self.style.WARNING('❌ Операция отменена'))
            return False
        return True

    def _clear_game_data(self, Movie, dry_run, no_analyze, analyze_keywords_only, analyze_criteria_only):
        """Выполняет очистку данных игры"""

        # 1. Удаление rawg_description
        self._clear_rawg_description(Movie, dry_run)

        # 2. Удаление жанров
        self._clear_genres(Movie, dry_run)

        # 3. Удаление тем
        self._clear_themes(Movie, dry_run)

        # 4. Удаление ключевых слов (очистка массива keyword_ids)
        self._clear_keywords(Movie, dry_run)

        # 5. Обновление векторов
        self._update_vectors(Movie, dry_run)

        # 6. Перезапуск анализа
        if not no_analyze:
            self._run_analysis(Movie, dry_run, analyze_keywords_only, analyze_criteria_only)

        # Итог
        self._print_summary(Movie, dry_run, no_analyze)

    def _clear_rawg_description(self, Movie, dry_run):
        """Удаляет описание RAWG"""
        self.stdout.write('\n📝 Шаг 1/6: Удаление rawg_description...')

        if dry_run:
            self.stdout.write(self.style.WARNING('   [DRY-RUN] Будет удалено описание RAWG'))
            return

        try:
            Movie.rawg_description = None
            Movie.save(update_fields=['rawg_description'])
            self.stdout.write(self.style.SUCCESS('   ✅ rawg_description удалено'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'   ❌ Ошибка: {e}'))

    def _clear_genres(self, Movie, dry_run):
        """Удаляет все связи с жанрами"""
        self.stdout.write('\n🎭 Шаг 2/6: Удаление жанров...')

        genres_count = Movie.genres.count()

        if dry_run:
            self.stdout.write(self.style.WARNING(f'   [DRY-RUN] Будет удалено {genres_count} жанров'))
            return

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM movies_game_genres WHERE game_id = %s",
                    [Movie.id]
                )
            self.stdout.write(self.style.SUCCESS(f'   ✅ Удалено {genres_count} жанров'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'   ❌ Ошибка: {e}'))

    def _clear_themes(self, Movie, dry_run):
        """Удаляет все связи с темами"""
        self.stdout.write('\n🎨 Шаг 3/6: Удаление тем...')

        themes_count = Movie.themes.count()

        if dry_run:
            self.stdout.write(self.style.WARNING(f'   [DRY-RUN] Будет удалено {themes_count} тем'))
            return

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM movies_game_themes WHERE game_id = %s",
                    [Movie.id]
                )
            self.stdout.write(self.style.SUCCESS(f'   ✅ Удалено {themes_count} тем'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'   ❌ Ошибка: {e}'))

    def _clear_keywords(self, Movie, dry_run):
        """Удаляет все связи с ключевыми словами (очищает массив keyword_ids)"""
        self.stdout.write('\n🔑 Шаг 4/6: Удаление ключевых слов...')

        keywords_count = Movie.keywords.count()

        if dry_run:
            self.stdout.write(self.style.WARNING(f'   [DRY-RUN] Будет удалено {keywords_count} ключевых слов'))
            return

        try:
            # Очищаем массив keyword_ids напрямую через UPDATE
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE movies_game SET keyword_ids = ARRAY[]::integer[] WHERE id = %s",
                    [Movie.id]
                )
            self.stdout.write(
                self.style.SUCCESS(f'   ✅ Удалено {keywords_count} ключевых слов (очищен массив keyword_ids)'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'   ❌ Ошибка: {e}'))

    def _update_vectors(self, Movie, dry_run):
        """Обновляет материализованные векторы игры"""
        self.stdout.write('\n📊 Шаг 5/6: Обновление векторов...')

        if dry_run:
            self.stdout.write(self.style.WARNING('   [DRY-RUN] Будут обновлены векторы'))
            return

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE movies_game
                    SET genre_ids = ARRAY[]::integer[],
                        theme_ids = ARRAY[]::integer[],
                        keyword_ids = ARRAY[]::integer[],
                        perspective_ids = ARRAY[]::integer[],
                        developer_ids = ARRAY[]::integer[],
                        game_mode_ids = ARRAY[]::integer[],
                        engine_ids = ARRAY[]::integer[]
                    WHERE id = %s
                    """,
                    [Movie.id]
                )
            self.stdout.write(self.style.SUCCESS('   ✅ Векторы обновлены'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'   ❌ Ошибка: {e}'))

    def _run_analysis(self, Movie, dry_run, analyze_keywords_only, analyze_criteria_only):
        """Запускает анализ игры (по умолчанию и жанры/темы, и ключевые слова)"""
        self.stdout.write('\n🔍 Шаг 6/6: Запуск анализа...')

        if dry_run:
            cmd = f'analyze_game_criteria_fast --Movie-name "{Movie.name}" --auto-save'

            # Определяем режим анализа
            if analyze_keywords_only:
                cmd += ' --keywords'
                mode = 'ТОЛЬКО ключевые слова'
            elif analyze_criteria_only:
                mode = 'ТОЛЬКО жанры и темы'
            else:
                # По умолчанию: и жанры/темы, и ключевые слова (два запуска)
                mode = 'жанры, темы и ключевые слова (2 этапа)'

            self.stdout.write(self.style.WARNING(f'   [DRY-RUN] Будет выполнен анализ: {mode}'))
            self.stdout.write(self.style.WARNING(f'   [DRY-RUN] Команда: python manage.py {cmd}'))
            return

        try:
            # Шаг A: Анализ жанров и тем (всегда выполняется, если не указан --analyze-keywords-only)
            if not analyze_keywords_only:
                self.stdout.write(f'\n   ▶️ [1/2] Анализ жанров и тем...')
                args = [
                    sys.executable, 'manage.py', 'analyze_game_criteria_fast',
                    '--Movie-name', Movie.name,
                    '--auto-save'
                ]
                subprocess.run(args, check=True)
                self.stdout.write(self.style.SUCCESS('   ✅ Анализ жанров и тем завершен'))

            # Шаг B: Анализ ключевых слов (всегда выполняется, если не указан --analyze-criteria-only)
            if not analyze_criteria_only:
                self.stdout.write(f'\n   ▶️ [2/2] Анализ ключевых слов...')
                args = [
                    sys.executable, 'manage.py', 'analyze_game_criteria_fast',
                    '--Movie-name', Movie.name,
                    '--keywords',
                    '--auto-save'
                ]
                subprocess.run(args, check=True)
                self.stdout.write(self.style.SUCCESS('   ✅ Анализ ключевых слов завершен'))

            self.stdout.write(self.style.SUCCESS('\n   ✅ Весь анализ успешно завершен!'))

        except subprocess.CalledProcessError as e:
            self.stdout.write(self.style.ERROR(f'   ❌ Ошибка выполнения анализа: {e}'))

    def _print_summary(self, Movie, dry_run, no_analyze):
        """Выводит итоговую статистику"""
        # Обновляем статистику после очистки
        Movie.refresh_from_db()

        self.stdout.write('\n' + '=' * 70)
        if dry_run:
            self.stdout.write(self.style.WARNING('📊 РЕЗУЛЬТАТ (DRY-RUN):'))
        else:
            self.stdout.write(self.style.SUCCESS('📊 РЕЗУЛЬТАТ:'))
        self.stdout.write('=' * 70)
        self.stdout.write(f'   🎮 {Movie.name} (ID: {Movie.id})')
        self.stdout.write(f'   📝 rawg_description: {"✅ Удалено" if not Movie.rawg_description else "❌ Осталось"}')
        self.stdout.write(f'   🎭 Жанров: {Movie.genres.count()}')
        self.stdout.write(f'   🎨 Тем: {Movie.themes.count()}')
        self.stdout.write(f'   🔑 Ключевых слов: {Movie.keywords.count()}')

        if not dry_run and not Movie.rawg_description and Movie.genres.count() == 0 and Movie.themes.count() == 0 and Movie.keywords.count() == 0:
            self.stdout.write(self.style.SUCCESS('\n✅ Все данные игры успешно очищены!'))
            if not no_analyze:
                self.stdout.write(self.style.SUCCESS('   Анализ выполнен (жанры, темы, ключевые слова)'))
        elif dry_run:
            self.stdout.write(self.style.WARNING('\n🔧 РЕЖИМ ПРОСМОТРА - изменения НЕ применены'))
        else:
            self.stdout.write(self.style.SUCCESS('\n✅ Операция выполнена успешно!'))
        self.stdout.write('=' * 70 + '\n')