import os
import time
import threading
import csv
from typing import List, Dict, Set


class FailedmoviesLogger:
    """Логгер для неудачных игр с чтением/записью"""

    def __init__(self, filename: str = "failed_wiki_movies.csv"):  # Изменено
        self.filename = filename
        self.failed_movies = []
        self.failed_ids = set()
        self.lock = threading.Lock()

        # Упрощаем создание директории
        directory = os.path.dirname(self.filename)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        elif not directory:  # Если путь без директории (просто имя файла)
            # Файл будет создан в текущей директории
            pass

        # Загружаем существующие ошибки
        self._load_existing_failures()

    def _initialize_file(self):
        """Инициализировать файл"""
        try:
            with open(self.filename, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['ID', 'Название игры', 'Время ошибки', 'Причина неудачи'])
        except Exception as e:
            print(f"❌ Ошибка создания файла {self.filename}: {e}")

    def remove_movies_by_ids(self, game_ids: Set[int]):
        """Удалить игры по ID из файла ошибок"""
        if not game_ids:
            return

        with self.lock:
            # Фильтруем игры
            new_failed_movies = [
                Movie for Movie in self.failed_movies
                if Movie['id'] not in game_ids
            ]

            removed_count = len(self.failed_movies) - len(new_failed_movies)

            if removed_count > 0:
                # Обновляем внутренние структуры
                self.failed_movies = new_failed_movies
                self.failed_ids = {Movie['id'] for Movie in new_failed_movies}

                # Перезаписываем файл
                try:
                    with open(self.filename, 'w', encoding='utf-8', newline='') as f:
                        writer = csv.writer(f)
                        writer.writerow(['ID', 'Название игры', 'Время ошибки', 'Причина неудачи'])

                        for Movie in new_failed_movies:
                            safe_name = Movie['name'].replace(',', ';')
                            safe_reason = Movie.get('reason', '').replace(',', ';').replace('\n', ' ')
                            writer.writerow([
                                Movie['id'],
                                safe_name,
                                Movie.get('timestamp', ''),
                                safe_reason
                            ])

                    print(f"✅ Удалено {removed_count} игр из файла ошибок")
                except Exception as e:
                    print(f"❌ Ошибка обновления файла ошибок: {e}")

    def get_failed_ids_from_file(self) -> Set[int]:
        """Загрузить ID неудачных игр только из файла (без загрузки в память)"""
        failed_ids = set()

        if not os.path.exists(self.filename):
            return failed_ids

        try:
            with open(self.filename, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader, None)  # Пропускаем заголовок

                for row in reader:
                    if len(row) >= 1:  # Хотя бы ID
                        try:
                            game_id = int(row[0])
                            failed_ids.add(game_id)
                        except ValueError:
                            continue

            # Добавляем вывод для отладки
            if failed_ids:
                print(f"📋 Загружено {len(failed_ids)} ID из файла {self.filename}")

        except Exception as e:
            print(f"⚠️  Ошибка чтения файла ошибок: {e}")

        return failed_ids

    def reload_failed_ids(self):
        """Перезагрузить ID неудачных игр из файла"""
        with self.lock:
            self.failed_ids = self.get_failed_ids_from_file()

    def _load_existing_failures(self):
        """Загрузить существующие неудачные игры из файла"""
        if not os.path.exists(self.filename):
            # Создаем файл с заголовками
            self._initialize_file()
            return

        try:
            with open(self.filename, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader, None)  # Пропускаем заголовок

                for row in reader:
                    if len(row) >= 2:  # ID и название
                        try:
                            game_id = int(row[0])
                            self.failed_ids.add(game_id)
                            self.failed_movies.append({
                                'id': game_id,
                                'name': row[1] if len(row) > 1 else 'Unknown',
                                'timestamp': row[2] if len(row) > 2 else '',
                                'reason': row[3] if len(row) > 3 else ''
                            })
                        except ValueError:
                            continue
        except Exception as e:
            print(f"⚠️  Ошибка загрузки файла ошибок: {e}")
            self._initialize_file()

    def is_failed(self, game_id: int) -> bool:
        """Проверить, была ли игра уже неудачной"""
        return game_id in self.failed_ids

    def add_failed_game(self, game_id: int, game_name: str, reason: str):
        """Добавить неудачную игру"""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        game_info = {
            'id': game_id,
            'name': game_name,
            'timestamp': timestamp,
            'reason': reason
        }

        with self.lock:
            # Добавляем только если ещё нет
            if game_id not in self.failed_ids:
                self.failed_ids.add(game_id)
                self.failed_movies.append(game_info)

                # Записываем в файл
                try:
                    with open(self.filename, 'a', encoding='utf-8', newline='') as f:
                        writer = csv.writer(f)
                        safe_name = game_name.replace(',', ';')
                        safe_reason = reason.replace(',', ';').replace('\n', ' ')
                        writer.writerow([game_id, safe_name, timestamp, safe_reason])
                except Exception as e:
                    print(f"❌ Ошибка записи в файл: {e}")

    def get_count(self) -> int:
        """Получить количество неудачных игр"""
        return len(self.failed_ids)

    def get_filename(self) -> str:
        """Получить имя файла"""
        return self.filename

    def get_failed_movies(self) -> List[Dict]:
        """Получить список неудачных игр"""
        with self.lock:
            return self.failed_movies.copy()

    def get_failed_ids(self) -> Set[int]:
        """Получить множество ID неудачных игр"""
        with self.lock:
            return self.failed_ids.copy()

    def clear_failures(self):
        """Очистить список неудачных игр"""
        with self.lock:
            self.failed_ids.clear()
            self.failed_movies.clear()
            self._initialize_file()

    def load_failed_movies_for_retry(self, check_database: bool = True) -> List[Dict]:
        """Загрузить неудачные игры для повторной попытки с проверкой базы"""
        movies_for_retry = []

        for game_info in self.failed_movies:
            game_id = game_info['id']

            if check_database:
                try:
                    # Проверяем, есть ли уже описание в базе
                    from movies.models import Movie
                    Movie = Movie.objects.get(id=game_id)
                    if Movie.wiki_description:
                        # Пропускаем - уже есть описание
                        continue
                except Movie.DoesNotExist:
                    # Игры нет в базе - странно, но пропускаем
                    continue
                except Exception:
                    # В случае ошибки все равно пытаемся обработать
                    pass

            movies_for_retry.append({
                'id': game_id,
                'name': game_info['name']
            })

        return movies_for_retry
