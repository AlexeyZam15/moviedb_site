<div align="center">

# 🎬 MovieDB – Поиск фильмов и сериалов

**Каталог фильмов и сериалов на данных TMDB**

[![Русский](https://img.shields.io/badge/Язык-Русский-blue)](README.ru.md)
[![English](https://img.shields.io/badge/Language-English-red)](README.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub](https://img.shields.io/badge/GitHub-moviedb__site-181717)](https://github.com/AlexeyZam15/moviedb_site)
[![Discord](https://img.shields.io/badge/Discord-Присоединиться-7289da)](https://discord.gg/PMZsfrCnre)

</div>

---

## 📌 Статус проекта

**Только исходный код.** Публичного сайта и десктоп-сборки пока нет — проект в активной разработке. Этот README описывает текущий код и способ запуска локально.

---

## 🎯 Как это работает

MovieDB — веб-приложение на Django для поиска фильмов и сериалов. Источник данных — **TMDB**: названия, жанры, ключевые слова, темы, рейтинги и другие метаданные.

Идея простая: вы знаете, что вам нравится, и хотите найти, что посмотреть дальше.

1. **Найдите** фильм или сериал через поиск или каталог
2. **Откройте карточку** с описанием и метаданными
3. **Получите похожие тайтлы**, ранжированные по жанрам, ключевым словам, темам и другим атрибутам TMDB
4. **Сравните** два тайтла бок о бок

---

## 🔍 Возможности

- **Каталог фильмов и сериалов** на данных TMDB
- **Поиск** по названиям с фильтрами
- **Похожие тайтлы** на основе жанров, ключевых слов, тем и других метаданных
- **Продвинутые фильтры** — жанр, тема, ключевое слово, год выхода, рейтинг и другое
- **Сравнение двух тайтлов** бок о бок
- **Подробные страницы** с описанием, слоганом, рейтингами и метаданными
- **Кэширование** карточек и счётчиков (Redis в production, LocMemCache как fallback)
- **Django admin** для управления контентом
- **Форма обратной связи**

---

## 🛠️ Технологии

- **Backend:** Django 5.2, Python 3.11
- **База данных:** PostgreSQL (`psycopg2-binary`, `dj-database-url`)
- **Источник данных:** TMDB API (`TMDB_API_KEY`, `TMDB_API_READ_ACCESS_TOKEN`)
- **Frontend:** Bootstrap 5, Vanilla JavaScript
- **Кэш:** Redis через `django_redis` (опционально; fallback — LocMemCache)
- **Статика:** WhiteNoise
- **WSGI-сервер:** Gunicorn
- **Контейнеризация:** Docker (`Dockerfile`, `start.sh`, `railway.json`)
- **Анализ текста:** NLTK, joblib

---

## 🚀 Быстрый старт (локально)

### 1. Клонировать репозиторий

```bash
git clone https://github.com/AlexeyZam15/moviedb_site.git
cd moviedb_site
```

### 2. Создать виртуальное окружение

```bash
python -m venv venv
```

Windows:

```powershell
venv\Scripts\activate
```

Linux/macOS:

```bash
source venv/bin/activate
```

### 3. Установить зависимости

```bash
pip install -r requirements-base.txt
```

### 4. Настроить окружение

Создайте файл `.env` в корне проекта и заполните переменные (см. раздел ниже). Минимально нужно:

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG=True`
- `TMDB_API_KEY`
- `TMDB_API_READ_ACCESS_TOKEN`
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`

### 5. Применить миграции

```bash
python manage.py migrate
```

### 6. Запустить сервер разработки

```bash
python manage.py runserver
```

Откройте **http://127.0.0.1:8000**.

---

## 📥 Загрузка данных из TMDB

Данные TMDB загружаются management-командами в `movies/management/commands/`:

- `load_tmdb` — пайплайн загрузки из TMDB (API-клиент, сборщик, загрузчик, offset-менеджер, кэш)
- `load_movies` — загрузка фильмов и сериалов из TMDB
- `full_pipeline` — сквозной пайплайн обработки

Запуск команды:

```bash
python manage.py <имя_команды>
```

Посмотреть доступные опции:

```bash
python manage.py <имя_команды> --help
```

Перед загрузкой нужен действующий `TMDB_API_KEY` / `TMDB_API_READ_ACCESS_TOKEN` в `.env`.

---

## ⚙️ Переменные окружения

Конфигурация читается из `.env` (через `python-dotenv`). Имена переменных, которые использует код:

| Переменная | Назначение |
|------------|------------|
| `DJANGO_SECRET_KEY` | Секретный ключ Django |
| `DJANGO_DEBUG` | `True` / `False` |
| `ALLOWED_HOSTS` | Разрешённые хосты через запятую |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | Подключение к PostgreSQL |
| `DATABASE_URL` | Опциональный полный URL БД (Railway, внешний PostgreSQL) |
| `TMDB_API_KEY` | API-ключ TMDB |
| `TMDB_API_READ_ACCESS_TOKEN` | Read access token TMDB |
| `EMAIL_HOST_PASSWORD` | Пароль SMTP для формы обратной связи |
| `INDEXNOW_KEY` | Ключ IndexNow для поисковых систем |
| `VPS_HOST`, `VPS_USER`, `VPS_PATH`, `SSH_PASSWORD` | Хелперы для деплоя на VPS |

---

## 🌐 Развёртывание

В репозитории есть Docker-путь развёртывания:

- `Dockerfile` — образ на Python 3.11 slim с зависимостями
- `start.sh` — применяет миграции и запускает Gunicorn
- `railway.json` — билдер и start-команда для Railway

Контейнеру нужен доступный PostgreSQL и корректный `DATABASE_URL` (или переменные `DB_*`). Redis опционален: если он
недоступен, приложение переходит на Django LocMemCache.

**Важно:** живого деплоя пока нет — эти файлы описывают, как проект можно развернуть, а не работающий сервис.

---

## 🐛 Отладка

- `DJANGO_DEBUG=True` включает Django Debug Toolbar на localhost
- Медленные запросы логируются кастомными middleware (`SlowRequestLoggerMiddleware`, `TimingMiddleware`)
- Логи Django пишутся в `logs/django.log`, медленные SQL — в `logs/slow_sql.log`

---

## 🤝 Вклад в проект

1. Форкните репозиторий
2. Создайте ветку для новой функции (`git checkout -b feature/amazing-feature`)
3. Закоммитьте изменения (`git commit -m 'Add amazing feature'`)
4. Запушьте ветку (`git push origin feature/amazing-feature`)
5. Откройте Pull Request

---

## 📄 Лицензия

Проект распространяется под лицензией MIT. Свободное использование, модификация и распространение с указанием авторства.

---

## 🙏 Благодарности

- **Django** — веб-фреймворк
- **PostgreSQL** — база данных
- **TMDB API** — источник данных о фильмах и сериалах
- **Bootstrap 5** — фронтенд
- **Redis / django_redis** — опциональный кэш
- **WhiteNoise** — статика
- **Gunicorn** — WSGI-сервер

*MovieDB использует TMDB API, но не аффилирован с TMDB и не одобрен ими.*

---

## 💝 Поддержать проект

Если MovieDB вам полезен, вы можете поддержать развитие проекта:

➡️ **[Поддержать автора](https://dalink.to/wolfgunt)**

Спасибо за вашу поддержку! ❤️

---

## 📬 Контакты

- **Email:** gamespeek@mail.ru
- **Discord:** [Присоединиться к серверу](https://discord.gg/PMZsfrCnre)
- **GitHub:** [AlexeyZam15/moviedb_site](https://github.com/AlexeyZam15/moviedb_site)

---
