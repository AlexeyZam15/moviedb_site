# movies/load_tmdb/tmdb_api.py
"""
TMDB API client.

Использует TMDB_API_READ_ACCESS_TOKEN из settings (Bearer-токен).
По образцу movies/management/commands/tmdb_probe.py.

Поддерживает:
  - GET /movie/{id}?append_to_response=...
  - GET /discover/movie?page=...
  - GET /genre/movie/list
  - ретраи (429 -> Retry-After / экспонента; 5xx -> экспонента;
    timeout/connection -> экспонента)
  - простой rate limiter (~50 req/s)
  - thread-local классификацию последней ошибки
"""

import os
import time
import random
import threading
from typing import Optional, Dict, Any, List

import requests
from django.conf import settings

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"

# Потокобезопасное хранилище последней ошибки запроса (для классификации).
_request_local = threading.local()


def _set_last_error(error_type: str) -> None:
    _request_local.last_error = error_type


def get_last_error() -> str:
    return getattr(_request_local, 'last_error', 'unknown')


class _RateLimiter:
    """Простой rate limiter: не более N запросов в секунду (по умолчанию 50)."""

    def __init__(self, max_per_second: int = 50):
        self.max_per_second = max_per_second
        self._lock = threading.Lock()
        self._window_start = time.time()
        self._count = 0

    def acquire(self) -> None:
        with self._lock:
            now = time.time()
            if now - self._window_start >= 1.0:
                self._window_start = now
                self._count = 0
            if self._count >= self.max_per_second:
                sleep_for = 1.0 - (now - self._window_start)
                if sleep_for > 0:
                    time.sleep(sleep_for)
                self._window_start = time.time()
                self._count = 0
            self._count += 1


_rate_limiter = _RateLimiter(max_per_second=50)

_session: Optional[requests.Session] = None
_session_lock = threading.Lock()


def _get_session() -> requests.Session:
    global _session
    with _session_lock:
        if _session is None:
            s = requests.Session()
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=50,
                pool_maxsize=50,
                max_retries=0,
            )
            s.mount('http://', adapter)
            s.mount('https://', adapter)
            s.headers.update({
                'Accept': 'application/json',
            })
            _session = s
        return _session


def _get_token() -> str:
    token = getattr(settings, 'TMDB_API_READ_ACCESS_TOKEN', None)
    if not token:
        raise RuntimeError(
            'TMDB_API_READ_ACCESS_TOKEN is not set in settings/.env. '
            'Add it and retry.'
        )
    return token


def tmdb_request(
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0,
        retries: int = 3,
) -> Optional[Dict[str, Any]]:
    """
    Выполняет GET-запрос к TMDB API.

    endpoint: путь без базового URL (например, 'movie/11' или 'discover/movie').
    params: query-параметры (language, append_to_response, page, ...).
    Возвращает dict (JSON) или None (после ретраев).

    Классификация последней ошибки — get_last_error():
      'ok', 'http_401', 'http_404', 'http_429', 'http_5xx', 'http_other',
      'timeout', 'connection', 'json', 'no_response', 'exception'.
    """
    token = _get_token()
    url = f"{TMDB_BASE_URL}/{endpoint.lstrip('/')}"
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
    }
    session = _get_session()

    last_error_type = 'unknown'

    for attempt in range(retries):
        _rate_limiter.acquire()
        try:
            response = session.get(
                url,
                params=params,
                headers=headers,
                timeout=timeout,
            )
        except requests.exceptions.Timeout:
            last_error_type = 'timeout'
            time.sleep(min(2 ** attempt + random.uniform(0, 1), 30))
            continue
        except requests.exceptions.ConnectionError:
            last_error_type = 'connection'
            time.sleep(min(2 ** attempt + random.uniform(0, 1), 30))
            continue
        except Exception:
            last_error_type = 'exception'
            time.sleep(min(2 ** attempt, 10))
            continue

        if response is None:
            last_error_type = 'no_response'
            time.sleep(2)
            continue

        status = response.status_code

        if status == 200:
            try:
                data = response.json()
                _set_last_error('ok')
                return data
            except ValueError:
                last_error_type = 'json'
                time.sleep(1)
                continue

        if status == 401:
            last_error_type = 'http_401'
            # Нет смысла ретраить — токен неверный.
            _set_last_error(last_error_type)
            return None

        if status == 404:
            last_error_type = 'http_404'
            _set_last_error(last_error_type)
            return None

        if status == 429:
            last_error_type = 'http_429'
            retry_after = response.headers.get('Retry-After')
            if retry_after:
                try:
                    wait = float(retry_after)
                except ValueError:
                    wait = 5.0 * (attempt + 1)
            else:
                wait = 5.0 * (attempt + 1)
            time.sleep(min(wait + random.uniform(0, 1), 60))
            continue

        if 500 <= status < 600:
            last_error_type = 'http_5xx'
            time.sleep(min(2 ** attempt + random.uniform(0, 1), 30))
            continue

        last_error_type = 'http_other'
        time.sleep(min(2 ** attempt + random.uniform(0, 1), 10))

    _set_last_error(last_error_type)
    return None


def tmdb_get_movie(
        tmdb_id: int,
        append: str = 'keywords,credits,recommendations,similar,release_dates',
        language: str = 'en-US',
        timeout: float = 30.0,
) -> Optional[Dict[str, Any]]:
    """GET /movie/{tmdb_id}?append_to_response=..."""
    return tmdb_request(
        f'movie/{tmdb_id}',
        params={
            'language': language,
            'append_to_response': append,
        },
        timeout=timeout,
    )


def tmdb_discover_movies(
        params: Optional[Dict[str, Any]] = None,
        page: int = 1,
        language: str = 'en-US',
        timeout: float = 30.0,
) -> Optional[Dict[str, Any]]:
    """GET /discover/movie?page=..."""
    p = dict(params or {})
    p['page'] = page
    p['language'] = language
    return tmdb_request('discover/movie', params=p, timeout=timeout)


def tmdb_get_genres(
        language: str = 'en-US',
        timeout: float = 30.0,
) -> Optional[Dict[str, Any]]:
    """GET /genre/movie/list (id -> name)."""
    return tmdb_request(
        'genre/movie/list',
        params={'language': language},
        timeout=timeout,
    )


def build_image_url(path: Optional[str], size: str = 'w500') -> Optional[str]:
    """
    Собирает URL картинки TMDB.

    path: 'poster_path'/'backdrop_path'/'logo_path' из TMDB (начинается с '/').
    size: 'w92', 'w154', 'w185', 'w342', 'w500', 'w780', 'original'.
    Возвращает None, если path пустой.
    """
    if not path:
        return None
    if path.startswith('http://') or path.startswith('https://'):
        return path
    if not path.startswith('/'):
        path = '/' + path
    return f"{TMDB_IMAGE_BASE}/{size}{path}"