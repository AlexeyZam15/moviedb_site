# movies/load_tmdb/loader.py
"""
Маппинг TMDB -> Django-модели.

- Movie: tmdb_id, imdb_id, name<-title, original_title, summary<-overview,
  tagline, homepage, original_language, status, adult, first_release_date<-release_date,
  runtime, budget, revenue, popularity, rating<-vote_average, rating_count<-vote_count,
  cover_url<-poster_path, backdrop_url<-backdrop_path, poster_path, backdrop_path.
- Collection <- belongs_to_collection (upsert по tmdb_id).
- Genre <- genres (upsert по tmdb_id).
- Keyword <- keywords.keywords (upsert по tmdb_id).
- Company <- production_companies (upsert по tmdb_id).
- MovieRecommendation <- recommendations.results (source=Movie, target=Movie).
- Image/Video <- images/videos (если есть в ответе; по умолчанию append их не запрашивает).
- Series = None (в TMDB-movie нет Series).
- Theme — не заполняем (в TMDB-movie нет тем).

bulk_create/bulk_update + through.bulk_create + update_materialized_vectors.
"""

import time
from datetime import datetime, date
from typing import Optional, Dict, Any, List, Tuple

from django.db import transaction
from django.utils import timezone

from movies.models import (
    Movie, Genre, Keyword, Company, Collection, MovieRecommendation,
    Image, Video,
)
from .tmdb_api import build_image_url


class TmdbLoader:
    """Маппинг TMDB -> Django-модели и сохранение."""

    def __init__(self, stdout, stderr, debug: bool = False):
        self.stdout = stdout
        self.stderr = stderr
        self.debug = debug

    # ------------------------------------------------------------------ #
    #  Парсинг
    # ------------------------------------------------------------------ #

    def _parse_release_date(self, s: Optional[str]) -> Optional[datetime]:
        if not s:
            return None
        try:
            d = datetime.strptime(s, '%Y-%m-%d')
        except (ValueError, TypeError):
            return None
        try:
            if timezone.is_naive(d):
                d = timezone.make_aware(d)
        except Exception:
            pass
        return d

    # ------------------------------------------------------------------ #
    #  Upsert справочников
    # ------------------------------------------------------------------ #

    def _upsert_genres(self, genres_data: List[Dict[str, Any]]) -> Dict[int, Genre]:
        if not genres_data:
            return {}
        by_tmdb = {}
        for g in genres_data:
            tid = g.get('id')
            name = g.get('name')
            if tid and name:
                by_tmdb[int(tid)] = name
        if not by_tmdb:
            return {}
        Genre.objects.bulk_create(
            [Genre(tmdb_id=tid, name=name) for tid, name in by_tmdb.items()],
            ignore_conflicts=True,
            batch_size=500,
        )
        return {g.tmdb_id: g for g in Genre.objects.filter(tmdb_id__in=list(by_tmdb.keys()))}

    def _upsert_keywords(self, keywords_data: List[Dict[str, Any]]) -> Dict[int, Keyword]:
        if not keywords_data:
            return {}
        by_tmdb = {}
        for k in keywords_data:
            tid = k.get('id')
            name = k.get('name')
            if tid and name:
                by_tmdb[int(tid)] = name
        if not by_tmdb:
            return {}
        Keyword.objects.bulk_create(
            [Keyword(tmdb_id=tid, name=name) for tid, name in by_tmdb.items()],
            ignore_conflicts=True,
            batch_size=500,
        )
        return {k.tmdb_id: k for k in Keyword.objects.filter(tmdb_id__in=list(by_tmdb.keys()))}

    def _upsert_companies(self, companies_data: List[Dict[str, Any]]) -> Dict[int, Company]:
        if not companies_data:
            return {}
        by_tmdb = {}
        for c in companies_data:
            tid = c.get('id')
            name = c.get('name')
            if tid and name:
                by_tmdb[int(tid)] = {
                    'name': name,
                    'logo_path': c.get('logo_path'),
                    'origin_country': c.get('origin_country'),
                }
        if not by_tmdb:
            return {}
        Company.objects.bulk_create(
            [
                Company(
                    tmdb_id=tid,
                    name=v['name'],
                    logo_path=v['logo_path'],
                    origin_country=v['origin_country'],
                )
                for tid, v in by_tmdb.items()
            ],
            ignore_conflicts=True,
            batch_size=500,
        )
        return {c.tmdb_id: c for c in Company.objects.filter(tmdb_id__in=list(by_tmdb.keys()))}

    def _upsert_collection(self, collection_data: Optional[Dict[str, Any]]) -> Optional[Collection]:
        if not collection_data:
            return None
        tid = collection_data.get('id')
        name = collection_data.get('name')
        if not tid or not name:
            return None
        tid = int(tid)
        Collection.objects.bulk_create(
            [
                Collection(
                    tmdb_id=tid,
                    name=name,
                    overview=collection_data.get('overview'),
                    poster_path=collection_data.get('poster_path'),
                    backdrop_path=collection_data.get('backdrop_path'),
                )
            ],
            ignore_conflicts=True,
        )
        return Collection.objects.filter(tmdb_id=tid).first()

    # ------------------------------------------------------------------ #
    #  Movie
    # ------------------------------------------------------------------ #

    def movie_from_tmdb(
            self,
            data: Dict[str, Any],
            collection: Optional[Collection] = None,
    ) -> Optional[Movie]:
        """Собирает Movie (без сохранения, без M2M)."""
        tid = data.get('id')
        if not tid:
            return None
        name = data.get('title') or data.get('original_title') or f'Movie {tid}'
        return Movie(
            tmdb_id=int(tid),
            imdb_id=data.get('imdb_id'),
            name=name,
            original_title=data.get('original_title'),
            summary=data.get('overview'),
            tagline=data.get('tagline'),
            homepage=data.get('homepage'),
            original_language=data.get('original_language'),
            status=data.get('status'),
            adult=bool(data.get('adult', False)),
            first_release_date=self._parse_release_date(data.get('release_date')),
            runtime=data.get('runtime'),
            budget=data.get('budget'),
            revenue=data.get('revenue'),
            popularity=data.get('popularity'),
            rating=data.get('vote_average'),
            rating_count=int(data.get('vote_count') or 0),
            cover_url=build_image_url(data.get('poster_path'), 'w500'),
            backdrop_url=build_image_url(data.get('backdrop_path'), 'w780'),
            poster_path=data.get('poster_path'),
            backdrop_path=data.get('backdrop_path'),
            collection=collection,
            series=None,
        )

    def save_movies(
            self,
            movies_data_list: List[Dict[str, Any]],
            overwrite: bool = False,
    ) -> Tuple[int, int, int, Dict[int, Movie]]:
        """
        Сохраняет фильмы батчем.

        Возвращает (created, updated, skipped, movie_map{tmdb_id: Movie}).
        movie_map содержит ВСЕ фильмы из movies_data_list (и новые, и существующие).
        """
        if not movies_data_list:
            return 0, 0, 0, {}

        # 1. Собрать уникальные справочники
        all_genres: List[Dict[str, Any]] = []
        all_keywords: List[Dict[str, Any]] = []
        all_companies: List[Dict[str, Any]] = []
        collections_data: Dict[int, Dict[str, Any]] = {}

        for data in movies_data_list:
            for g in (data.get('genres') or []):
                all_genres.append(g)
            kw_block = data.get('keywords') or {}
            for k in (kw_block.get('keywords') or []):
                all_keywords.append(k)
            for c in (data.get('production_companies') or []):
                all_companies.append(c)
            coll = data.get('belongs_to_collection')
            if coll and coll.get('id'):
                collections_data[int(coll['id'])] = coll

        # 2. Upsert справочники
        genre_map = self._upsert_genres(all_genres)
        keyword_map = self._upsert_keywords(all_keywords)
        company_map = self._upsert_companies(all_companies)
        collection_map: Dict[int, Collection] = {}
        for cid, cdata in collections_data.items():
            coll_obj = self._upsert_collection(cdata)
            if coll_obj:
                collection_map[cid] = coll_obj

        # 3. Существующие Movie по tmdb_id
        tmdb_ids = [int(d['id']) for d in movies_data_list if d.get('id')]
        existing = {m.tmdb_id: m for m in Movie.objects.filter(tmdb_id__in=tmdb_ids)}

        if overwrite:
            # Удаляем существующие (каскадно рекомендации и т.д.)
            Movie.objects.filter(tmdb_id__in=tmdb_ids).delete()
            existing = {}

        # 4. Собрать Movie-объекты
        to_create: List[Movie] = []
        to_update: List[Movie] = []
        for data in movies_data_list:
            tid = data.get('id')
            if not tid:
                continue
            tid = int(tid)
            coll_id = None
            coll = data.get('belongs_to_collection')
            if coll and coll.get('id') and int(coll['id']) in collection_map:
                coll_id = collection_map[int(coll['id'])].id

            if tid in existing:
                m = existing[tid]
                # обновляем поля
                m.imdb_id = data.get('imdb_id') or m.imdb_id
                m.name = data.get('title') or m.name
                m.original_title = data.get('original_title') or m.original_title
                m.summary = data.get('overview') or m.summary
                m.tagline = data.get('tagline') or m.tagline
                m.homepage = data.get('homepage') or m.homepage
                m.original_language = data.get('original_language') or m.original_language
                m.status = data.get('status') or m.status
                m.adult = bool(data.get('adult', m.adult))
                rd = self._parse_release_date(data.get('release_date'))
                if rd:
                    m.first_release_date = rd
                if data.get('runtime') is not None:
                    m.runtime = data.get('runtime')
                if data.get('budget') is not None:
                    m.budget = data.get('budget')
                if data.get('revenue') is not None:
                    m.revenue = data.get('revenue')
                if data.get('popularity') is not None:
                    m.popularity = data.get('popularity')
                if data.get('vote_average') is not None:
                    m.rating = data.get('vote_average')
                if data.get('vote_count') is not None:
                    m.rating_count = int(data.get('vote_count') or 0)
                m.cover_url = build_image_url(data.get('poster_path'), 'w500') or m.cover_url
                m.backdrop_url = build_image_url(data.get('backdrop_path'), 'w780') or m.backdrop_url
                m.poster_path = data.get('poster_path') or m.poster_path
                m.backdrop_path = data.get('backdrop_path') or m.backdrop_path
                if coll_id:
                    m.collection_id = coll_id
                to_update.append(m)
            else:
                m = self.movie_from_tmdb(data, collection=collection_map.get(int(coll['id'])) if coll and coll.get(
                    'id') else None)
                if m:
                    to_create.append(m)

        # 5. bulk_create / bulk_update
        created = 0
        updated = 0
        if to_create:
            try:
                with transaction.atomic():
                    Movie.objects.bulk_create(to_create, ignore_conflicts=True, batch_size=200)
                created = len(to_create)
            except Exception as e:
                self.stderr.write(f"   ❌ bulk_create Movie: {e}\n")
                self.stderr.flush()
                # fallback: по одному
                for m in to_create:
                    try:
                        m.save()
                        created += 1
                    except Exception:
                        pass

        if to_update:
            try:
                with transaction.atomic():
                    Movie.objects.bulk_update(
                        to_update,
                        fields=[
                            'imdb_id', 'name', 'original_title', 'summary', 'tagline',
                            'homepage', 'original_language', 'status', 'adult',
                            'first_release_date', 'runtime', 'budget', 'revenue',
                            'popularity', 'rating', 'rating_count',
                            'cover_url', 'backdrop_url', 'poster_path', 'backdrop_path',
                            'collection',
                        ],
                        batch_size=200,
                    )
                updated = len(to_update)
            except Exception as e:
                self.stderr.write(f"   ❌ bulk_update Movie: {e}\n")
                self.stderr.flush()

        # 6. Перечитать movie_map
        movie_map = {m.tmdb_id: m for m in Movie.objects.filter(tmdb_id__in=tmdb_ids)}

        # 7. M2M через through.bulk_create
        self._save_m2m(movies_data_list, movie_map, genre_map, keyword_map, company_map)

        # 8. update_materialized_vectors для затронутых
        if movie_map:
            try:
                for m in movie_map.values():
                    m.update_materialized_vectors(force=True)
            except Exception as e:
                self.stderr.write(f"   ⚠️ update_materialized_vectors: {e}\n")
                self.stderr.flush()

        return created, updated, 0, movie_map

    def _save_m2m(
            self,
            movies_data_list: List[Dict[str, Any]],
            movie_map: Dict[int, Movie],
            genre_map: Dict[int, Genre],
            keyword_map: Dict[int, Keyword],
            company_map: Dict[int, Company],
    ) -> None:
        """through.bulk_create для genres/keywords/production_companies."""
        genre_through = Movie.genres.through
        keyword_through = Movie.keywords.through
        company_through = Movie.production_companies.through

        genre_rels = []
        keyword_rels = []
        company_rels = []

        # Определяем имена FK-колонок из _meta (movie_id/genre_id и т.д.)
        def _movie_col(through):
            return next(f.column for f in through._meta.fields if f.remote_field and f.remote_field.model is Movie)

        def _rel_col(through, model):
            return next(f.column for f in through._meta.fields if f.remote_field and f.remote_field.model is model)

        g_movie_col = _movie_col(genre_through)
        g_genre_col = _rel_col(genre_through, Genre)
        k_movie_col = _movie_col(keyword_through)
        k_kw_col = _rel_col(keyword_through, Keyword)
        c_movie_col = _movie_col(company_through)
        c_company_col = _rel_col(company_through, Company)

        for data in movies_data_list:
            tid = data.get('id')
            if not tid:
                continue
            m = movie_map.get(int(tid))
            if not m:
                continue
            for g in (data.get('genres') or []):
                gid = g.get('id')
                if gid and int(gid) in genre_map:
                    genre_rels.append(genre_through(**{g_movie_col: m.id, g_genre_col: genre_map[int(gid)].id}))
            kw_block = data.get('keywords') or {}
            for k in (kw_block.get('keywords') or []):
                kid = k.get('id')
                if kid and int(kid) in keyword_map:
                    keyword_rels.append(keyword_through(**{k_movie_col: m.id, k_kw_col: keyword_map[int(kid)].id}))
            for c in (data.get('production_companies') or []):
                cid = c.get('id')
                if cid and int(cid) in company_map:
                    company_rels.append(company_through(**{c_movie_col: m.id, c_company_col: company_map[int(cid)].id}))

        if genre_rels:
            genre_through.objects.bulk_create(genre_rels, ignore_conflicts=True, batch_size=1000)
        if keyword_rels:
            keyword_through.objects.bulk_create(keyword_rels, ignore_conflicts=True, batch_size=1000)
        if company_rels:
            company_through.objects.bulk_create(company_rels, ignore_conflicts=True, batch_size=1000)

    # ------------------------------------------------------------------ #
    #  Recommendations
    # ------------------------------------------------------------------ #

    def save_recommendations(
            self,
            movies_data_list: List[Dict[str, Any]],
            movie_map: Dict[int, Movie],
    ) -> int:
        """MovieRecommendation из recommendations.results. Создаёт заглушки для target."""
        # 1. Собрать все target tmdb_id
        target_tmdb_ids = set()
        for data in movies_data_list:
            recs = data.get('recommendations') or {}
            for r in (recs.get('results') or []):
                rid = r.get('id')
                if rid:
                    target_tmdb_ids.add(int(rid))

        if not target_tmdb_ids:
            return 0

        # 2. Существующие target
        existing_targets = {m.tmdb_id: m for m in Movie.objects.filter(tmdb_id__in=list(target_tmdb_ids))}

        # 3. Заглушки для отсутствующих
        to_create = []
        for data in movies_data_list:
            recs = data.get('recommendations') or {}
            for r in (recs.get('results') or []):
                rid = r.get('id')
                if not rid:
                    continue
                rid = int(rid)
                if rid in existing_targets or rid in movie_map:
                    continue
                if rid in {m.tmdb_id for m in to_create}:
                    continue
                to_create.append(
                    Movie(
                        tmdb_id=rid,
                        name=r.get('title') or r.get('original_title') or f'Movie {rid}',
                        original_title=r.get('original_title'),
                        summary=r.get('overview'),
                        rating=r.get('vote_average'),
                        rating_count=int(r.get('vote_count') or 0),
                        popularity=r.get('popularity'),
                        poster_path=r.get('poster_path'),
                        backdrop_path=r.get('backdrop_path'),
                        cover_url=build_image_url(r.get('poster_path'), 'w500'),
                        backdrop_url=build_image_url(r.get('backdrop_path'), 'w780'),
                        original_language=r.get('original_language'),
                        adult=bool(r.get('adult', False)),
                        first_release_date=self._parse_release_date(r.get('release_date')),
                    )
                )
        if to_create:
            Movie.objects.bulk_create(to_create, ignore_conflicts=True, batch_size=200)

        all_targets = {m.tmdb_id: m for m in Movie.objects.filter(tmdb_id__in=list(target_tmdb_ids))}

        # 4. MovieRecommendation
        rels = []
        for data in movies_data_list:
            tid = data.get('id')
            if not tid:
                continue
            source = movie_map.get(int(tid))
            if not source:
                continue
            recs = data.get('recommendations') or {}
            for order, r in enumerate(recs.get('results') or []):
                rid = r.get('id')
                if not rid:
                    continue
                target = all_targets.get(int(rid))
                if target and target.id != source.id:
                    rels.append(MovieRecommendation(source_movie=source, target_movie=target, order=order))

        if rels:
            MovieRecommendation.objects.bulk_create(rels, ignore_conflicts=True, batch_size=1000)
        return len(rels)

    # ------------------------------------------------------------------ #
    #  Images / Videos (опционально)
    # ------------------------------------------------------------------ #

    def save_images_videos(
            self,
            movies_data_list: List[Dict[str, Any]],
            movie_map: Dict[int, Movie],
    ) -> Tuple[int, int]:
        """Image/Video из images/videos (если есть в ответе)."""
        images = []
        videos = []
        for data in movies_data_list:
            tid = data.get('id')
            if not tid:
                continue
            m = movie_map.get(int(tid))
            if not m:
                continue
            img_block = data.get('images') or {}
            for kind in ('posters', 'backdrops', 'logos'):
                for img in (img_block.get(kind) or []):
                    fp = img.get('file_path')
                    if not fp:
                        continue
                    images.append(Image(
                        movie=m,
                        file_path=fp,
                        image_type='poster' if kind == 'posters' else ('backdrop' if kind == 'backdrops' else 'logo'),
                        width=img.get('width') or 0,
                        height=img.get('height') or 0,
                        aspect_ratio=img.get('aspect_ratio'),
                        language=img.get('iso_639_1'),
                        vote_average=img.get('vote_average'),
                        vote_count=img.get('vote_count') or 0,
                    ))
            vid_block = data.get('videos') or {}
            for v in (vid_block.get('results') or []):
                vid_id = v.get('id')
                key = v.get('key')
                if not vid_id or not key:
                    continue
                videos.append(Video(
                    movie=m,
                    video_id=vid_id,
                    key=key,
                    site=v.get('site') or 'YouTube',
                    video_type=v.get('type') or 'Trailer',
                    name=v.get('name') or '',
                    official=bool(v.get('official', False)),
                    size=v.get('size') or 0,
                    language=v.get('iso_639_1'),
                    country=v.get('iso_3166_1'),
                    published_at=self._parse_release_date(v.get('published_at')),
                ))

        if images:
            Image.objects.bulk_create(images, ignore_conflicts=True, batch_size=500)
        if videos:
            Video.objects.bulk_create(videos, ignore_conflicts=True, batch_size=500)
        return len(images), len(videos)