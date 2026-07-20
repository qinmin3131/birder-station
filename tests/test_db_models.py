import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.models import Base, Photo, Species


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_create_photo(session):
    photo = Photo(file_path="D:/Photos/test.jpg", filename="test.jpg")
    session.add(photo)
    session.commit()
    assert photo.id is not None


def test_create_species(session):
    sp = Species(scientific_name="Acrocephalus arundinaceus", chinese_name="大苇莺")
    session.add(sp)
    session.commit()
    assert sp.id is not None
