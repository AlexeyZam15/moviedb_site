# movies/management/commands/full_pipeline.py
"""
Единая команда для выполнения полного пайплайна обработки данных (TMDB).

Порядок шагов:
  1. load_movies
  2. add_new_keywords_from_descriptions
  3. normalize_keywords
  4. criteries_reassign
  5. analyze_movie_criteria_fast
     + подшаг: только НОВЫЕ ключевые слова по СТАРЫМ
  6. update_movie_vectors
  7. delete_low_usage_keywords

TV-пресет: --anime-tv = genres Animation + original_language ja + media_type tv.
"""

from django.core.management.base import BaseCommand
from django.db.models import Max
import subprocess
import sys
import time
import os
from datetime import datetime
from typing import List, Optional, Dict, Any, Set
from enum import Enum
import signal


class PipelineInterrupted(Exception):
    """Пайплайн прерван пользователем (Ctrl+C в дочернем процессе)."""
    pass


CTRL_C_RETURNCODES = {3221225786, -1073741510, 130, -2}


class PipelineStep(Enum):
    """Этапы пайплайна (TMDB)."""
    LOAD_MOVIES = "load_movies"
    ADD_KEYWORDS = "add_new_keywords_from_descriptions"
    NORMALIZE_KEYWORDS = "normalize_keywords"
    CRITERIES_REASSIGN = "criteries_reassign"
    ANALYZE_CRITERIA = "analyze_movie_criteria_fast"
    UPDATE_VECTORS = "update_movie_vectors"
    DELETE_LOW_USAGE = "delete_low_usage_keywords"


class Command(BaseCommand):
    """Полный пайплайн обработки данных TMDB."""

    help = 'Выполняет полный пайплайн обработки данных от загрузки до анализа'

    def add_arguments(self, parser):
        parser.add_argument(
            '--media-type', type=str, default='movie',
            choices=['movie', 'tv', 'all'],
            help='Тип медиа для load_movies: movie, tv или all (два прохода)'
        )
        parser.add_argument(
            '--anime-tv', action='store_true',
            help='Пресет TV-аниме: --genres Animation + --original-language ja + --media-type tv'
        )
        parser.add_argument(
            '--original-language', type=str, default=None,
            help='TMDB with_original_language (например: ja)'
        )
        parser.add_argument(
            '--with-keywords', type=str, default=None,
            help='TMDB with_keywords (например: 210024)'
        )
        parser.add_argument('--limit', type=int, default=None,
                            help='Общий лимит для обработки (по умолчанию: без лимита)')
        parser.add_argument('--dry-run', action='store_true',
                            help='Режим просмотра: показывает команды без выполнения')
        parser.add_argument('--verbose', action='store_true', help='Подробный вывод')
        parser.add_argument('--skip-errors', action='store_true',
                            help='Пропускать ошибки и продолжать выполнение')
        parser.add_argument('--skip-update-vectors', action='store_true',
                            help='Пропустить шаг UPDATE_VECTORS')
        parser.add_argument(
            '--start-from', type=str,
            choices=[step.value for step in PipelineStep],
            help='Начать выполнение с указанного шага'
        )
        parser.add_argument(
            '--stop-after', type=str,
            choices=[step.value for step in PipelineStep],
            help='Остановиться после указанного шага'
        )
        parser.add_argument('--anime', action='store_true',
                            help='Пресет аниме: Animation + ja (media_type=movie)')
        parser.add_argument('--genres', type=str, nargs='+', default=[],
                            help='Фильтр по жанрам TMDB (логика И)')
        parser.add_argument('--text-contains', type=str, nargs='+', default=[],
                            help='[ИГНОРИРУЕТСЯ] discover не поддерживает')
        parser.add_argument('--analyze-threads', type=int, default=24,
                            help='Потоков для анализа')
        parser.add_argument('--delete-low-usage', action='store_true',
                            help='Удалить ключевые слова с низким использованием')
        parser.add_argument('--low-usage-threshold', type=int, default=1,
                            help='Порог использования')
        parser.add_argument('--delete-stopwords', action='store_true',
                            help='[УСТАРЕЛ] Чистка стоп-слов всегда на шаге ADD_KEYWORDS')
        parser.add_argument('--no-auto-save', action='store_true',
                            help='Отключить автосохранение результатов анализа')
        parser.add_argument('--force-update', action='store_true',
                            help='Принудительно обновить существующие записи')
        parser.add_argument('--update-all', action='store_true',
                            help='Обновить ВСЕ записи в базе')
        parser.add_argument('--load-movies-limit', type=int,
                            help='Лимит для load_movies')
        parser.add_argument('--keywords-limit', type=int,
                            help='Лимит для add_new_keywords_from_descriptions')
        parser.add_argument('--analyze-limit', type=int,
                            help='Лимит для analyze_movie_criteria_fast')
        parser.add_argument('--output', type=str, default='pipeline_report.txt',
                            help='Путь к файлу отчёта')
        parser.add_argument('--reset-offset', action='store_true',
                            help='Сбросить сохранённый offset')
        parser.add_argument('--reload-movie-tmdb-id', type=int, nargs='+', default=None,
                            help='Перезагрузить конкретные записи по TMDB ID')
        parser.add_argument('--reload-Movie-igdb-id', type=int, nargs='+', default=None,
                            dest='reload_movie_igdb_id_legacy',
                            help='[УСТАРЕЛ] алиас для --reload-movie-tmdb-id')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_time: Optional[datetime] = None
        self.step_results: Dict[str, Any] = {}
        self.errors: List[Dict[str, Any]] = []
        self.all_steps = list(PipelineStep)
        self.output_file = None
        self.output_file_path = None
        self.dry_run = False
        self.verbose = False
        self.skip_errors = False
        self.skip_update_vectors = False
        self.start_from = None
        self.stop_after = None
        self.limit = None
        self.genres = []
        self.text_contains = []
        self.analyze_threads = 24
        self.delete_stopwords = False
        self.auto_save = True
        self.force_update = False
        self.update_all = False
        self.load_movies_limit = None
        self.keywords_limit = None
        self.analyze_limit = None
        self.loaded_movie_ids = []
        self.reset_offset = False
        self.reload_movie_tmdb_ids: List[int] = []
        self.max_keyword_id_before: int = 0
        self.new_keyword_ids: Set[int] = set()
        self.interrupted = False
        self.delete_low_usage = False
        self.low_usage_threshold = 1
        self.original_language = None
        self.with_keywords = None
        self.anime_preset = False
        self.anime_tv_preset = False
        self.media_type = 'movie'
        self.force_reload = False

    def signal_handler(self, signum, frame):
        self._log('\n\n⚠️ Получен сигнал прерывания (Ctrl+C)')
        self._log('⏳ Завершение текущего шага...')

    def _write_to_file(self, text: str):
        if self.output_file:
            try:
                self.output_file.write(text + '\n')
                self.output_file.flush()
            except Exception:
                pass

    def _log(self, message: str, style: str = None):
        if style:
            self.stdout.write(getattr(self.style, style)(message))
        else:
            self.stdout.write(message)
        self._write_to_file(message)

    def _log_section(self, title: str, char: str = '='):
        self._log('')
        self._log(char * 80)
        self._log(title)
        self._log(char * 80)

    def handle(self, *args, **options):
        self.start_time = datetime.now()

        self.dry_run = options.get('dry_run', False)
        self.verbose = options.get('verbose', False)
        self.skip_errors = options.get('skip_errors', False)
        self.skip_update_vectors = options.get('skip_update_vectors', False)
        self.limit = options.get('limit', None)
        self.genres = options.get('genres', [])
        self.text_contains = options.get('text_contains', [])
        self.analyze_threads = options.get('analyze_threads', 24)
        self.delete_stopwords = options.get('delete_stopwords', False)
        self.auto_save = not options.get('no_auto_save', False)
        self.force_update = options.get('force_update', False)
        self.update_all = options.get('update_all', False)
        self.load_movies_limit = options.get('load_movies_limit')
        self.keywords_limit = options.get('keywords_limit')
        self.analyze_limit = options.get('analyze_limit')
        self.reset_offset = options.get('reset_offset', False)
        self.delete_low_usage = options.get('delete_low_usage', False)
        self.low_usage_threshold = options.get('low_usage_threshold', 1)
        self.original_language = options.get('original_language')
        self.with_keywords = options.get('with_keywords')
        self.anime_preset = options.get('anime', False)
        self.anime_tv_preset = options.get('anime_tv', False)
        self.media_type = options.get('media_type') or 'movie'
        self.force_reload = options.get('force_reload', False)

        if self.anime_preset:
            if not self.genres:
                self.genres = ['Animation']
            if not self.original_language:
                self.original_language = 'ja'
            self.media_type = 'all'

        if self.anime_tv_preset:
            if not self.genres:
                self.genres = ['Animation']
            if not self.original_language:
                self.original_language = 'ja'
            self.media_type = 'tv'

        self.reload_movie_tmdb_ids = (
                options.get('reload_movie_tmdb_id')
                or options.get('reload_movie_igdb_id_legacy')
                or []
        )

        if options.get('start_from'):
            self.start_from = PipelineStep(options['start_from'])
        if options.get('stop_after'):
            self.stop_after = PipelineStep(options['stop_after'])

        self._setup_output_file(options.get('output', 'pipeline_report.txt'))

        signal.signal(signal.SIGINT, self.signal_handler)

        try:
            self._write_report_header()
            self._print_header()

            if self.reload_movie_tmdb_ids:
                self._run_reload_movies_by_tmdb_ids()
                self._print_footer()
                return

            steps = self._get_steps_to_run()

            for step in steps:
                self._run_step(step)
                if self.stop_after == step:
                    self._log(f'\n⏹️ Остановлено после шага {step.value}')
                    break

            self._print_footer()

        except PipelineInterrupted:
            self.interrupted = True
            self._log('\n⏹️ Пайплайн прерван пользователем (Ctrl+C в дочернем процессе)')
            self._print_footer()
        except KeyboardInterrupt:
            self.interrupted = True
            self._log('\n⏹️ Прервано пользователем (Ctrl+C)')
            self._print_footer()
        except Exception as e:
            self._log(f'\n❌ Критическая ошибка: {e}')
            if self.verbose:
                import traceback
                traceback.print_exc()
            raise
        finally:
            if self.output_file:
                self.output_file.close()
                self._log(f'\n📄 Отчет сохранен в: {self.output_file_path}')

    def _setup_output_file(self, file_path: str):
        try:
            dir_path = os.path.dirname(os.path.abspath(file_path))
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            self.output_file = open(file_path, 'w', encoding='utf-8')
            self.output_file_path = file_path
        except Exception as e:
            self.stdout.write(f'❌ Ошибка создания файла: {e}')
            self.output_file = None

    def _write_report_header(self):
        self._write_to_file('=' * 80)
        self._write_to_file('ОТЧЕТ О ВЫПОЛНЕНИИ ПАЙПЛАЙНА')
        self._write_to_file('=' * 80)
        self._write_to_file(f'Дата запуска: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        self._write_to_file('=' * 80)
        self._write_to_file('')

    def _print_header(self):
        self._log_section('🚀 ЗАПУСК ПОЛНОГО ПАЙПЛАЙНА ОБРАБОТКИ ДАННЫХ (TMDB)')
        self._log('\n📋 Параметры:')

        if self.reload_movie_tmdb_ids:
            self._log(f'  • РЕЖИМ ПЕРЕЗАГРУЗКИ ПО TMDB ID: {self.reload_movie_tmdb_ids}')
            self._log('  • Остальные шаги пайплайна будут пропущены')
            self._log(f'\n  • Потоков анализа: {self.analyze_threads}')
            self._log(f'\n📄 Отчет будет сохранен в: {self.output_file_path}')
            return

        if self.limit is not None:
            self._log(f'  • Общий лимит: {self.limit:,}')
        else:
            self._log('  • Общий лимит: БЕЗ ЛИМИТА')

        self._log(f'  • media_type: {self.media_type}')
        self._log(f'  • Режим просмотра: {"✅" if self.dry_run else "❌"}')
        self._log(f'  • Подробный вывод: {"✅" if self.verbose else "❌"}')
        self._log(f'  • Пропуск ошибок: {"✅" if self.skip_errors else "❌"}')
        self._log(f'  • Пропуск UPDATE_VECTORS: {"✅" if self.skip_update_vectors else "❌"}')
        self._log(f'  • Принудительное обновление: {"✅" if self.force_update else "❌"}')
        self._log(f'  • Обновить все: {"✅" if self.update_all else "❌"}')
        self._log(f'  • Сброс offset: {"✅" if self.reset_offset else "❌"}')
        self._log('  • Чистка стоп-слов: ✅ (всегда)')
        if self.anime_preset:
            self._log('  • Пресет: --anime (Animation + ja)')
        if self.anime_tv_preset:
            self._log('  • Пресет: --anime-tv (Animation + ja + media_type=tv)')

        if self.start_from:
            self._log(f'  • Начать с: {self.start_from.value}')
        if self.stop_after:
            self._log(f'  • Остановить после: {self.stop_after.value}')

        if self.genres:
            self._log(f'  • Фильтр по жанрам (И): {", ".join(self.genres)}')

        self._log(f'\n  • Потоков анализа: {self.analyze_threads}')

        if self.delete_low_usage:
            self._log(f'  • Удаление низкочастотных слов: ✅ (порог: {self.low_usage_threshold})')

        self._log(f'\n📄 Отчет будет сохранен в: {self.output_file_path}')

    def _run_reload_movies_by_tmdb_ids(self):
        from movies.models import Movie

        self._log_section('🔄 РЕЖИМ ПЕРЕЗАГРУЗКИ ПО TMDB ID')

        if self.dry_run:
            self._log('   ⏭️ [DRY-RUN] Режим перезагрузки пропущен')
            self._log(f'   🔧 [DRY-RUN] Были бы обработаны TMDB ID: {self.reload_movie_tmdb_ids}')
            return

        movies_info = []
        not_found_tmdb = []

        for tmdb_id in self.reload_movie_tmdb_ids:
            movie = Movie.objects.filter(tmdb_id=tmdb_id).first()
            if not movie:
                not_found_tmdb.append(tmdb_id)
                continue
            movies_info.append({
                'tmdb_id': tmdb_id,
                'movie_id': movie.id,
                'name': movie.name,
                'media_type': movie.media_type,
            })

        if not_found_tmdb:
            self._log(f'   ⚠️ Не найдены в БД по TMDB ID: {not_found_tmdb}')

        if not movies_info:
            self._log('   ❌ Нет записей для перезагрузки')
            return

        names = [g['name'] for g in movies_info]
        self._log(f'   📋 К перезагрузке: {len(movies_info)}')
        for g in movies_info:
            self._log(f'      • TMDB ID {g["tmdb_id"]} → Movie.id {g["movie_id"]} («{g["name"]}», {g["media_type"]})')

        self._log('\n   🗑️ Удаление старых записей...')
        deleted_count, _ = Movie.objects.filter(
            tmdb_id__in=[g['tmdb_id'] for g in movies_info]
        ).delete()
        self._log(f'   ✅ Удалено записей: {deleted_count}')

        self._log('\n   📥 Перезагрузка через load_movies --Movie-names...')
        args = [
            '--clear-cache',
            '--clear-db-cache',
            '--Movie-names', ','.join(names),
            '--overwrite',
            '--media-type', self.media_type,
        ]
        self._call_command('load_movies', args)

        self._log('\n   🔍 Поиск новых Movie.id по TMDB ID...')
        new_movies = list(
            Movie.objects.filter(tmdb_id__in=[g['tmdb_id'] for g in movies_info])
            .values_list('tmdb_id', 'id')
        )
        new_map = {tmdb_id: gid for tmdb_id, gid in new_movies}

        reloaded = []
        for g in movies_info:
            new_gid = new_map.get(g['tmdb_id'])
            if new_gid:
                reloaded.append({'tmdb_id': g['tmdb_id'], 'movie_id': new_gid, 'name': g['name']})
                self._log(f'      ✅ TMDB ID {g["tmdb_id"]} → новый Movie.id {new_gid}')
            else:
                self._log(f'      ⚠️ TMDB ID {g["tmdb_id"]} не найден после перезагрузки')

        if not reloaded:
            self._log('   ❌ Не удалось перезагрузить ни одну запись')
            return

        reload_ids_file = 'temp_reload_movie_ids.txt'
        try:
            with open(reload_ids_file, 'w', encoding='utf-8') as f:
                for g in reloaded:
                    f.write(f'{g["movie_id"]}\n')
            self._log(f'   📁 Создан {reload_ids_file}: {len(reloaded)} ID')
        except Exception as e:
            self._log(f'   ⚠️ Ошибка записи {reload_ids_file}: {e}')
            return

        self._log('\n   🔍 Анализ КРИТЕРИЕВ для перезагруженных...')
        args_criteria = [
            f'--threads={self.analyze_threads}',
            '--auto-save',
            '--collect-all-patterns',
            '--Movie-ids-file', reload_ids_file,
        ]
        if self.verbose:
            args_criteria.append('--verbose')
        self._call_command('analyze_movie_criteria_fast', args_criteria)

        self._log('\n   🔑 Анализ КЛЮЧЕВЫХ СЛОВ для перезагруженных...')
        args_keywords = [
            f'--threads={self.analyze_threads}',
            '--keywords',
            '--auto-save',
            '--collect-all-patterns',
            '--Movie-ids-file', reload_ids_file,
        ]
        if self.verbose:
            args_keywords.append('--verbose')
        self._call_command('analyze_movie_criteria_fast', args_keywords)

        self._log('\n   ✅ Перезагрузка завершена')

    def _get_steps_to_run(self) -> List[PipelineStep]:
        all_steps = self.all_steps
        start_index = 0
        if self.start_from:
            for i, step in enumerate(all_steps):
                if step == self.start_from:
                    start_index = i
                    break
        steps = all_steps[start_index:]
        if self.stop_after:
            for i, step in enumerate(steps):
                if step == self.stop_after:
                    steps = steps[:i + 1]
                    break
        return steps

    def _run_step(self, step: PipelineStep):
        self._log_section(f'🔄 ШАГ: {step.value.upper()}')
        step_start = time.time()
        try:
            if step == PipelineStep.LOAD_MOVIES:
                self._run_load_movies()
            elif step == PipelineStep.ADD_KEYWORDS:
                self._run_add_keywords()
            elif step == PipelineStep.NORMALIZE_KEYWORDS:
                self._run_normalize_keywords()
            elif step == PipelineStep.CRITERIES_REASSIGN:
                self._run_criteria_reassign()
            elif step == PipelineStep.ANALYZE_CRITERIA:
                self._run_analyze_criteria()
            elif step == PipelineStep.UPDATE_VECTORS:
                self._run_update_movie_vectors()
            elif step == PipelineStep.DELETE_LOW_USAGE:
                self._run_delete_low_usage()
            step_time = time.time() - step_start
            self.step_results[step.value] = {'status': 'success', 'time': step_time}
            self._log(f'\n✅ Шаг {step.value} завершен за {step_time:.1f}с')
        except PipelineInterrupted:
            step_time = time.time() - step_start
            self.step_results[step.value] = {'status': 'interrupted', 'time': step_time}
            self._log(f'\n⏹️ Шаг {step.value} прерван пользователем')
            raise
        except Exception as e:
            step_time = time.time() - step_start
            self.step_results[step.value] = {'status': 'error', 'time': step_time, 'error': str(e)}
            self.errors.append({'step': step.value, 'error': str(e)})
            self._log(f'\n❌ Шаг {step.value} завершился с ошибкой: {e}')
            if not self.skip_errors:
                raise

    def _run_update_movie_vectors(self):
        if self.skip_update_vectors:
            self._log('   ⏭️ Пропущено (--skip-update-vectors)')
            return
        if self.dry_run:
            self._log('   ⏭️ [DRY-RUN] update_movie_vectors пропущен')
            return
        self._call_command('update_movie_vectors', [])

    def _run_load_movies(self):
        from movies.models import Movie

        if self.dry_run:
            self._log('   ⏭️ [DRY-RUN] load_movies пропущен')
            self.loaded_movie_ids = []
            return

        max_id_before = Movie.objects.aggregate(Max('id'))['id__max'] or 0
        self._log(f'   📌 max(id) до load_movies: {max_id_before}')

        args = []

        if getattr(self, 'force_reload', False):
            args.extend(['--clear-cache', '--clear-db-cache', '--force-reload'])

        if self.load_movies_limit is not None:
            args.extend(['--limit', str(self.load_movies_limit)])
        elif self.limit is not None:
            args.extend(['--limit', str(self.limit)])

        if self.media_type:
            args.extend(['--media-type', self.media_type])

        if self.genres:
            args.extend(['--genres', ','.join(self.genres)])
        if self.original_language:
            args.extend(['--original-language', self.original_language])
        if self.with_keywords:
            args.extend(['--with-keywords', self.with_keywords])
        if self.text_contains:
            args.extend(['--description-contains', ' '.join(self.text_contains)])
        if self.reset_offset:
            args.append('--reset-offset')

        self._call_command('load_movies', args)

        new_movies = Movie.objects.filter(id__gt=max_id_before).order_by('id')
        self.loaded_movie_ids = list(new_movies.values_list('id', flat=True))
        self._log(f'   📊 Загружено новых: {len(self.loaded_movie_ids)}')

        if self.loaded_movie_ids:
            try:
                with open('temp_movie_ids.txt', 'w', encoding='utf-8') as f:
                    for mid in self.loaded_movie_ids:
                        f.write(f'{mid}\n')
                self._log(f'   📁 Создан temp_movie_ids.txt: {len(self.loaded_movie_ids)} ID')
            except Exception as e:
                self._log(f'   ⚠️ Ошибка записи temp_movie_ids.txt: {e}')

    def _run_add_keywords(self):
        from movies.models import Keyword

        self._log('\n   🗑️ Чистка стоп-слов (--delete-stopwords)...')
        stop_args = ['--delete-stopwords']
        if self.dry_run:
            stop_args.append('--dry-run')
        if self.verbose:
            stop_args.append('--verbose')
        try:
            self._call_command('add_new_keywords_from_descriptions', stop_args)
        except PipelineInterrupted:
            raise
        except RuntimeError as e:
            self._log(f'   ⚠️ Чистка стоп-слов завершилась с ошибкой: {e}')

        self.max_keyword_id_before = Keyword.objects.aggregate(Max('id'))['id__max'] or 0
        self._log(f'   📌 max(keyword.id) до add_new_keywords: {self.max_keyword_id_before}')

        args = []
        if self.keywords_limit is not None:
            args.extend(['--limit', str(self.keywords_limit)])
        elif self.limit is not None:
            args.extend(['--limit', str(self.limit)])
        if self.dry_run:
            args.append('--dry-run')
        if self.verbose:
            args.append('--verbose')

        self._call_command('add_new_keywords_from_descriptions', args)

        if self.dry_run:
            self._log('   📊 [DRY-RUN] новые ключевые слова не собираются')
            return

        new_keywords = Keyword.objects.filter(id__gt=self.max_keyword_id_before)
        self.new_keyword_ids = set(new_keywords.values_list('id', flat=True))
        self._log(f'   📊 Новых ключевых слов: {len(self.new_keyword_ids)}')

    def _run_normalize_keywords(self):
        from movies.models import Keyword

        args = ['--merge-only']
        if self.dry_run:
            args.append('--dry-run')
        if self.verbose:
            args.append('--verbose')

        self._call_command('normalize_keywords', args)

        if self.dry_run:
            self._log('   📊 [DRY-RUN] пересборка new_keyword_ids пропущена')
            return

        if self.max_keyword_id_before == 0:
            self._log('   ℹ️ max_keyword_id_before = 0, пересборка невозможна')
            return

        surviving = Keyword.objects.filter(id__gt=self.max_keyword_id_before)
        self.new_keyword_ids = set(surviving.values_list('id', flat=True))
        self._log(f'   📊 Выживших новых ключевых слов: {len(self.new_keyword_ids)}')

    def _run_criteria_reassign(self):
        if self.dry_run:
            self._log('   ⏭️ [DRY-RUN] criteries_reassign пропущен')
            return
        args = ['--apply']
        if self.verbose:
            args.append('--verbose')
        self._call_command('criteries_reassign', args)

    def _run_analyze_criteria(self):
        if self.dry_run:
            self._log('   ⏭️ [DRY-RUN] analyze_movie_criteria_fast пропущен')
            return

        temp_ids_path = 'temp_movie_ids.txt'
        game_ids_file_added = False
        if os.path.exists(temp_ids_path) and self.loaded_movie_ids:
            try:
                with open(temp_ids_path, 'r', encoding='utf-8') as f:
                    has_ids = any(line.strip().isdigit() for line in f)
            except Exception:
                has_ids = False
            if has_ids:
                game_ids_file_added = True

        args = [f'--threads={self.analyze_threads}']
        if self.auto_save:
            args.append('--auto-save')
        args.append('--collect-all-patterns')
        if game_ids_file_added:
            args.extend(['--Movie-ids-file', temp_ids_path])
        if self.analyze_limit is not None:
            args.extend(['--limit', str(self.analyze_limit)])
        elif self.limit is not None:
            args.extend(['--limit', str(self.limit)])
        if self.verbose:
            args.append('--verbose')
        self._call_command('analyze_movie_criteria_fast', args)

        self._log('\n   🔑 Запускаем анализ КЛЮЧЕВЫХ СЛОВ (только по новым)...')
        args_keywords = [f'--threads={self.analyze_threads}', '--keywords']
        if self.auto_save:
            args_keywords.append('--auto-save')
        args_keywords.append('--collect-all-patterns')
        if game_ids_file_added:
            args_keywords.extend(['--Movie-ids-file', temp_ids_path])
        if self.analyze_limit is not None:
            args_keywords.extend(['--limit', str(self.analyze_limit)])
        elif self.limit is not None:
            args_keywords.extend(['--limit', str(self.limit)])
        if self.verbose:
            args_keywords.append('--verbose')
        self._call_command('analyze_movie_criteria_fast', args_keywords)

        self._run_analyze_new_keywords_on_old_movies()

        if not self.dry_run:
            self._log('\n   🎬 Заполнение keyword_ids для TV по summary/tagline...')
            tv_args = ['--apply']
            if self.verbose:
                tv_args.append('--verbose')
            try:
                self._call_command('fill_tv_keywords_from_summary', tv_args)
            except PipelineInterrupted:
                raise
            except Exception as e:
                self._log(f'   ⚠️ fill_tv_keywords_from_summary: {e}')

            self._log('\n   🔄 Синхронизация keyword_ids (pk -> tmdb_id)...')
            conv_args = ['--apply']
            if self.verbose:
                conv_args.append('--verbose')
            self._call_command('convert_keyword_ids_pk_to_tmdb', conv_args)

            self._log('\n   🔄 Синхронизация M2M keywords...')
            sync_args = ['--apply']
            if self.verbose:
                sync_args.append('--verbose')
            self._call_command('sync_keyword_m2m', sync_args)

    def _run_analyze_new_keywords_on_old_movies(self):
        from movies.models import Movie

        self._log('\n   🔄 ПОДШАГ: новые ключевые слова по старым')

        if self.dry_run:
            self._log('   ⏭️ [DRY-RUN] подшаг пропущен')
            return
        if not self.new_keyword_ids:
            self._log('   ⏭️ Нет новых ключевых слов — подшаг пропущен')
            return

        new_kw_file = 'temp_new_keyword_ids.txt'
        try:
            with open(new_kw_file, 'w', encoding='utf-8') as f:
                for kw_id in sorted(self.new_keyword_ids):
                    f.write(f'{kw_id}\n')
        except Exception as e:
            self._log(f'   ⚠️ Ошибка записи {new_kw_file}: {e}')
            return

        loaded_set = set(self.loaded_movie_ids) if self.loaded_movie_ids else set()
        old_movie_ids = []
        try:
            qs = Movie.objects.all().only('id').order_by('id')
            for gid in qs.values_list('id', flat=True).iterator(chunk_size=10000):
                if gid not in loaded_set:
                    old_movie_ids.append(gid)
        except Exception as e:
            self._log(f'   ⚠️ Ошибка сбора старых: {e}')
            return

        if not old_movie_ids:
            self._log('   ⏭️ Нет старых — подшаг пропущен')
            return

        old_movies_file = 'temp_old_movie_ids.txt'
        try:
            with open(old_movies_file, 'w', encoding='utf-8') as f:
                for gid in old_movie_ids:
                    f.write(f'{gid}\n')
        except Exception as e:
            self._log(f'   ⚠️ Ошибка записи {old_movies_file}: {e}')
            return

        args = [
            f'--threads={self.analyze_threads}',
            '--keywords',
            '--keyword-ids-file', new_kw_file,
            '--Movie-ids-file', old_movies_file,
        ]
        if self.auto_save:
            args.append('--auto-save')
        args.append('--collect-all-patterns')
        if self.verbose:
            args.append('--verbose')
        self._call_command('analyze_movie_criteria_fast', args)

    def _run_delete_low_usage(self):
        if not self.delete_low_usage:
            self._log('   ⏭️ Пропущено (опция не включена)')
            return
        args = [f'--usage={self.low_usage_threshold}']
        if self.dry_run:
            args.append('--dry-run')
        self._call_command('delete_low_usage_keywords', args)

    def _call_command(self, command_name: str, args: List[str]):
        if self.dry_run and command_name not in (
                'add_new_keywords_from_descriptions',
                'normalize_keywords',
        ):
            self._log(f'\n   🔧 [DRY-RUN] manage.py {command_name} {" ".join(args)}')
            return

        self._log(f'\n   ▶️ Выполняется: manage.py {command_name} {" ".join(args)}')
        self.stdout.flush()

        try:
            result = subprocess.run(
                [sys.executable, 'manage.py', command_name] + args,
                check=False
            )
            if result.returncode in CTRL_C_RETURNCODES:
                self._log('   ⏹️ Дочерний процесс прерван пользователем (Ctrl+C)')
                raise PipelineInterrupted()
            if result.returncode != 0:
                raise RuntimeError(f'Команда завершилась с кодом {result.returncode}')
        except PipelineInterrupted:
            raise
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f'Ошибка выполнения команды {command_name}: {e}')
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f'Неизвестная ошибка при выполнении {command_name}: {e}')

    def _print_footer(self):
        total_time = (datetime.now() - self.start_time).total_seconds()

        self._log_section('📊 ИТОГОВАЯ СТАТИСТИКА ВЫПОЛНЕНИЯ')

        success_count = 0
        error_count = 0
        interrupted_count = 0

        for step_name, result in self.step_results.items():
            status = result.get('status', 'unknown')
            time_str = f"{result.get('time', 0):.1f}с"
            if status == 'success':
                success_count += 1
                self._log(f'  ✅ {step_name}: {time_str}')
            elif status == 'interrupted':
                interrupted_count += 1
                self._log(f'  ⏹️ {step_name}: {time_str} (прервано)')
            elif status == 'error':
                error_count += 1
                self._log(f'  ❌ {step_name}: {time_str} - {result.get("error", "неизвестная ошибка")}')
            else:
                self._log(f'  ⏭️ {step_name}: {time_str}')

        if self.reload_movie_tmdb_ids:
            self._log(f'\n📋 Режим перезагрузки: TMDB ID {self.reload_movie_tmdb_ids}')

        self._log(f'\n📊 Всего шагов: {len(self.step_results)}')
        self._log(f'  ✅ Успешно: {success_count}')
        self._log(f'  ⏹️ Прервано: {interrupted_count}')
        self._log(f'  ❌ С ошибками: {error_count}')

        if self.errors:
            self._log(f'\n⚠️ Ошибок всего: {len(self.errors)}')
            for error in self.errors[:3]:
                self._log(f'  • {error.get("step", "unknown")}: {error.get("error", "")[:100]}...')

        hours = int(total_time // 3600)
        minutes = int((total_time % 3600) // 60)
        seconds = int(total_time % 60)
        time_str = f"{hours}ч {minutes}м {seconds}с" if hours > 0 else f"{minutes}м {seconds}с"
        self._log(f'\n⏱️ Общее время: {time_str}')

        if self.interrupted:
            self._log('\n⏹️ ПАЙПЛАЙН ПРЕРВАН ПОЛЬЗОВАТЕЛЕМ (Ctrl+C)')
            self._log('📋 Частичные результаты сохранены, БД не повреждена')
        elif self.dry_run:
            self._log('\n🔧 РЕЖИМ ПРОСМОТРА: изменения не были применены')
        else:
            self._log('\n✨ Пайплайн успешно завершен!')

        self._log('=' * 80)




