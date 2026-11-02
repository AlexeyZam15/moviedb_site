# movies/management/commands/load_movies.py
"""
Команда загрузки фильмов/сериалов из TMDB.

Флаги: --media-type (movie|tv|all), --anime-tv (preset TV-аниме), --limit, --offset,
--genres, --original-language, --with-keywords, --year-from, --year-to, --sort-by,
--min-vote-count, --tmdb-ids, --tmdb-ids-file, --Movie-names, --overwrite, --reset-offset,
--clear-cache, --clear-db-cache, --update-missing-data, --update-covers, --count-only,
--dry-run, --debug, --workers, --language, --append, --no-cache, --cache-ttl.
"""

from django.core.management.base import BaseCommand
from movies.load_tmdb.command import TmdbLoadCommand


class Command(BaseCommand):
    help = 'Загрузка фильмов/сериалов из TMDB (discover / search / по tmdb_id)'

    def add_arguments(self, parser):
        parser.add_argument('--media-type', type=str, default='movie',
                            choices=['movie', 'tv', 'all'],
                            help='Тип медиа: movie, tv или all (два прохода)')
        parser.add_argument('--skip-existing', dest='skip_existing', action='store_true', default=True,
                            help='Пропускать TMDB ID, уже существующие в БД (по умолчанию: да)')
        parser.add_argument('--no-skip-existing', dest='skip_existing', action='store_false',
                            help='НЕ пропускать существующие (перезагружать детали)')
        parser.add_argument('--force-reload', action='store_true',
                            help='Перезагрузить существующие (эквивалент --no-skip-existing --overwrite)')
        parser.add_argument('--anime-tv', action='store_true',
                            help='Пресет TV-аниме: --genres Animation --original-language ja --media-type tv')

        parser.add_argument('--limit', type=int, default=0,
                            help='Лимит загружаемых записей (0 - без лимита)')
        parser.add_argument('--offset', type=int, default=0,
                            help='Пропустить N TMDB ID (для discover)')
        parser.add_argument('--original-language', type=str, default=None,
                            help='TMDB with_original_language (например: ja)')
        parser.add_argument('--with-keywords', type=str, default=None,
                            help='TMDB with_keywords (например: 210024)')
        parser.add_argument('--genres', type=str, default='',
                            help='Жанры TMDB через запятую (логика И)')
        parser.add_argument('--description-contains', type=str, default='',
                            help='[ИГНОРИРУЕТСЯ] discover не поддерживает поиск по тексту')
        parser.add_argument('--Movie-names', type=str, default='',
                            help='Загрузить по названиям (через запятую)')
        parser.add_argument('--overwrite', action='store_true',
                            help='Удалить существующие и загрузить заново')
        parser.add_argument('--reset-offset', action='store_true',
                            help='Сбросить сохранённый offset')
        parser.add_argument('--clear-cache', action='store_true',
                            help='Очистить кэш проверенных TMDB ID')
        parser.add_argument('--clear-db-cache', action='store_true',
                            help='Очистить весь кэш Django')

        parser.add_argument('--update-missing-data', action='store_true',
                            help='Дозагрузить полные данные для существующих записей')
        parser.add_argument('--update-covers', action='store_true',
                            help='Обновить только cover_url/backdrop_url')
        parser.add_argument('--count-only', action='store_true',
                            help='Только подсчитать количество (без сохранения)')

        parser.add_argument('--tmdb-ids', type=int, nargs='+', default=None,
                            help='Список TMDB ID для загрузки')
        parser.add_argument('--tmdb-ids-file', type=str, default=None,
                            help='Файл со списком TMDB ID')
        parser.add_argument('--year-from', type=int, default=None,
                            help='Год от (discover: primary_release_date.gte / first_air_date.gte)')
        parser.add_argument('--year-to', type=int, default=None,
                            help='Год до (discover: primary_release_date.lte / first_air_date.lte)')
        parser.add_argument('--min-vote-count', type=int, default=0,
                            help='Минимальное количество оценок')
        parser.add_argument('--sort-by', type=str, default='popularity.desc',
                            help='Сортировка discover')
        parser.add_argument('--workers', type=int, default=8,
                            help='Потоков для загрузки полных данных')
        parser.add_argument('--language', type=str, default='en-US',
                            help='Язык TMDB')
        parser.add_argument('--append', type=str,
                            default='keywords,credits,recommendations,similar,release_dates,images',
                            help='append_to_response для movie')

        parser.add_argument('--no-cache', action='store_true',
                            help='Не использовать кэш проверенных TMDB ID')
        parser.add_argument('--cache-ttl', type=int, default=60 * 60 * 24 * 7,
                            help='TTL кэша проверенных TMDB ID (сек)')
        parser.add_argument('--iteration-limit', type=int, default=100,
                            help='[совместимость] не используется')
        parser.add_argument('--repeat', type=int, default=-1,
                            help='[совместимость] не используется')

        parser.add_argument('--debug', action='store_true',
                            help='Подробный вывод')
        parser.add_argument('--dry-run', action='store_true',
                            help='Не сохранять в БД')

    def handle(self, *args, **options):
        if options.get('force_reload'):
            options['skip_existing'] = False
            options['overwrite'] = True
        if options.get('anime_tv'):
            if not options.get('genres'):
                options['genres'] = 'Animation'
            if not options.get('original_language'):
                options['original_language'] = 'ja'
            options['media_type'] = 'tv'
        cmd = TmdbLoadCommand(self.stdout, self.stderr, options)
        cmd.run()

