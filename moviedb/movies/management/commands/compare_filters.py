"""
Django management command to compare filters step by step.
Run with: python manage.py compare_filters --Movie-id=13265
"""

from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone
from movies.models import Movie
from movies.similarity import moviesimilarity
import time


class Command(BaseCommand):
    help = 'Compare filters step by step'

    def add_arguments(self, parser):
        parser.add_argument(
            '--Movie-id',
            type=int,
            required=True,
            help='Movie ID to compare'
        )

    def format_time(self, seconds):
        if seconds < 0.001:
            return f"{seconds * 1000000:.0f} мкс"
        elif seconds < 1:
            return f"{seconds * 1000:.1f} мс"
        else:
            return f"{seconds:.2f} сек"

    def get_old_candidate_ids(self, game_id):
        """Получает ID кандидатов из старой версии"""
        Movie = Movie.objects.get(id=game_id)
        similarity_engine = moviesimilarity()
        similarity_engine.verbose = False
        similarity_engine.clear_cache(force=True)

        # Получаем данные через внутренний метод
        source_data, single_player_info = similarity_engine._prepare_source_data(Movie)

        # Вызываем _get_candidate_ids_new напрямую
        candidate_ids = similarity_engine._get_candidate_ids_new(
            source_data,
            single_player_info,
            min_similarity=40,
            search_filters=None
        )

        return sorted(candidate_ids), source_data, single_player_info

    def get_sql_filter_counts(self, game_id):
        """Получает количество игр после каждого фильтра в SQL"""
        current_time = timezone.now()

        with connection.cursor() as cursor:
            # Получаем данные исходной игры
            cursor.execute("""
                           SELECT g.id,
                                  COALESCE(ARRAY_AGG(DISTINCT ggg.genre_id) FILTER(WHERE ggg.genre_id IS NOT NULL), ARRAY[]::integer[])                           as genre_ids,
                                  COALESCE(ARRAY_AGG(DISTINCT ggt.theme_id) FILTER(WHERE ggt.theme_id IS NOT NULL), ARRAY[]::integer[])                           as theme_ids,
                                  COALESCE(ARRAY_AGG(DISTINCT gggp.playerperspective_id) FILTER(WHERE gggp.playerperspective_id IS NOT NULL), ARRAY[]::integer[]) as perspective_ids,
                                  COALESCE(ARRAY_AGG(DISTINCT gggm.gamemode_id) FILTER(WHERE gggm.gamemode_id IS NOT NULL), ARRAY[]::integer[])                   as game_mode_ids,
                                  COALESCE(ARRAY_AGG(DISTINCT gge.gameengine_id) FILTER(WHERE gge.gameengine_id IS NOT NULL), ARRAY[]::integer[])                 as engine_ids,
                                  COALESCE(ARRAY_AGG(DISTINCT ggd.company_id) FILTER(WHERE ggd.company_id IS NOT NULL), ARRAY[]::integer[])                       as developer_ids,
                                  COALESCE(g.keyword_ids, ARRAY[]::integer[])                                                                                     as keyword_ids
                           FROM movies_game g
                                    LEFT JOIN movies_game_genres ggg ON ggg.game_id = g.id
                                    LEFT JOIN movies_game_themes ggt ON ggt.game_id = g.id
                                    LEFT JOIN movies_game_player_perspectives gggp ON gggp.game_id = g.id
                                    LEFT JOIN movies_game_game_modes gggm ON gggm.game_id = g.id
                                    LEFT JOIN movies_game_engines gge ON gge.game_id = g.id
                                    LEFT JOIN movies_game_developers ggd ON ggd.game_id = g.id
                           WHERE g.id = %s
                           GROUP BY g.id, g.keyword_ids
                           """, [game_id])

            row = cursor.fetchone()
            if not row:
                return None

            source_game_id = row[0]
            source_genre_ids = row[1] if row[1] else []
            source_theme_ids = row[2] if row[2] else []
            source_perspective_ids = row[3] if row[3] else []
            source_game_mode_ids = row[4] if row[4] else []
            source_engine_ids = row[5] if row[5] else []
            source_developer_ids = row[6] if row[6] else []
            source_keyword_ids = row[7] if row[7] else []

            # Получаем Single Player режим
            cursor.execute("""
                           SELECT id
                           FROM movies_gamemode
                           WHERE name ILIKE 'single player' 
                   OR name ILIKE 'single' 
                   OR name ILIKE 'singleplayer' 
                   OR name ILIKE 'single-player' 
                   OR name ILIKE '1 player'
                LIMIT 1
                           """)
            row = cursor.fetchone()
            single_player_mode_id = row[0] if row else None

            has_single_player = single_player_mode_id and single_player_mode_id in source_game_mode_ids
            dynamic_min_common_genres = 2 if len(source_genre_ids) >= 2 else 1 if len(source_genre_ids) == 1 else 0

            self.stdout.write(f"\n📊 ДАННЫЕ ИСХОДНОЙ ИГРЫ:")
            self.stdout.write(f"   Жанры: {source_genre_ids}")
            self.stdout.write(f"   Ключевые слова: {len(source_keyword_ids)} шт.")
            self.stdout.write(f"   Темы: {source_theme_ids}")
            self.stdout.write(f"   Перспективы: {source_perspective_ids}")
            self.stdout.write(f"   Режимы игры: {source_game_mode_ids}")
            self.stdout.write(f"   Движки: {source_engine_ids}")
            self.stdout.write(f"   Разработчики: {source_developer_ids}")
            self.stdout.write(f"   Single Player ID: {single_player_mode_id}")
            self.stdout.write(f"   Есть Single Player: {has_single_player}")
            self.stdout.write(f"   Минимальное количество общих жанров: {dynamic_min_common_genres}")

            # ============================================================
            # ФИЛЬТР 1: Все игры с датой релиза
            # ============================================================
            cursor.execute("""
                           SELECT COUNT(DISTINCT g.id)
                           FROM movies_game g
                           WHERE g.first_release_date IS NOT NULL
                             AND g.first_release_date <= %s
                           """, [current_time])
            total_movies = cursor.fetchone()[0]
            self.stdout.write(f"\n🔍 ФИЛЬТР 1: Игры с датой релиза")
            self.stdout.write(f"   Количество: {total_movies}")

            # ============================================================
            # ФИЛЬТР 2: Исключаем исходную игру
            # ============================================================
            cursor.execute("""
                           SELECT COUNT(DISTINCT g.id)
                           FROM movies_game g
                           WHERE g.first_release_date IS NOT NULL
                             AND g.first_release_date <= %s
                             AND g.id != %s
                           """, [current_time, source_game_id])
            total_movies_excl = cursor.fetchone()[0]
            self.stdout.write(f"\n🔍 ФИЛЬТР 2: Исключаем исходную игру")
            self.stdout.write(f"   Количество: {total_movies_excl}")

            # ============================================================
            # ФИЛЬТР 3: Фильтр по жанрам (если есть)
            # ============================================================
            if source_genre_ids and dynamic_min_common_genres > 0:
                genre_ids_str = ','.join(map(str, source_genre_ids))
                cursor.execute(f"""
                    SELECT COUNT(DISTINCT g.id)
                    FROM movies_game g
                    WHERE g.first_release_date IS NOT NULL
                      AND g.first_release_date <= %s
                      AND g.id != %s
                      AND EXISTS (
                          SELECT 1 
                          FROM movies_game_genres ggg 
                          WHERE ggg.game_id = g.id 
                            AND ggg.genre_id IN ({genre_ids_str})
                          GROUP BY ggg.game_id
                          HAVING COUNT(DISTINCT ggg.genre_id) >= {dynamic_min_common_genres}
                      )
                """, [current_time, source_game_id])
                after_genres = cursor.fetchone()[0]
                self.stdout.write(f"\n🔍 ФИЛЬТР 3: Фильтр по жанрам (>= {dynamic_min_common_genres} общих)")
                self.stdout.write(f"   Количество: {after_genres}")

                # Показываем ID первых 10 игр
                cursor.execute(f"""
                    SELECT DISTINCT g.id
                    FROM movies_game g
                    WHERE g.first_release_date IS NOT NULL
                      AND g.first_release_date <= %s
                      AND g.id != %s
                      AND EXISTS (
                          SELECT 1 
                          FROM movies_game_genres ggg 
                          WHERE ggg.game_id = g.id 
                            AND ggg.genre_id IN ({genre_ids_str})
                          GROUP BY ggg.game_id
                          HAVING COUNT(DISTINCT ggg.genre_id) >= {dynamic_min_common_genres}
                      )
                    LIMIT 10
                """, [current_time, source_game_id])
                genre_ids_result = [row[0] for row in cursor.fetchall()]
                self.stdout.write(f"   Первые 10 ID: {genre_ids_result}")

            # ============================================================
            # ФИЛЬТР 4: Фильтр по Single Player (если есть)
            # ============================================================
            if has_single_player and single_player_mode_id:
                if source_genre_ids and dynamic_min_common_genres > 0:
                    genre_ids_str = ','.join(map(str, source_genre_ids))
                    cursor.execute(f"""
                        SELECT COUNT(DISTINCT g.id)
                        FROM movies_game g
                        WHERE g.first_release_date IS NOT NULL
                          AND g.first_release_date <= %s
                          AND g.id != %s
                          AND EXISTS (
                              SELECT 1 
                              FROM movies_game_genres ggg 
                              WHERE ggg.game_id = g.id 
                                AND ggg.genre_id IN ({genre_ids_str})
                              GROUP BY ggg.game_id
                              HAVING COUNT(DISTINCT ggg.genre_id) >= {dynamic_min_common_genres}
                          )
                          AND EXISTS (
                              SELECT 1 
                              FROM movies_game_game_modes gggm 
                              WHERE gggm.game_id = g.id 
                                AND gggm.gamemode_id = {single_player_mode_id}
                          )
                    """, [current_time, source_game_id])
                    after_single = cursor.fetchone()[0]
                    self.stdout.write(f"\n🔍 ФИЛЬТР 4: Фильтр по Single Player")
                    self.stdout.write(f"   Количество: {after_single}")

                    cursor.execute(f"""
                        SELECT DISTINCT g.id
                        FROM movies_game g
                        WHERE g.first_release_date IS NOT NULL
                          AND g.first_release_date <= %s
                          AND g.id != %s
                          AND EXISTS (
                              SELECT 1 
                              FROM movies_game_genres ggg 
                              WHERE ggg.game_id = g.id 
                                AND ggg.genre_id IN ({genre_ids_str})
                              GROUP BY ggg.game_id
                              HAVING COUNT(DISTINCT ggg.genre_id) >= {dynamic_min_common_genres}
                          )
                          AND EXISTS (
                              SELECT 1 
                              FROM movies_game_game_modes gggm 
                              WHERE gggm.game_id = g.id 
                                AND gggm.gamemode_id = {single_player_mode_id}
                          )
                        LIMIT 10
                    """, [current_time, source_game_id])
                    single_ids_result = [row[0] for row in cursor.fetchall()]
                    self.stdout.write(f"   Первые 10 ID: {single_ids_result}")

            # ============================================================
            # ФИЛЬТР 5: Фильтр по rating_count (ЕСЛИ ЕСТЬ)
            # ============================================================
            if has_single_player and single_player_mode_id and source_genre_ids and dynamic_min_common_genres > 0:
                genre_ids_str = ','.join(map(str, source_genre_ids))
                cursor.execute(f"""
                    SELECT COUNT(DISTINCT g.id)
                    FROM movies_game g
                    WHERE g.first_release_date IS NOT NULL
                      AND g.first_release_date <= %s
                      AND g.id != %s
                      AND EXISTS (
                          SELECT 1 
                          FROM movies_game_genres ggg 
                          WHERE ggg.game_id = g.id 
                            AND ggg.genre_id IN ({genre_ids_str})
                          GROUP BY ggg.game_id
                          HAVING COUNT(DISTINCT ggg.genre_id) >= {dynamic_min_common_genres}
                      )
                      AND EXISTS (
                          SELECT 1 
                          FROM movies_game_game_modes gggm 
                          WHERE gggm.game_id = g.id 
                            AND gggm.gamemode_id = {single_player_mode_id}
                      )
                """, [current_time, source_game_id])
                after_rating = cursor.fetchone()[0]
                self.stdout.write(f"\n🔍 ФИЛЬТР 5: БЕЗ фильтра rating_count")
                self.stdout.write(f"   Количество: {after_rating}")

                cursor.execute(f"""
                    SELECT DISTINCT g.id
                    FROM movies_game g
                    WHERE g.first_release_date IS NOT NULL
                      AND g.first_release_date <= %s
                      AND g.id != %s
                      AND EXISTS (
                          SELECT 1 
                          FROM movies_game_genres ggg 
                          WHERE ggg.game_id = g.id 
                            AND ggg.genre_id IN ({genre_ids_str})
                          GROUP BY ggg.game_id
                          HAVING COUNT(DISTINCT ggg.genre_id) >= {dynamic_min_common_genres}
                      )
                      AND EXISTS (
                          SELECT 1 
                          FROM movies_game_game_modes gggm 
                          WHERE gggm.game_id = g.id 
                            AND gggm.gamemode_id = {single_player_mode_id}
                      )
                    LIMIT 10
                """, [current_time, source_game_id])
                final_ids_result = [row[0] for row in cursor.fetchall()]
                self.stdout.write(f"   Первые 10 ID: {final_ids_result}")

            return {
                'total_movies': total_movies,
                'total_movies_excl': total_movies_excl,
                'after_genres': after_genres if 'after_genres' in locals() else None,
                'after_single': after_single if 'after_single' in locals() else None,
                'after_rating': after_rating if 'after_rating' in locals() else None,
                'final_ids': final_ids_result if 'final_ids_result' in locals() else []
            }

    def handle(self, *args, **options):
        game_id = options.get('game_id')

        self.stdout.write(self.style.SUCCESS('\n' + '=' * 70))
        self.stdout.write(self.style.SUCCESS('🔬 СРАВНЕНИЕ ФИЛЬТРОВ КАНДИДАТОВ'))
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write(f"🎮 Игра ID: {game_id}")
        self.stdout.write('=' * 70)

        try:
            Movie = Movie.objects.get(id=game_id)
            self.stdout.write(f"✅ Игра: {Movie.name}")
        except Movie.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"❌ Игра с ID {game_id} не найдена"))
            return

        # Получаем данные из старой версии
        self.stdout.write("\n⏳ Получение кандидатов из старой версии...")
        old_candidates, source_data, single_player_info = self.get_old_candidate_ids(game_id)
        self.stdout.write(f"✅ Старая версия: {len(old_candidates)} кандидатов")
        self.stdout.write(f"   Первые 10 ID: {old_candidates[:10]}")

        # Получаем данные из SQL версии
        self.stdout.write("\n⏳ Получение данных из SQL версии...")
        sql_data = self.get_sql_filter_counts(game_id)

        if sql_data:
            self.stdout.write(self.style.SUCCESS('\n📊 ИТОГОВОЕ СРАВНЕНИЕ:'))
            self.stdout.write(f"   Кандидатов в старой версии: {len(old_candidates)}")
            self.stdout.write(
                f"   Кандидатов в SQL версии (без rating_count): {sql_data['after_rating'] if sql_data['after_rating'] else 'N/A'}")

            if sql_data['after_rating'] and len(old_candidates) != sql_data['after_rating']:
                self.stdout.write(
                    self.style.WARNING(f"\n⚠️ РАЗНИЦА: {len(old_candidates) - sql_data['after_rating']} игр"))

                # Находим ID, которые есть в старой версии, но нет в SQL
                sql_ids = set(sql_data['final_ids'] if sql_data['final_ids'] else [])
                old_ids = set(old_candidates[:10])

                if old_ids and sql_ids:
                    only_old = old_ids - sql_ids
                    only_sql = sql_ids - old_ids

                    if only_old:
                        self.stdout.write(f"\n   ❗️ Игры только в старой версии (первые 10): {list(only_old)}")
                    if only_sql:
                        self.stdout.write(f"\n   ❗️ Игры только в SQL версии (первые 10): {list(only_sql)}")
            elif sql_data['after_rating'] and len(old_candidates) == sql_data['after_rating']:
                self.stdout.write(self.style.SUCCESS(f"\n✅ ИДЕАЛЬНОЕ СОВПАДЕНИЕ!"))

        self.stdout.write(self.style.SUCCESS('\n' + '=' * 70))