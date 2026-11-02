# movies/load_tmdb/offset_manager.py
"""
Сохранение/загрузка offset для TMDB-импорта.

Ключ — md5 от нормализованных параметров (жанры, годы, min_vote_count,
sort_by, режим). Файлы — в settings.BASE_DIR/offset_data/offset_<hash>.json.

Не зависит от load_igdb/offset_manager.py (тот будет удалён/архивирован).
"""

import os
import json
import time
import hashlib
import threading
from typing import Optional, Dict, Any
from collections import OrderedDict

from django.conf import settings


class OffsetManager:
    """Менеджер offset для TMDB-импорта."""

    OFFSET_DIR = os.path.join(settings.BASE_DIR, 'offset_data')
    OFFSET_FILE_PREFIX = 'offset_tmdb_'

    _CACHE: Dict[str, int] = {}
    _CACHE_TIMESTAMP: Dict[str, float] = {}
    _CACHE_LOCK = threading.RLock()
    _CACHE_TTL = 300

    @classmethod
    def _ensure_dir(cls) -> None:
        if not os.path.exists(cls.OFFSET_DIR):
            os.makedirs(cls.OFFSET_DIR, exist_ok=True)

    @classmethod
    def _normalize_params(cls, params: Dict[str, Any]) -> "OrderedDict[str, str]":
        normalized: "OrderedDict[str, str]" = OrderedDict()
        for key, value in sorted((params or {}).items()):
            if value is None:
                normalized[key] = ''
            elif isinstance(value, (list, tuple)):
                normalized[key] = ','.join(str(v) for v in value)
            elif isinstance(value, str):
                normalized[key] = value.strip()
            else:
                normalized[key] = str(value)
        return normalized

    @classmethod
    def _hash(cls, params: Dict[str, Any]) -> str:
        normalized = cls._normalize_params(params)
        s = '|'.join(f'{k}={v}' for k, v in normalized.items())
        return hashlib.md5(s.encode('utf-8')).hexdigest()[:12]

    @classmethod
    def _filename(cls, params: Dict[str, Any]) -> str:
        cls._ensure_dir()
        h = cls._hash(params)
        readable = ''
        if params.get('genres'):
            readable = f"_gen_{str(params['genres'])[:20]}"
        elif params.get('title_names'):
            readable = f"_name_{str(params['title_names'])[:20]}"
        elif params.get('sort_by'):
            readable = f"_sort_{str(params['sort_by'])[:20]}"
        else:
            readable = "_popular"
        import re
        readable = re.sub(r'[^\w\-_]', '_', readable)
        return os.path.join(cls.OFFSET_DIR, f"{cls.OFFSET_FILE_PREFIX}{h}{readable}.json")

    @classmethod
    def save_offset(cls, params: Dict[str, Any], offset: int) -> bool:
        try:
            filename = cls._filename(params)
            payload = {
                'params': dict(cls._normalize_params(params)),
                'offset': int(offset),
                'timestamp': time.time(),
            }
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            with cls._CACHE_LOCK:
                cls._CACHE[cls._hash(params)] = int(offset)
                cls._CACHE_TIMESTAMP[cls._hash(params)] = time.time()
            return True
        except Exception:
            return False

    @classmethod
    def load_offset(cls, params: Dict[str, Any]) -> Optional[int]:
        try:
            h = cls._hash(params)
            with cls._CACHE_LOCK:
                if h in cls._CACHE:
                    if time.time() - cls._CACHE_TIMESTAMP.get(h, 0) < cls._CACHE_TTL:
                        return cls._CACHE[h]
            filename = cls._filename(params)
            if not os.path.exists(filename):
                return None
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
            offset = data.get('offset')
            if offset is None:
                return None
            with cls._CACHE_LOCK:
                cls._CACHE[h] = int(offset)
                cls._CACHE_TIMESTAMP[h] = time.time()
            return int(offset)
        except Exception:
            return None

    @classmethod
    def clear_offset(cls, params: Optional[Dict[str, Any]] = None) -> bool:
        try:
            cls._ensure_dir()
            if params is not None:
                filename = cls._filename(params)
                if os.path.exists(filename):
                    os.remove(filename)
                    h = cls._hash(params)
                    with cls._CACHE_LOCK:
                        cls._CACHE.pop(h, None)
                        cls._CACHE_TIMESTAMP.pop(h, None)
                    return True
                return False
            deleted = 0
            for fn in os.listdir(cls.OFFSET_DIR):
                if fn.startswith(cls.OFFSET_FILE_PREFIX) and fn.endswith('.json'):
                    os.remove(os.path.join(cls.OFFSET_DIR, fn))
                    deleted += 1
            with cls._CACHE_LOCK:
                cls._CACHE.clear()
                cls._CACHE_TIMESTAMP.clear()
            return deleted > 0
        except Exception:
            return False