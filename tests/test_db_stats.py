import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, Photo, Species
from src.db.stats import refresh_species_for_photo


class FakeManager:
    def __init__(self):
        self.updated = []
        self.closed = 0

    def get_bird_info(self, scientific_name):
        return {"chinese_name": "麻雀", "family_cn": "雀科", "family_sci": "Passeridae"}

    def update_species_stats_for_photo(self, scientific_name):
        self.updated.append(scientific_name)

    def close(self):
        self.closed += 1


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_refresh_creates_species_with_photo_count(session):
    fake = FakeManager()
    session.add(Photo(file_path="a.jpg", filename="a.jpg", scientific_name="Passer montanus"))
    session.add(Photo(file_path="b.jpg", filename="b.jpg", scientific_name="Passer montanus"))
    session.commit()

    refresh_species_for_photo(session, "Passer montanus", manager_factory=lambda: fake)

    sp = session.query(Species).filter(Species.scientific_name == "Passer montanus").first()
    assert sp is not None
    assert sp.photo_count == 2
    assert sp.chinese_name == "麻雀"
    assert fake.updated == ["Passer montanus"]


def test_refresh_updates_existing_species_count(session):
    session.add(Species(scientific_name="Passer montanus", photo_count=5))
    session.add(Photo(file_path="a.jpg", filename="a.jpg", scientific_name="Passer montanus"))
    session.commit()

    refresh_species_for_photo(session, "Passer montanus")

    sp = session.query(Species).filter(Species.scientific_name == "Passer montanus").first()
    assert sp.photo_count == 1


def test_refresh_deletes_species_when_no_photos(session):
    session.add(Species(scientific_name="Passer montanus", photo_count=1))
    session.commit()

    refresh_species_for_photo(session, "Passer montanus")

    assert session.query(Species).filter(Species.scientific_name == "Passer montanus").first() is None


def test_refresh_empty_name_is_noop(session):
    refresh_species_for_photo(session, "")
    assert session.query(Species).count() == 0
