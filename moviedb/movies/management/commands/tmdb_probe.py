"""Django management command to probe TMDB API and print raw JSON.

Usage:
    python manage.py tmdb_probe
    python manage.py tmdb_probe --movie-id 11
    python manage.py tmdb_probe --movie-id 11 --append credits,videos,keywords
"""

import json

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

TMDB_BASE_URL = "https://api.themoviedb.org/3"
DEFAULT_APPEND = "credits,videos,recommendations,similar,keywords,release_dates"


class Command(BaseCommand):
    help = "Fetch a movie from TMDB API and print the raw JSON response."

    def add_arguments(self, parser):
        parser.add_argument(
            "--movie-id",
            type=int,
            default=11,
            help="TMDB movie ID to fetch (default: 11 — Star Wars).",
        )
        parser.add_argument(
            "--append",
            type=str,
            default=DEFAULT_APPEND,
            help=(
                "Comma-separated list of append_to_response blocks "
                f"(default: {DEFAULT_APPEND})."
            ),
        )
        parser.add_argument(
            "--language",
            type=str,
            default="en-US",
            help="Language for TMDB response (default: en-US).",
        )

    def handle(self, *args, **options):
        token = getattr(settings, "TMDB_API_READ_ACCESS_TOKEN", None)
        if not token:
            raise CommandError(
                "TMDB_API_READ_ACCESS_TOKEN is not set in settings/.env. "
                "Add it and retry."
            )

        movie_id = options["movie_id"]
        append = options["append"]
        language = options["language"]

        url = f"{TMDB_BASE_URL}/movie/{movie_id}"
        params = {
            "language": language,
            "append_to_response": append,
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        self.stdout.write(self.style.NOTICE(f"GET {url}"))
        self.stdout.write(self.style.NOTICE(f"append_to_response = {append}"))
        self.stdout.write(self.style.NOTICE(f"language = {language}"))
        self.stdout.write("")

        try:
            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=30,
            )
        except requests.exceptions.Timeout:
            raise CommandError("TMDB request timed out after 30 seconds.")
        except requests.exceptions.ConnectionError as exc:
            raise CommandError(f"TMDB connection error: {exc}")

        self.stdout.write(
            self.style.NOTICE(f"HTTP {response.status_code} {response.reason}")
        )

        if response.status_code != 200:
            self.stdout.write(self.style.ERROR("Response body:"))
            self.stdout.write(response.text)
            raise CommandError(
                f"TMDB returned non-200 status: {response.status_code}"
            )

        try:
            data = response.json()
        except ValueError:
            raise CommandError("TMDB response is not valid JSON.")

        pretty = json.dumps(data, indent=2, ensure_ascii=False)
        self.stdout.write(self.style.SUCCESS("=== TMDB response JSON ==="))
        self.stdout.write(pretty)

        # Краткая сводка по ключевым блокам — чтобы сразу видеть структуру
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== Summary ==="))
        self.stdout.write(f"id:               {data.get('id')}")
        self.stdout.write(f"title:            {data.get('title')}")
        self.stdout.write(f"original_title:   {data.get('original_title')}")
        self.stdout.write(f"release_date:     {data.get('release_date')}")
        self.stdout.write(f"runtime:          {data.get('runtime')}")
        self.stdout.write(f"vote_average:     {data.get('vote_average')}")
        self.stdout.write(f"vote_count:       {data.get('vote_count')}")
        self.stdout.write(f"genres:           {len(data.get('genres') or [])}")
        self.stdout.write(f"production_companies: {len(data.get('production_companies') or [])}")
        self.stdout.write(f"production_countries: {len(data.get('production_countries') or [])}")
        self.stdout.write(f"spoken_languages: {len(data.get('spoken_languages') or [])}")

        for block in append.split(","):
            block = block.strip()
            if not block:
                continue
            value = data.get(block)
            if isinstance(value, dict):
                inner = value.get("cast") or value.get("crew") or value.get("results")
                if inner is not None:
                    self.stdout.write(f"{block}.results/cast/crew: {len(inner)}")
                else:
                    self.stdout.write(f"{block}: keys={list(value.keys())}")
            elif isinstance(value, list):
                self.stdout.write(f"{block}: {len(value)} items")
            else:
                self.stdout.write(f"{block}: {type(value).__name__}")