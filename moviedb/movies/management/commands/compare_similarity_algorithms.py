# movies/management/commands/compare_similarity_algorithms.py
"""
Django management command to compare old and new similarity algorithms for mass update.
Run with: python manage.py compare_similarity_algorithms --Movie-id=13265
"""

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import Q
from django.utils import timezone
from movies.models import Movie
from movies.similarity import moviesimilarity
import time
import sys


class Command(BaseCommand):
    help = 'Compare old and new similarity algorithms for mass update'

    def add_arguments(self, parser):
        parser.add_argument(
            '--Movie-id',
            type=int,
            nargs='+',
            help='Movie IDs to compare'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=12,
            help='Number of similar movies to compare (default: 12)'
        )
        parser.add_argument(
            '--min-similarity',
            type=int,
            default=40,
            help='Minimum similarity percentage (default: 40)'
        )
        parser.add_argument(
            '--count',
            type=int,
            default=100,
            help='Number of movies to test for mass update (default: 100)'
        )
        parser.add_argument(
            '--mass-test',
            action='store_true',
            help='Test mass update performance on multiple movies'
        )

    def format_time(self, seconds):
        if seconds < 0.001:
            return f"{seconds * 1000000:.0f} мкс"
        elif seconds < 1:
            return f"{seconds * 1000:.1f} мс"
        else:
            return f"{seconds:.2f} сек"

    def get_old_algorithm_results(self, game_id, limit=12, min_similarity=40):
        """Получает результаты старого алгоритма"""
        Movie = Movie.objects.get(id=game_id)
        similarity_engine = moviesimilarity()
        similarity_engine.verbose = False
        similarity_engine.clear_cache(force=True)

        start = time.time()
        similar_data = similarity_engine.find_similar_movies(
            source_game=Movie,
            min_similarity=min_similarity,
            limit=limit
        )
        elapsed = time.time() - start

        results = []
        for item in similar_data:
            if isinstance(item, dict):
                results.append({
                    'id': item['Movie'].id,
                    'name': item['Movie'].name,
                    'similarity': item['similarity']
                })
            else:
                results.append({
                    'id': item.id,
                    'name': item.name,
                    'similarity': getattr(item, 'similarity', 0)
                })

        return results, elapsed

    def get_raw_sql_optimized_results(self, game_id, limit=12, min_similarity=40):
        """Получает результаты через оптимизированный сырой SQL запрос"""
        start = time.time()

        # Получаем данные исходной игры
        with connection.cursor() as cursor:
            cursor.execute("""
                           SELECT g.id,
                                  COALESCE(g.genre_ids, ARRAY[]::integer[])       as genre_ids,
                                  COALESCE(g.keyword_ids, ARRAY[]::integer[])     as keyword_ids,
                                  COALESCE(g.theme_ids, ARRAY[]::integer[])       as theme_ids,
                                  COALESCE(g.perspective_ids, ARRAY[]::integer[]) as perspective_ids,
                                  COALESCE(g.game_mode_ids, ARRAY[]::integer[])   as game_mode_ids,
                                  COALESCE(g.engine_ids, ARRAY[]::integer[])      as engine_ids,
                                  COALESCE(g.developer_ids, ARRAY[]::integer[])   as developer_ids,
                                  COALESCE(array_length(g.genre_ids, 1), 0)       as genre_count,
                                  COALESCE(array_length(g.keyword_ids, 1), 0)     as keyword_count,
                                  COALESCE(array_length(g.theme_ids, 1), 0)       as theme_count,
                                  COALESCE(array_length(g.perspective_ids, 1), 0) as perspective_count,
                                  COALESCE(array_length(g.game_mode_ids, 1), 0)   as game_mode_count,
                                  COALESCE(array_length(g.engine_ids, 1), 0)      as engine_count,
                                  COALESCE(array_length(g.developer_ids, 1), 0)   as developer_count
                           FROM movies_game g
                           WHERE g.id = %s
                           """, [game_id])

            row = cursor.fetchone()
            if not row:
                return [], 0

            source_game_id = row[0]
            source_genre_ids = row[1] or []
            source_keyword_ids = row[2] or []
            source_theme_ids = row[3] or []
            source_perspective_ids = row[4] or []
            source_game_mode_ids = row[5] or []
            source_engine_ids = row[6] or []
            source_developer_ids = row[7] or []
            source_genre_count = row[8] or 0
            source_keyword_count = row[9] or 0
            source_theme_count = row[10] or 0
            source_perspective_count = row[11] or 0
            source_game_mode_count = row[12] or 0
            source_engine_count = row[13] or 0
            source_developer_count = row[14] or 0

        # Получаем Single Player режим
        single_player_mode_id = None
        with connection.cursor() as cursor:
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
            if row:
                single_player_mode_id = row[0]

        has_single_player = single_player_mode_id and single_player_mode_id in source_game_mode_ids
        dynamic_min_common_genres = 2 if source_genre_count >= 2 else 1 if source_genre_count == 1 else 0

        # Формируем SQL запрос
        genre_ids_str = ','.join(map(str, source_genre_ids)) if source_genre_ids else ''
        keyword_ids_str = ','.join(map(str, source_keyword_ids)) if source_keyword_ids else ''
        theme_ids_str = ','.join(map(str, source_theme_ids)) if source_theme_ids else ''
        perspective_ids_str = ','.join(map(str, source_perspective_ids)) if source_perspective_ids else ''
        game_mode_ids_str = ','.join(map(str, source_game_mode_ids)) if source_game_mode_ids else ''
        engine_ids_str = ','.join(map(str, source_engine_ids)) if source_engine_ids else ''
        developer_ids_str = ','.join(map(str, source_developer_ids)) if source_developer_ids else ''

        # Строим условия для EXISTS
        exists_conditions = []
        if genre_ids_str:
            exists_conditions.append(
                f"EXISTS (SELECT 1 FROM movies_game_genres ggg WHERE ggg.game_id = g.id AND ggg.genre_id IN ({genre_ids_str}))")
        if keyword_ids_str:
            exists_conditions.append(f"g.keyword_ids && ARRAY[{keyword_ids_str}]::integer[]")
        if theme_ids_str:
            exists_conditions.append(
                f"EXISTS (SELECT 1 FROM movies_game_themes ggt WHERE ggt.game_id = g.id AND ggt.theme_id IN ({theme_ids_str}))")
        if perspective_ids_str:
            exists_conditions.append(
                f"EXISTS (SELECT 1 FROM movies_game_player_perspectives gggp WHERE gggp.game_id = g.id AND gggp.playerperspective_id IN ({perspective_ids_str}))")
        if game_mode_ids_str:
            exists_conditions.append(
                f"EXISTS (SELECT 1 FROM movies_game_game_modes gggm WHERE gggm.game_id = g.id AND gggm.gamemode_id IN ({game_mode_ids_str}))")
        if engine_ids_str:
            exists_conditions.append(
                f"EXISTS (SELECT 1 FROM movies_game_engines gge WHERE gge.game_id = g.id AND gge.gameengine_id IN ({engine_ids_str}))")
        if developer_ids_str:
            exists_conditions.append(
                f"EXISTS (SELECT 1 FROM movies_game_developers ggd WHERE ggd.game_id = g.id AND ggd.company_id IN ({developer_ids_str}))")

        exists_sql = " OR ".join(exists_conditions) if exists_conditions else "TRUE"

        # Основной SQL запрос
        raw_sql = f"""
            WITH source_data AS (
                SELECT 
                    {source_genre_count} as source_genre_count,
                    {source_keyword_count} as source_keyword_count,
                    {source_theme_count} as source_theme_count,
                    {source_perspective_count} as source_perspective_count,
                    {source_game_mode_count} as source_game_mode_count,
                    {source_engine_count} as source_engine_count,
                    {source_developer_count} as source_developer_count,
                    {dynamic_min_common_genres} as min_genres,
                    {single_player_mode_id if single_player_mode_id else 'NULL'} as single_player_id,
                    {has_single_player}::boolean as require_single_player,
                    ARRAY[{genre_ids_str}]::integer[] as source_genre_ids,
                    ARRAY[{keyword_ids_str}]::integer[] as source_keyword_ids,
                    ARRAY[{theme_ids_str}]::integer[] as source_theme_ids,
                    ARRAY[{perspective_ids_str}]::integer[] as source_perspective_ids,
                    ARRAY[{game_mode_ids_str}]::integer[] as source_game_mode_ids,
                    ARRAY[{engine_ids_str}]::integer[] as source_engine_ids,
                    ARRAY[{developer_ids_str}]::integer[] as source_developer_ids
            ),
            candidate_movies AS (
                SELECT DISTINCT g.id
                FROM movies_game g
                CROSS JOIN source_data s
                WHERE g.first_release_date IS NOT NULL
                  AND g.id != %s
                  AND ({exists_sql})
            ),
            game_stats AS (
                SELECT 
                    g.id as game_id,
                    COALESCE(cardinality(g.genre_ids & s.source_genre_ids), 0) as common_genres,
                    COALESCE(cardinality(g.keyword_ids & s.source_keyword_ids), 0) as common_keywords,
                    COALESCE(cardinality(g.theme_ids & s.source_theme_ids), 0) as common_themes,
                    COALESCE(cardinality(g.perspective_ids & s.source_perspective_ids), 0) as common_perspectives,
                    COALESCE(cardinality(g.game_mode_ids & s.source_game_mode_ids), 0) as common_game_modes,
                    COALESCE(cardinality(g.engine_ids & s.source_engine_ids), 0) as common_engines,
                    COALESCE(cardinality(g.developer_ids & s.source_developer_ids), 0) as common_developers,
                    COALESCE(cardinality(g.genre_ids), 0) as total_genres,
                    COALESCE(cardinality(g.keyword_ids), 0) as total_keywords,
                    COALESCE(cardinality(g.theme_ids), 0) as total_themes,
                    COALESCE(cardinality(g.perspective_ids), 0) as total_perspectives,
                    COALESCE(cardinality(g.game_mode_ids), 0) as total_game_modes,
                    COALESCE(cardinality(g.engine_ids), 0) as total_engines,
                    COALESCE(cardinality(g.developer_ids), 0) as total_developers,
                    CASE 
                        WHEN s.single_player_id IS NOT NULL 
                        THEN s.single_player_id = ANY(g.game_mode_ids)
                        ELSE FALSE
                    END as has_single_player
                FROM movies_game g
                CROSS JOIN source_data s
                WHERE g.id IN (SELECT id FROM candidate_movies)
            )
            SELECT 
                game_id,
                common_genres,
                common_keywords,
                common_themes,
                common_perspectives,
                common_game_modes,
                common_engines,
                common_developers,
                total_genres,
                total_keywords,
                total_themes,
                total_perspectives,
                total_game_modes,
                total_engines,
                total_developers,
                has_single_player
            FROM game_stats
            CROSS JOIN source_data
            WHERE common_genres >= source_data.min_genres
              AND (NOT source_data.require_single_player OR has_single_player)
            ORDER BY 
                (common_genres * 30.0 / GREATEST(source_data.source_genre_count, 1) + 
                 common_keywords * 0.2 + 
                 common_themes * 10.0 / GREATEST(source_data.source_theme_count, 1) + 
                 common_perspectives * 10.0 / GREATEST(source_data.source_perspective_count, 1) + 
                 common_game_modes * 5.0 / GREATEST(source_data.source_game_mode_count, 1) + 
                 common_developers * 5.0 / GREATEST(source_data.source_developer_count, 1)) DESC
            LIMIT {limit}
        """

        with connection.cursor() as cursor:
            cursor.execute(raw_sql, [source_game_id])
            rows = cursor.fetchall()

        results = []
        for row in rows:
            game_id_result = row[0]
            similarity = 0.0

            # Рассчитываем схожесть по тому же алгоритму
            common_genres = row[1]
            common_keywords = row[2]
            common_themes = row[3]
            common_perspectives = row[4]
            common_game_modes = row[5]
            common_engines = row[6]
            common_developers = row[7]

            if source_genre_count > 0:
                genre_score = common_genres * 30.0 / source_genre_count
                total_genres = row[8]
                extra_genres = total_genres - common_genres
                genre_score -= extra_genres * 2.0
                similarity += max(0.0, genre_score)

            if source_keyword_count > 0:
                similarity += min(common_keywords * 0.2, 40.0)

            if source_theme_count > 0 and common_themes > 0:
                similarity += (common_themes / source_theme_count) * 10.0

            if source_perspective_count > 0 and common_perspectives > 0:
                similarity += (common_perspectives / source_perspective_count) * 10.0

            if source_game_mode_count > 0 and common_game_modes > 0:
                similarity += (common_game_modes / source_game_mode_count) * 5.0

            if source_developer_count > 0 and common_developers > 0:
                similarity += (common_developers / source_developer_count) * 5.0

            if source_engine_count > 0 and common_engines > 0:
                similarity += (common_engines / source_engine_count) * 0.0

            # Бонус
            has_any = any([
                common_genres > 0, common_keywords > 0, common_themes > 0,
                common_perspectives > 0, common_game_modes > 0,
                common_developers > 0, common_engines > 0
            ])
            active_count = sum([
                source_genre_count > 0, source_keyword_count > 0,
                source_theme_count > 0, source_perspective_count > 0,
                source_game_mode_count > 0, source_developer_count > 0,
                source_engine_count > 0
            ])
            if has_any and active_count > 1:
                similarity += 5.0

            similarity = min(100.0, max(0.0, similarity))

            if similarity >= min_similarity:
                results.append({
                    'id': game_id_result,
                    'similarity': round(similarity, 2)
                })

        # Добавляем исходную игру
        results.append({
            'id': source_game_id,
            'similarity': 100.0
        })

        # Сортируем и берем лимит
        results.sort(key=lambda x: x['similarity'], reverse=True)
        results = results[:limit]

        # Загружаем названия игр
        game_ids = [item['id'] for item in results]
        movies = Movie.objects.filter(id__in=game_ids).only('id', 'name')
        game_dict = {Movie.id: Movie for Movie in movies}

        final_results = []
        for item in results:
            Movie = game_dict.get(item['id'])
            if Movie:
                final_results.append({
                    'id': Movie.id,
                    'name': Movie.name,
                    'similarity': item['similarity']
                })

        elapsed = time.time() - start
        return final_results, elapsed

    def test_mass_update_performance(self, count=100, limit=12, min_similarity=40):
        """Тестирует производительность массового обновления"""
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write("📊 ТЕСТ МАССОВОГО ОБНОВЛЕНИЯ")
        self.stdout.write("=" * 70)
        self.stdout.write(f"🎯 Тестируем на {count} играх")

        # Получаем игры для теста - ИСПРАВЛЕННЫЙ ФИЛЬТР
        movies = Movie.objects.filter(
            Q(similar_game_ids=[]) | Q(similar_game_ids__isnull=True)
        ).only('id', 'name')[:count]

        if not movies:
            self.stdout.write("⚠️ Нет игр с пустыми similar_game_ids для теста")
            return

        self.stdout.write(f"✅ Найдено {len(movies)} игр для теста\n")

        # Тест старого алгоритма
        self.stdout.write("⏳ Тест старого алгоритма...")
        old_times = []
        old_total_ids = set()
        old_start = time.time()

        for Movie in movies:
            try:
                results, elapsed = self.get_old_algorithm_results(Movie.id, limit, min_similarity)
                old_times.append(elapsed)
                for r in results:
                    old_total_ids.add(r['id'])
            except Exception as e:
                self.stdout.write(f"   ⚠️ Ошибка для игры {Movie.id}: {str(e)[:50]}")

        old_elapsed = time.time() - old_start

        # Тест SQL алгоритма
        self.stdout.write("⏳ Тест SQL алгоритма...")
        sql_times = []
        sql_total_ids = set()
        sql_start = time.time()

        for Movie in movies:
            try:
                results, elapsed = self.get_raw_sql_optimized_results(Movie.id, limit, min_similarity)
                sql_times.append(elapsed)
                for r in results:
                    sql_total_ids.add(r['id'])
            except Exception as e:
                self.stdout.write(f"   ⚠️ Ошибка для игры {Movie.id}: {str(e)[:50]}")

        sql_elapsed = time.time() - sql_start

        # Результаты
        self.stdout.write("\n" + "-" * 70)
        self.stdout.write(self.style.SUCCESS("\n📊 РЕЗУЛЬТАТЫ ТЕСТА:"))
        self.stdout.write(f"\n{'Параметр':<30} {'Старый':<20} {'SQL':<20}")
        self.stdout.write("-" * 70)

        avg_old = sum(old_times) / len(old_times) if old_times else 0
        avg_sql = sum(sql_times) / len(sql_times) if sql_times else 0

        self.stdout.write(f"{'Общее время':<30} {old_elapsed:.2f}с{'':<15} {sql_elapsed:.2f}с")
        self.stdout.write(f"{'Среднее время на игру':<30} {avg_old:.2f}с{'':<15} {avg_sql:.2f}с")
        self.stdout.write(f"{'Всего уникальных игр найдено':<30} {len(old_total_ids):<20} {len(sql_total_ids)}")

        if old_elapsed > 0 and sql_elapsed > 0:
            speedup = old_elapsed / sql_elapsed
            self.stdout.write(f"{'Ускорение':<30} {'':<20} {speedup:.1f}x")

        self.stdout.write("\n" + "=" * 70)

    def handle(self, *args, **options):
        game_ids = options.get('game_id')
        limit = options.get('limit', 12)
        min_similarity = options.get('min_similarity', 40)
        mass_test = options.get('mass_test', False)
        count = options.get('count', 100)

        if mass_test:
            self.test_mass_update_performance(count, limit, min_similarity)
            return

        if not game_ids:
            self.stdout.write(self.style.ERROR("❌ Укажите --Movie-id для сравнения"))
            return

        self.stdout.write(self.style.SUCCESS('\n' + '=' * 70))
        self.stdout.write(self.style.SUCCESS('🔬 СРАВНЕНИЕ АЛГОРИТМОВ ПОХОЖЕСТИ'))
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write(f"🎮 Игры: {game_ids}")
        self.stdout.write(f"📊 Лимит: {limit}")
        self.stdout.write(f"📊 Мин. схожесть: {min_similarity}%")
        self.stdout.write('=' * 70)

        all_old_results = []
        all_sql_results = []
        old_total_time = 0
        sql_total_time = 0

        for game_id in game_ids:
            try:
                Movie = Movie.objects.get(id=game_id)
                self.stdout.write(f"\n✅ Игра: {Movie.name} (ID: {Movie.id})")
            except Movie.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"❌ Игра с ID {game_id} не найдена"))
                continue

            # Старый алгоритм
            old_results, old_time = self.get_old_algorithm_results(game_id, limit, min_similarity)
            old_total_time += old_time

            # SQL алгоритм
            sql_results, sql_time = self.get_raw_sql_optimized_results(game_id, limit, min_similarity)
            sql_total_time += sql_time

            all_old_results.append((Movie.name, old_results, old_time))
            all_sql_results.append((Movie.name, sql_results, sql_time))

            # Сравнение для этой игры
            self.stdout.write(f"\n📊 Сравнение для {Movie.name}:")
            self.stdout.write(f"   Старый: {len(old_results)} игр за {self.format_time(old_time)}")
            self.stdout.write(f"   SQL:    {len(sql_results)} игр за {self.format_time(sql_time)}")

            if old_time > 0 and sql_time > 0:
                speedup = old_time / sql_time
                self.stdout.write(f"   ⚡ Ускорение: {speedup:.1f}x")

            # Показываем первые 5 результатов
            self.stdout.write("\n   Топ-5 похожих игр:")
            self.stdout.write(f"   {'#':<4} {'Старый':<30} {'%':>8} {'SQL':<30} {'%':>8}")
            self.stdout.write("   " + "-" * 80)

            old_dict = {item['id']: item for item in old_results}
            sql_dict = {item['id']: item for item in sql_results}
            all_ids = list(set(old_dict.keys()) | set(sql_dict.keys()))[:5]

            for i, game_id_result in enumerate(all_ids, 1):
                old_item = old_dict.get(game_id_result)
                sql_item = sql_dict.get(game_id_result)

                old_name = old_item['name'] if old_item else "—"
                old_sim = old_item['similarity'] if old_item else 0
                sql_name = sql_item['name'] if sql_item else "—"
                sql_sim = sql_item['similarity'] if sql_item else 0

                match = "✅" if old_item and sql_item and abs(old_sim - sql_sim) < 0.5 else "⚠️"
                self.stdout.write(
                    f"   {i:<4} {old_name[:28]:<30} {old_sim:>7.1f}%  {sql_name[:28]:<30} {sql_sim:>7.1f}% {match}")

        # Общая статистика
        self.stdout.write(self.style.SUCCESS('\n' + '=' * 70))
        self.stdout.write(self.style.SUCCESS('📊 ОБЩАЯ СТАТИСТИКА'))
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write(f"   Всего игр обработано: {len(game_ids)}")
        self.stdout.write(f"   Старый алгоритм: {self.format_time(old_total_time)}")
        self.stdout.write(f"   SQL алгоритм:    {self.format_time(sql_total_time)}")

        if old_total_time > 0 and sql_total_time > 0:
            speedup = old_total_time / sql_total_time
            self.stdout.write(f"   ⚡ Общее ускорение: {speedup:.1f}x")

        self.stdout.write(self.style.SUCCESS('=' * 70))