# movies/load_tmdb/cache.py
"""
Кэш проверенных TMDB ID (чтобы не загружать повторно).

Использует django.core.cache (Redis/LocMem — как в settings.py).
Префикс "tmdb_checked_" — не конфликтует со старым "movies_checked_"
(load_igdb/game_cache.py).
"""

from django.core.cache import cache


class TmdbCacheManager:
    """Менеджер кэша проверенных TMDB ID."""

    CACHE_PREFIX = "tmdb_checked_"
    CACHE_TIMEOUT = 60 * 60 * 24 * 7  # 7 дней
    _SET_KEY = "tmdb_checked_set"

    @classmethod
    def is_checked(cls, tmdb_id) -> bool:
        if not tmdb_id:
            return False
        return cache.get(f"{cls.CACHE_PREFIX}{tmdb_id}") is not None

    @classmethod
    def mark_checked(cls, tmdb_id) -> None:
        if not tmdb_id:
            return
        cache.set(f"{cls.CACHE_PREFIX}{tmdb_id}", True, cls.CACHE_TIMEOUT)
        try:
            s = cache.get(cls._SET_KEY, set())
            if isinstance(s, set):
                s.add(int(tmdb_id))
                cache.set(cls._SET_KEY, s, cls.CACHE_TIMEOUT)
        except Exception:
            pass

    @classmethod
    def batch_check(cls, tmdb_ids) -> dict:
        result = {}
        if not tmdb_ids:
            return result
        try:
            keys = {f"{cls.CACHE_PREFIX}{tid}": int(tid) for tid in tmdb_ids if tid}
            values = cache.get_many(keys.keys())
            for key, tid in keys.items():
                result[tid] = values.get(key) is not None
            missing = [tid for tid in tmdb_ids if tid and not result.get(int(tid), False)]
            if missing:
                s = cache.get(cls._SET_KEY, set())
                if isinstance(s, set):
                    for tid in missing:
                        if int(tid) in s:
                            result[int(tid)] = True
                            cache.set(f"{cls.CACHE_PREFIX}{tid}", True, cls.CACHE_TIMEOUT)
        except Exception:
            for tid in tmdb_ids:
                if tid:
                    result[int(tid)] = cls.is_checked(tid)
        return result

    @classmethod
    def batch_mark_checked(cls, tmdb_ids) -> None:
        if not tmdb_ids:
            return
        try:
            data = {f"{cls.CACHE_PREFIX}{tid}": True for tid in tmdb_ids if tid}
            if data:
                cache.set_many(data, cls.CACHE_TIMEOUT)
            valid = [int(tid) for tid in tmdb_ids if tid]
            s = cache.get(cls._SET_KEY, set())
            if isinstance(s, set):
                s.update(valid)
                cache.set(cls._SET_KEY, s, cls.CACHE_TIMEOUT)
        except Exception:
            for tid in tmdb_ids:
                if tid:
                    cls.mark_checked(tid)

    @classmethod
    def get_checked_count(cls) -> int:
        try:
            try:
                keys = cache.keys(f"{cls.CACHE_PREFIX}*")
                if keys is not None:
                    return len(keys)
            except Exception:
                pass
            s = cache.get(cls._SET_KEY, set())
            return len(s) if isinstance(s, set) else 0
        except Exception:
            return 0

    @classmethod
    def clear_cache(cls) -> int:
        cleared = 0
        try:
            try:
                keys = cache.keys(f"{cls.CACHE_PREFIX}*")
                if keys:
                    cache.delete_many(keys)
                    cleared = len(keys)
            except Exception:
                pass
            cache.delete(cls._SET_KEY)
            if cleared == 0:
                s = cache.get(cls._SET_KEY, set())
                if isinstance(s, set):
                    cleared = len(s)
            return cleared
        except Exception:
            try:
                cache.clear()
                return -1
            except Exception:
                return 0

    @classmethod
    def get_all_checked_ids(cls) -> set:
        try:
            try:
                keys = cache.keys(f"{cls.CACHE_PREFIX}*")
                if keys:
                    return {int(k.replace(cls.CACHE_PREFIX, '')) for k in keys if
                            k.replace(cls.CACHE_PREFIX, '').isdigit()}
            except Exception:
                pass
            s = cache.get(cls._SET_KEY, set())
            return s if isinstance(s, set) else set()
        except Exception:
            return set()