# movies/management/commands/analyzer/text_preparer.py
"""
Подготовка текста для анализа (TMDB-модель).

ВАЖНО: в новой TMDB-модели Movie есть только текстовые поля
`summary` и `tagline`. Полей `storyline`, `rawg_description`,
`wiki_description` больше нет. Все ветки, которые раньше
обращались к ним, маппятся на `summary` (+ `tagline`).
"""

from movies.models import Movie


class TextPreparer:
    """Подготавливает текст для анализа из TMDB-полей Movie."""

    def __init__(self, command_instance):
        self.command = command_instance
        self.text_source_mode = self._resolve_text_source_priority()

    def _resolve_text_source_priority(self) -> str:
        """Разрешает приоритет опций источника текста."""
        if getattr(self.command, 'use_wiki', False):
            return 'use_wiki'
        elif getattr(self.command, 'use_rawg', False):
            return 'use_rawg'
        elif getattr(self.command, 'use_storyline', False):
            return 'use_storyline'
        elif getattr(self.command, 'prefer_wiki', False):
            return 'prefer_wiki'
        elif getattr(self.command, 'prefer_storyline', False):
            return 'prefer_storyline'
        elif getattr(self.command, 'combine_all_texts', False):
            return 'combine_all_texts'
        elif getattr(self.command, 'combine_texts', False):
            return 'combine_texts'
        else:
            return 'default'

    def prepare_text(self, Movie: Movie) -> str:
        """
        Возвращает текст для анализа.

        В TMDB-модели доступны только `summary` и `tagline`.
        Все старые режимы (use_wiki/use_rawg/use_storyline/...) маппятся
        на эти два поля, чтобы не ломать вызывающий код.
        """
        has_summary = bool(Movie.summary and Movie.summary.strip())
        has_tagline = bool(Movie.tagline and Movie.tagline.strip())

        if self.text_source_mode in (
                'use_wiki', 'use_rawg', 'use_storyline', 'prefer_wiki',
                'prefer_storyline', 'default',
        ):
            # Все «специфичные» режимы теперь эквивалентны: summary, иначе tagline.
            if has_summary:
                return Movie.summary
            if has_tagline:
                return Movie.tagline
            return ""

        if self.text_source_mode == 'combine_all_texts':
            texts = []
            if has_summary:
                texts.append(Movie.summary)
            if has_tagline:
                texts.append(Movie.tagline)
            return " ".join(texts) if texts else ""

        if self.text_source_mode == 'combine_texts':
            texts = []
            if has_summary:
                texts.append(Movie.summary)
            if has_tagline:
                texts.append(Movie.tagline)
            return " ".join(texts) if texts else ""

        # fallback
        if has_summary:
            return Movie.summary
        if has_tagline:
            return Movie.tagline
        return ""

    def get_source_description(self) -> str:
        """Возвращает описание источника текста."""
        descriptions = {
            'use_wiki': "ТОЛЬКО summary (TMDB)",
            'use_rawg': "ТОЛЬКО summary (TMDB)",
            'use_storyline': "ТОЛЬКО summary (TMDB)",
            'prefer_wiki': "ПРЕДПОЧТИТЕЛЬНО summary (TMDB)",
            'prefer_storyline': "ПРЕДПОЧТИТЕЛЬНО summary (TMDB)",
            'combine_all_texts': "ОБЪЕДИНЕННЫЙ текст (summary + tagline)",
            'combine_texts': "ОБЪЕДИНЕННЫЙ текст (summary + tagline)",
            'default': "ПРЕДПОЧТИТЕЛЬНО summary (TMDB)",
        }
        return descriptions.get(self.text_source_mode, "Неизвестно")

    def get_text_source_for_game(self, Movie: Movie, text_to_analyze: str) -> str:
        """Определяет источник текста для отладочной информации."""
        if self.text_source_mode in ('combine_all_texts', 'combine_texts'):
            return "объединенный текст (summary + tagline)"
        if Movie.summary and text_to_analyze == Movie.summary:
            return "summary (TMDB)"
        if Movie.tagline and text_to_analyze == Movie.tagline:
            return "tagline (TMDB)"
        return "неизвестный источник"