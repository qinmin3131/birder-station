import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.models import (
    Base,
    BirdReportReport,
    EBirdDraftStatus,
    EBirdItemSource,
    EBirdSyncDraft,
    EBirdSyncItem,
    Photo,
    Species,
)


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


def test_ebird_sync_models_persist_relationships(session):
    report = BirdReportReport(
        remote_id="202610070001",
        observed_on="20261007",
        location_name="奥森",
    )
    draft = EBirdSyncDraft(
        report=report,
        status=EBirdDraftStatus.PENDING_CONFIRMATION.value,
    )
    draft.items.append(
        EBirdSyncItem(
            source=EBirdItemSource.BIRDREPORT.value,
            scientific_name="Pica pica",
            count_value="2",
            included=True,
        )
    )

    session.add(draft)
    session.commit()

    assert draft.report.remote_id == "202610070001"
    assert draft.items[0].count_value == "2"
