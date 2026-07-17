from django.db import models


class AnalysisJob(models.Model):
    """Stand-in for a ChessMate-style analysis row with a fence column."""

    progress = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=32, default="pending")
    fence_token = models.PositiveIntegerField(default=0)

    class Meta:
        app_label = "fencekit_django_support"
