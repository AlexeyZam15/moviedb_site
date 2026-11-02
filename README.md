<div align="center">

# 🎬 MovieDB – Movies & TV Series Discovery

**Explore movies and TV shows powered by TMDB metadata**

[![English](https://img.shields.io/badge/Language-English-red)](README.md)
[![Русский](https://img.shields.io/badge/Language-Russian-blue)](README.ru.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub](https://img.shields.io/badge/GitHub-moviedb__site-181717)](https://github.com/AlexeyZam15/moviedb_site)
[![Discord](https://img.shields.io/badge/Discord-Join-7289da)](https://discord.gg/PMZsfrCnre)

</div>

---

## 📌 Project Status

**Source code only.** There is no public website and no desktop build yet — the project is under active development. This README describes the current codebase and how to run it locally.

---

## 🎯 Core Concept

MovieDB is a Django web application for discovering movies and TV series. It uses **TMDB** as the data source for titles, genres, keywords, themes, ratings, and related metadata.

The idea is simple: you know what you like, and you want to find something similar to watch next.

1. **Browse or search** for a movie or TV series
2. **Open its card** to see details and metadata
3. **Get similar titles** ranked by similarity of genres, keywords, themes, and other TMDB attributes
4. **Compare** two titles side by side

---

## 🔍 Features

- **Movies and TV series** catalog backed by TMDB data
- **Search** across titles with filters
- **Similar titles** based on genres, keywords, themes, and other metadata
- **Advanced filters** — genre, theme, keyword, release year, rating, and more
- **Side-by-side comparison** of two titles
- **Detailed title pages** with summary, tagline, ratings, and metadata
- **Caching layer** for title cards and counts (Redis in production, LocMemCache as fallback)
- **Django admin** for content management
- **Feedback form** for user messages

---

## 🛠️ Technology Stack

- **Backend:** Django 5.2, Python 3.11
- **Database:** PostgreSQL (`psycopg2-binary`, `dj-database-url`)
- **Data source:** TMDB API (`TMDB_API_KEY`, `TMDB_API_READ_ACCESS_TOKEN`)
- **Frontend:** Bootstrap 5, Vanilla JavaScript
- **Caching:** Redis via `django_redis` (optional; LocMemCache fallback)
- **Static files:** WhiteNoise
- **WSGI server:** Gunicorn
- **Container:** Docker (`Dockerfile`, `start.sh`, `railway.json`)
- **Text analysis:** NLTK, joblib

---

## 🚀 Quick Start (Local Development)

### 1. Clone the repository

```bash
git clone https://github.com/AlexeyZam15/moviedb_site.git
cd moviedb_site
```

### 2. Create a virtual environment

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

### 3. Install dependencies

```bash
pip install -r requirements-base.txt
```

### 4. Configure environment

Create a `.env` file in the project root and fill in the variables (see the section below). At minimum you need:

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG=True`
- `TMDB_API_KEY`
- `TMDB_API_READ_ACCESS_TOKEN`
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`

### 5. Apply migrations

```bash
python manage.py migrate
```

### 6. Run the development server

```bash
python manage.py runserver
```

Then open **http://127.0.0.1:8000**.

---

## 📥 Loading Data from TMDB

TMDB data is loaded through management commands located in `movies/management/commands/`:

- `load_tmdb` — TMDB loading pipeline (API client, collector, loader, offset manager, cache)
- `load_movies` — loads movies and TV series from TMDB
- `full_pipeline` — end-to-end processing pipeline

Run a command with:

```bash
python manage.py <command_name>
```

Check the available options with:

```bash
python manage.py <command_name> --help
```

You need a valid `TMDB_API_KEY` / `TMDB_API_READ_ACCESS_TOKEN` in `.env` before loading data.

---

## ⚙️ Environment Variables

The project reads configuration from `.env` (via `python-dotenv`). Variable names used by the code:

| Variable | Purpose |
|----------|---------|
| `DJANGO_SECRET_KEY` | Django secret key |
| `DJANGO_DEBUG` | `True` / `False` |
| `ALLOWED_HOSTS` | Comma-separated allowed hosts |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | PostgreSQL connection |
| `DATABASE_URL` | Optional full DB URL (Railway, external PostgreSQL) |
| `TMDB_API_KEY` | TMDB API key |
| `TMDB_API_READ_ACCESS_TOKEN` | TMDB read access token |
| `EMAIL_HOST_PASSWORD` | SMTP password for the feedback form |
| `INDEXNOW_KEY` | IndexNow key for search engines |
| `VPS_HOST`, `VPS_USER`, `VPS_PATH`, `SSH_PASSWORD` | VPS deployment helpers |

---

## 🌐 Deployment

The repository includes a Docker-based deployment path:

- `Dockerfile` — Python 3.11 slim image with dependencies
- `start.sh` — runs migrations and starts Gunicorn
- `railway.json` — Railway builder and start command

The container expects a reachable PostgreSQL instance and a valid `DATABASE_URL` (or `DB_*` variables). Redis is
optional: if it is unavailable, the application falls back to Django LocMemCache.

**Note:** a live deployment is not provided yet — these files describe how the project can be deployed, not a running
service.

---

## 🐛 Debugging

- `DJANGO_DEBUG=True` enables Django Debug Toolbar on localhost
- Slow requests are logged by custom middleware (`SlowRequestLoggerMiddleware`, `TimingMiddleware`)
- Django logs are written to `logs/django.log`, slow SQL to `logs/slow_sql.log`

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License. Free to use, modify, and distribute with attribution.

---

## 🙏 Attribution

- **Django** — web framework
- **PostgreSQL** — database
- **TMDB API** — movie and TV series data source
- **Bootstrap 5** — frontend
- **Redis / django_redis** — optional caching
- **WhiteNoise** — static files
- **Gunicorn** — WSGI server

*MovieDB uses the TMDB API but is not endorsed or certified by TMDB.*

---

## 💝 Support the Project

If MovieDB is useful to you, consider supporting development:

➡️ **[Support the author](https://dalink.to/wolfgunt)**

Thank you for your support! ❤️

---

## 📬 Contact

- **Email:** gamespeek@mail.ru
- **Discord:** [Join our server](https://discord.gg/PMZsfrCnre)
- **GitHub:** [AlexeyZam15/moviedb_site](https://github.com/AlexeyZam15/moviedb_site)

---
