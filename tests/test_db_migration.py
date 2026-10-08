import pytest
from sqlalchemy import create_engine, inspect, text
from src.db.models import Base, init_database


def test_init_database_adds_missing_columns_and_tables():
    """Regression test: init_database should migrate an old schema."""
    engine = create_engine("sqlite:///:memory:")

    # Create an old-style photos table with only the original columns
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE photos (
                    id INTEGER PRIMARY KEY,
                    file_path TEXT,
                    filename TEXT,
                    original_path TEXT,
                    file_hash TEXT,
                    captured_date TEXT,
                    location_tag TEXT,
                    primary_bird_cn TEXT,
                    scientific_name TEXT,
                    confidence_score REAL,
                    width INTEGER,
                    height INTEGER,
                    candidates_json TEXT,
                    web_processed_path TEXT,
                    web_raw_path TEXT
                )
                """
            )
        )

    inspector = inspect(engine)
    assert inspector.has_table("photos")
    assert not inspector.has_table("species")
    assert not inspector.has_table("outings")
    assert not inspector.has_table("photo_groups")

    old_columns = {c["name"] for c in inspector.get_columns("photos")}
    assert "captured_at" not in old_columns

    init_database(engine)

    inspector = inspect(engine)
    assert inspector.has_table("species")
    assert inspector.has_table("outings")
    assert inspector.has_table("photo_groups")

    new_columns = {c["name"] for c in inspector.get_columns("photos")}
    assert "captured_at" in new_columns
    assert "is_selected" in new_columns
    assert "quality_score" in new_columns
    assert "created_at" in new_columns


def test_init_database_creates_new_schema_when_empty():
    """init_database should create all tables on a fresh DB."""
    engine = create_engine("sqlite:///:memory:")
    init_database(engine)

    inspector = inspect(engine)
    assert inspector.has_table("photos")
    assert inspector.has_table("species")
    assert inspector.has_table("outings")
    assert inspector.has_table("photo_groups")


def test_init_database_is_idempotent_for_ebird_tables(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")

    init_database(engine)
    init_database(engine)

    assert {
        "birdreport_reports",
        "ebird_sync_drafts",
        "ebird_sync_items",
        "ebird_export_batches",
    } <= set(inspect(engine).get_table_names())
