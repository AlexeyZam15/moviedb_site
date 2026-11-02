"""Media models: screenshots, images, videos."""

from django.db import models

from movies.load_tmdb.tmdb_api import build_image_url


class Screenshot(models.Model):
    """Legacy screenshot model (kept for template compatibility)."""

    movie = models.ForeignKey('Movie', on_delete=models.CASCADE, related_name='screenshots', db_index=True)
    url = models.URLField(max_length=500)
    w = models.SmallIntegerField(default=1920)
    h = models.SmallIntegerField(default=1080)
    primary = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ['-primary', 'id']
        indexes = [models.Index(fields=['movie', 'primary'])]

    def __str__(self) -> str:
        return f"Screenshot {self.id} for {self.movie.name}"


class Image(models.Model):
    """TMDB image (poster, backdrop, logo, screenshot)."""

    IMAGE_TYPES = [
        ('poster', 'Poster'),
        ('backdrop', 'Backdrop'),
        ('logo', 'Logo'),
        ('screenshot', 'Screenshot'),
    ]

    movie = models.ForeignKey('Movie', on_delete=models.CASCADE, related_name='images', db_index=True)
    file_path = models.CharField(max_length=255, db_index=True)
    image_type = models.CharField(max_length=20, choices=IMAGE_TYPES, db_index=True)
    width = models.IntegerField(default=0)
    height = models.IntegerField(default=0)
    aspect_ratio = models.FloatField(null=True, blank=True)
    language = models.CharField(max_length=10, blank=True, null=True, db_index=True)
    vote_average = models.FloatField(null=True, blank=True)
    vote_count = models.IntegerField(default=0)

    class Meta:
        ordering = ['-vote_average', 'id']
        indexes = [
            models.Index(fields=['movie', 'image_type']),
            models.Index(fields=['file_path']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['movie', 'file_path', 'image_type'],
                name='uniq_image_movie_file_type',
            ),
        ]

    def __str__(self) -> str:
        return f"{self.image_type} for {self.movie.name}"

    @property
    def url(self) -> str:
        return build_image_url(self.file_path, 'w500') or ''

    @property
    def url_w342(self) -> str:
        return build_image_url(self.file_path, 'w342') or ''

    @property
    def url_w500(self) -> str:
        return build_image_url(self.file_path, 'w500') or ''

    @property
    def url_w780(self) -> str:
        return build_image_url(self.file_path, 'w780') or ''

    @property
    def url_original(self) -> str:
        return build_image_url(self.file_path, 'original') or ''


class Video(models.Model):
    """TMDB video (trailer, teaser, clip, featurette, bloopers)."""

    VIDEO_TYPES = [
        ('Trailer', 'Trailer'),
        ('Teaser', 'Teaser'),
        ('Clip', 'Clip'),
        ('Featurette', 'Featurette'),
        ('Bloopers', 'Bloopers'),
        ('Behind the Scenes', 'Behind the Scenes'),
    ]

    movie = models.ForeignKey('Movie', on_delete=models.CASCADE, related_name='videos', db_index=True)
    video_id = models.CharField(max_length=64, db_index=True)
    key = models.CharField(max_length=64, db_index=True)
    site = models.CharField(max_length=32, default='YouTube')
    video_type = models.CharField(max_length=32, choices=VIDEO_TYPES, db_index=True)
    name = models.CharField(max_length=255)
    official = models.BooleanField(default=False, db_index=True)
    size = models.IntegerField(default=0)
    language = models.CharField(max_length=10, blank=True, null=True)
    country = models.CharField(max_length=10, blank=True, null=True)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ['-official', 'video_type', '-published_at']
        indexes = [
            models.Index(fields=['movie', 'video_type']),
            models.Index(fields=['key']),
        ]

    def __str__(self) -> str:
        return f"{self.video_type}: {self.name}"
