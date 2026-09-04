from src.backend.mongo.collections.col_jobs import JobDocument
from src.core.functions.job_eligibility import is_board_eligible


def test_eligible_job_posts():
    job = JobDocument(title="Graduate Software Engineer", board_eligible=True)
    assert is_board_eligible(job) is True


def test_ineligible_job_does_not_post():
    job = JobDocument(title="Graduate Accountant", board_eligible=False)
    assert is_board_eligible(job) is False


def test_unscored_job_does_not_post():
    """Default-deny.

    Every document in the live collection predates board scoring, so treating a
    missing field as "post it" means posting the entire collection at once.
    """
    job = JobDocument(title="Graduate Software Engineer")
    assert job.board_eligible is None
    assert is_board_eligible(job) is False


def test_board_fields_parse_from_mongo_document():
    job = JobDocument.model_validate(
        {
            "title": "Graduate Software Engineer",
            "board_eligible": True,
            "board_score": 7,
            "discipline": "SOFTWARE",
        }
    )
    assert job.board_eligible is True
    assert job.board_score == 7
    assert job.discipline == "SOFTWARE"


def test_board_fields_absent_do_not_raise():
    """Documents written before board scoring must still validate."""
    job = JobDocument.model_validate({"title": "Legacy Job"})
    assert job.board_eligible is None
    assert job.board_score is None
    assert job.discipline is None
