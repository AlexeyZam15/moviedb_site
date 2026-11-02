# movies/similarity_parts/utils.py
"""Utility helpers for similarity algorithm."""


def timeit(func):
    """Декоратор для замера времени выполнения метода."""

    def wrapper(self, *args, **kwargs):
        if not getattr(self, 'verbose', False):
            return func(self, *args, **kwargs)

        import time
        start_time = time.time()
        method_name = func.__name__

        print(f"\n⏱️  НАЧАЛО: {method_name}")

        result = func(self, *args, **kwargs)

        elapsed_time = time.time() - start_time
        print(f"✅ ЗАВЕРШЕНО: {method_name} - {elapsed_time:.2f} сек")

        return result

    return wrapper