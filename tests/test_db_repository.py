import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.models import Base, Photo
from src.db.repository import PhotoRepository


@pytest.fixture
def repo():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return PhotoRepository(Session())


def test_add_and_get_photo(repo):
    photo = Photo(file_path="D:/test.jpg", filename="test.jpg")
    added = repo.add(photo)
    assert added.id is not None
    fetched = repo.get_by_id(added.id)
    assert fetched.filename == "test.jpg"
