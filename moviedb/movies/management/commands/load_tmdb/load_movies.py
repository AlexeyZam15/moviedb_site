# movies/management/commands/load_movies.py
"""
Команда загрузки фильмов из TMDB.

Флаги (совместимы с full_pipeline и старыми вызовами):
  --limit, --offset, --genres, --description-contains (игнорируется для discover),
  --Movie-names, --overwrite, --reset-offset, --clear-cache, --clear-db-cache,
  --update-missing-data, --update-covers, --count-only, --dry-run, --debug,
  --workers, --language, --append, --no-cache, --cache-ttl,
  --tmdb-ids, --tmdb-ids-file, --year-from, --year-to, --min-vote-count, --sort-by,
  --iteration-limit, --repeat.
"""

from django.core.management.base import BaseCommand
from movies.load_tmdb.command import TmdbLoadCommand


class Command(BaseCommand):
    help = 'Загрузка фильмов из TMDB (discover / search / по tmdb_id)'

    def add_arguments(self, parser):
        # Основные
        parser.add_argument('--limit', type=int, default=0,
                            help='Лимит загружаемых фильмов (0 - без лимита)')
        parser.add_argument('--offset', type=int, default=0,
                            help='Пропустить N TMDB ID (для discover)')
        parser.add_argument('--genres', type=str, default='',
                            help='Жанры TMDB через запятую (логика И). Пример: "Action,Science Fiction"')
        parser.add_argument('--description-contains', type=str, default='',
                            help='[ИГНОРИРУЕТСЯ] discover/movie не поддерживает поиск по тексту')
        parser.add_argument('--Movie-names', type=str, default='',
                            help='Загрузить по названиям (через запятую). Пример: "The Matrix,Inception"')
        parser.add_argument('--overwrite', action='store_true',
                            help='Удалить существующие фильмы и загрузить заново')
        parser.add_argument('--reset-offset', action='store_true',
                            help='Сбросить сохранённый offset')
        parser.add_argument('--clear-cache', action='store_true',
                            help='Очистить кэш проверенных TMDB ID')
        parser.add_argument('--clear-db-cache', action='store_true',
                            help='Очистить весь кэш Django')

        # Режимы
        parser.add_argument('--update-missing-data', action='store_true',
                            help='Дозагрузить полные данные для существующих фильмов (по tmdb_id)')
        parser.add_argument('--update-covers', action='store_true',
                            help='Обновить только cover_url/backdrop_url у существующих фильмов')
        parser.add_argument('--count-only', action='store_true',
                            help='Только подсчитать количество (без сохранения)')

        # TMDB-специфичные
        parser.add_argument('--tmdb-ids', type=int, nargs='+', default=None,
                            help='Список TMDB ID для загрузки (например: --tmdb-ids 11 22)')
        parser.add_argument('--tmdb-ids-file', type=str, default=None,
                            help='Файл со списком TMDB ID (по одному на строку)')
        parser.add_argument('--year-from', type=int, default=None,
                            help='Год выпуска от (discover: primary_release_date.gte)')
        parser.add_argument('--year-to', type=int, default=None,
                            help='Год выпуска до (discover: primary_release_date.lte)')
        parser.add_argument('--min-vote-count', type=int, default=0,
                            help='Минимальное количество оценок (discover: vote_count.gte)')
        parser.add_argument('--sort-by', type=str, default='popularity.desc',
                            help='Сортировка discover (по умолчанию popularity.desc)')
        parser.add_argument('--workers', type=int, default=8,
                            help='Потоков для загрузки полных данных (по умолчанию 8)')
        parser.add_argument('--language', type=str, default='en-US',
                            help='Язык TMDB (по умолчанию en-US)')
        parser.add_argument('--append', type=str,
                            default='keywords,credits,recommendations,similar,release_dates',
                            help='append_to_response (по умолчанию keywords,credits,recommendations,similar,release_dates)')

        # Кэш/повтор
        parser.add_argument('--no-cache', action='store_true',
                            help='Не использовать кэш проверенных TMDB ID')
        parser.add_argument('--cache-ttl', type=int, default=60 * 60 * 24 * 7,
                            help='TTL кэша проверенных TMDB ID (сек)')
        parser.add_argument('--iteration-limit', type=int, default=100,
                            help='[совместимость] Игр за итерацию (не используется)')
        parser.add_argument('--repeat', type=int, default=-1,
                            help='[совместимость] Количество повторений (не используется)')

        # Отладка
        parser.add_argument('--debug', action='store_true',
                            help='Подробный вывод')
        parser.add_argument('--dry-run', action='store_true',
                            help='Не сохранять в БД')

    def handle(self, *args, **options):
        cmd = TmdbLoadCommand(self.stdout, self.stderr, options)
        cmd.run()