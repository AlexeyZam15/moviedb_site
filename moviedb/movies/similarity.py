# movies/similarity.py
"""Thin facade for the similarity algorithm.

Реальная реализация — в пакете `movies.similarity_parts`.
"""

from .similarity_parts import moviesimilarity

__all__ = ['moviesimilarity']