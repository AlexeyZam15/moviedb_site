# movies/management/commands/analyze_game_criteria_fast_src/progress.py


class ProgressMixin:
    """Инициализация прогресс-бара (совместимость с оригиналом)."""

    def _init_progress_bar(self, total_movies: int):
        """Инициализирует прогресс-бар без немедленного отображения"""
        if self.no_progress or total_movies <= 1:
            return

        try:
            from movies.management.commands.analyzer.progress_bar import ProgressBar

            stat_width = max(4, len(str(total_movies)))

            self.progress_bar = ProgressBar(
                total=total_movies,
                desc="Анализ фильмов",
                bar_length=30,
                update_interval=0.1,
                stat_width=stat_width,
                emoji_spacing=1
            )

            if hasattr(self.progress_bar, 'current'):
                self.progress_bar.current = 0
            if hasattr(self.progress_bar, '_progress_bar'):
                self.progress_bar._progress_bar.current = 0

            self.progress_bar.update_stats({
                'found_count': 0,
                'total_criteria_found': 0,
                'skipped_total': 0,
                'not_found_count': 0,
                'errors': 0,
                'updated': 0,
                'in_batch': 0
            })

            if hasattr(self.progress_bar, '_progress_bar'):
                self.progress_bar._progress_bar._force_update = lambda: None

            if hasattr(self.progress_bar, '_progress_bar') and hasattr(self.progress_bar._progress_bar, 'display'):
                self.progress_bar._progress_bar.display = lambda: None

        except Exception:
            self.progress_bar = None
            self.no_progress = True
