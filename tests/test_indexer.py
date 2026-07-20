import pytest
from pathlib import Path
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, Photo
from src.db.repository import PhotoRepository
from src.core.indexer import PhotoIndexer


@pytest.fixture
def repo(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return PhotoRepository(Session())


def test_index_folder_adds_only_supported_images(repo, tmp_path):
    indexer = PhotoIndexer(repo)

    # Create a JPEG image
    img_path = tmp_path / "bird.jpg"
    Image.new("RGB", (100, 100), color="red").save(img_path)

    # Create a non-image file
    (tmp_path / "notes.txt").write_text("not a photo")

    photos = indexer.index_folder(tmp_path)

    assert len(photos) == 1
    assert photos[0].filename == "bird.jpg"
    assert photos[0].file_hash is not None


def test_index_folder_skips_duplicate_hash(repo, tmp_path):
    indexer = PhotoIndexer(repo)

    img_path = tmp_path / "bird.jpg"
    Image.new("RGB", (100, 100), color="blue").save(img_path)

    first_run = indexer.index_folder(tmp_path)
    second_run = indexer.index_folder(tmp_path)

    assert len(first_run) == 1
    assert len(second_run) == 0

    all_photos = repo.list_photos()
    assert len(all_photos) == 1


def test_index_folder_respects_supported_formats(repo, tmp_path):
    indexer = PhotoIndexer(repo, supported_formats={".jpg"})

    (tmp_path / "bird.jpg").write_bytes(b"fake jpg")
    (tmp_path / "bird.nef").write_bytes(b"fake raw")

    photos = indexer.index_folder(tmp_path)

    assert len(photos) == 1
    assert photos[0].filename == "bird.jpg"
