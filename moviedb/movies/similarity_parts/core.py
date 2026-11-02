# movies/similarity_parts/core.py
"""Core class for Movie similarity algorithm."""

from .data_mixin import DataMixin
from .scoring_mixin import ScoringMixin
from .search_mixin import SearchMixin


class moviesimilarity(DataMixin, ScoringMixin, SearchMixin):
    """
    Универсальный алгоритм похожести фильмов с динамическими весами.

    source может быть экземпляром Movie или None (тогда критерии берутся
    только из override_criteria).
    """

    # ВЕРСИЯ АЛГОРИТМА — увеличивать при любых изменениях в логике расчета.
    ALGORITHM_VERSION = 10

    DEFAULT_SIMILAR_MOVIES_LIMIT = 500

    # Веса критериев (сумма = 100)
    GENRES_WEIGHT = 40.0
    KEYWORDS_WEIGHT = 30.0
    THEMES_WEIGHT = 20.0
    DEVELOPERS_WEIGHT = 5.0  # production_companies
    SERIES_WEIGHT = 5.0

    # Конфигурационные константы
    DEFAULT_MIN_SIMILARITY = 40
    BONUS_MULTI_CRITERIA = 5.0

    # Вспомогательные константы для расчетов
    KEYWORDS_ADD_PER_MATCH = 0.2
    EXTRA_GENRE_PENALTY = 2.0

    def __init__(self, verbose=False):
        self._similarity_cache = {}
        self._movie_data_cache = {}
        self.stop_flag = False
        self.verbose = verbose

    def set_verbose(self, verbose):
        """Устанавливает режим вывода отладочной информации."""
        self.verbose = verbose

    def clear_cache(self, force=False):
        """Очищает кэш. force=True — полная очистка (по факту та же)."""
        self._similarity_cache.clear()
        self._movie_data_cache.clear()
        if self.verbose:
            print("moviesimilarity: Cache cleared")

    def show_cache_status(self):
        """Показывает статус кэша."""
        print("\n📊 СТАТУС КЭША moviesimilarity:")
        print(f"   Кэш схожести (_similarity_cache): {len(self._similarity_cache)} записей")
        print(f"   Кэш данных фильмов (_movie_data_cache): {len(self._movie_data_cache)} записей")

        if self._similarity_cache:
            print("   Пример ключей в кэше схожести:")
            for key in list(self._similarity_cache.keys())[:3]:
                print(f"     - {key}")