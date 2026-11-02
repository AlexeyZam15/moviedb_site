"""
Middleware package for movies app.
"""

from .database_optimization import DatabaseOptimizationMiddleware

__all__ = ['DatabaseOptimizationMiddleware']