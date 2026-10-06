import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.models import Base, Photo
from src.db.repository import PhotoRepository, OutingRepository


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


@pytest.fixture
def outing_repo():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return OutingRepository(Session())


def test_outing_get_or_create_creates_new(outing_repo):
    outing = outing_repo.get_or_create(name="20260101_北京_奥森", start_date="20260101")
    assert outing.id is not None
    assert outing.name == "20260101_北京_奥森"


def test_outing_get_or_create_reuses_existing_by_name(outing_repo):
    """同名外拍即使 start_date 不同也应复用，避免重复导入产生重复外拍。"""
    first = outing_repo.get_or_create(name="20260101_北京_奥森", start_date="20260101")
    second = outing_repo.get_or_create(name="20260101_北京_奥森", start_date="20260927")
    assert first.id == second.id
