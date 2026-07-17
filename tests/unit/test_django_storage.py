"""Django ORM integration for :func:`fencekit.storage.fenced_update`."""

from __future__ import annotations

import pytest

django = pytest.importorskip("django")

from django.conf import settings

if not settings.configured:
    settings.configure(
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": ":memory:",
            }
        },
        INSTALLED_APPS=[
            "tests.django_support.apps.DjangoSupportConfig",
        ],
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        USE_TZ=True,
        SECRET_KEY="fencekit-tests-not-for-production",
    )

django.setup()

from django.db import connection

from fencekit import FencedOutError, FenceToken, fenced_update
from tests.django_support.models import AnalysisJob


@pytest.fixture(scope="module", autouse=True)
def _analysis_job_table() -> object:
    with connection.schema_editor() as schema_editor:
        schema_editor.create_model(AnalysisJob)
    yield
    with connection.schema_editor() as schema_editor:
        schema_editor.delete_model(AnalysisJob)


@pytest.fixture(autouse=True)
def _clean_jobs() -> None:
    AnalysisJob.objects.all().delete()


def test_django_fenced_update_advances_row() -> None:
    job = AnalysisJob.objects.create(progress=10, status="pending", fence_token=2)
    token = FenceToken(value=5, resource=f"analysis:{job.pk}")

    ok = fenced_update(
        AnalysisJob.objects.filter(pk=job.pk),
        token,
        updates={"progress": 75, "status": "running"},
    )

    job.refresh_from_db()
    assert ok is True
    assert job.progress == 75
    assert job.status == "running"
    assert job.fence_token == 5


def test_django_fenced_update_rejects_stale_token() -> None:
    job = AnalysisJob.objects.create(progress=80, status="running", fence_token=5)
    stale = FenceToken(value=4, resource=f"analysis:{job.pk}")

    ok = fenced_update(
        AnalysisJob.objects.filter(pk=job.pk),
        stale,
        updates={"progress": 99, "status": "stale-write"},
    )

    job.refresh_from_db()
    assert ok is False
    assert job.progress == 80
    assert job.status == "running"
    assert job.fence_token == 5


def test_django_fenced_update_equal_token_rewrites() -> None:
    job = AnalysisJob.objects.create(progress=20, fence_token=3)
    token = FenceToken(value=3, resource=f"analysis:{job.pk}")

    assert fenced_update(
        AnalysisJob.objects.filter(pk=job.pk),
        token,
        updates={"progress": 40},
    )
    job.refresh_from_db()
    assert job.progress == 40
    assert job.fence_token == 3


def test_django_fenced_update_raise_on_stale() -> None:
    job = AnalysisJob.objects.create(fence_token=7)
    stale = FenceToken(value=1, resource=f"analysis:{job.pk}")

    with pytest.raises(FencedOutError):
        fenced_update(
            AnalysisJob.objects.filter(pk=job.pk),
            stale,
            updates={"progress": 1},
            raise_on_stale=True,
        )
