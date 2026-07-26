from datetime import datetime, timezone

from src.backend.mongo.collections.col_jobs import Company, JobDocument
from src.core.functions.job_embed import build_job_embed


def test_title_includes_company():
    job = JobDocument(title="Software Engineer", company=Company(name="ACME"))
    embed = build_job_embed(job)
    assert "Software Engineer" in embed.title
    assert "ACME" in embed.title


def test_title_truncated_to_256():
    job = JobDocument(title="T" * 200, company=Company(name="C" * 200))
    embed = build_job_embed(job)
    assert len(embed.title) <= 256


def test_description_uses_one_liner():
    job = JobDocument(title="T", one_liner="A great opportunity")
    embed = build_job_embed(job)
    assert embed.description == "A great opportunity"


def test_description_none_when_no_one_liner():
    job = JobDocument(title="T")
    embed = build_job_embed(job)
    assert embed.description is None


def test_colour_is_yellow():
    job = JobDocument(title="T")
    embed = build_job_embed(job)
    assert embed.colour.value == 0xFFE330


def test_thumbnail_set_from_logo():
    job = JobDocument(
        title="T", company=Company(name="X", logo="https://example.com/logo.png")
    )
    embed = build_job_embed(job)
    assert embed.thumbnail.url == "https://example.com/logo.png"


def test_no_thumbnail_when_no_logo():
    job = JobDocument(title="T", company=Company(name="X"))
    embed = build_job_embed(job)
    assert embed.thumbnail.url is None


def test_type_field_present():
    job = JobDocument(title="T", type="GRADUATE")
    embed = build_job_embed(job)
    field_names = [f.name for f in embed.fields]
    assert "Type" in field_names


def test_locations_field_present():
    job = JobDocument(title="T", locations=["VIC", "NSW"])
    embed = build_job_embed(job)
    assert any(f.name == "Locations" for f in embed.fields)


def test_working_rights_labels_used():
    job = JobDocument(title="T", working_rights=["AUS_CITIZEN_PR", "NZ_CITIZEN_PR"])
    embed = build_job_embed(job)
    field = next(f for f in embed.fields if f.name == "Working Rights")
    assert "AU Citizen/PR" in field.value
    assert "NZ Citizen/PR" in field.value


def test_close_date_field_present():
    job = JobDocument(title="T", close_date=datetime(2099, 1, 1, tzinfo=timezone.utc))
    embed = build_job_embed(job)
    assert any(f.name == "Close Date" for f in embed.fields)


def test_sponsored_field_yes():
    job = JobDocument(title="T", is_sponsored=True)
    embed = build_job_embed(job)
    field = next(f for f in embed.fields if f.name == "Sponsored")
    assert field.value == "Yes"


def test_sponsored_field_no():
    job = JobDocument(title="T", is_sponsored=False)
    embed = build_job_embed(job)
    field = next(f for f in embed.fields if f.name == "Sponsored")
    assert field.value == "No"


def test_url_contains_job_id():
    job = JobDocument(title="T")
    job.id = "abc123"
    embed = build_job_embed(job)
    assert "abc123" in embed.url
