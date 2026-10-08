from enum import Enum

from sqlalchemy import create_engine, inspect, Column, Integer, String, Float, DateTime, Boolean, ForeignKey, JSON, Text, text
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()


class EBirdDraftStatus(str, Enum):
    PENDING_MATCH = "pending_match"
    PENDING_CONFIRMATION = "pending_confirmation"
    READY = "ready"
    EXPORTED = "exported"
    UPLOADED = "uploaded"
    NEEDS_REVISION = "needs_revision"


class EBirdItemSource(str, Enum):
    BIRDREPORT = "birdreport"
    LOCAL_SUPPLEMENT = "local_supplement"
    BOTH = "both"


def init_database(engine):
    """Initialize or migrate the database schema for SQLAlchemy models.

    Adds missing columns to the existing `photos` table (if any) and creates
    new tables required by the new data layer.
    """
    inspector = inspect(engine)

    if inspector.has_table("photos"):
        existing_columns = {c["name"] for c in inspector.get_columns("photos")}
        missing_columns = [
            ("captured_at", "DATETIME"),
            ("latitude", "FLOAT"),
            ("longitude", "FLOAT"),
            ("is_selected", "BOOLEAN DEFAULT 0"),
            ("rating", "INTEGER"),
            ("quality_score", "INTEGER"),
            ("quality_details", "TEXT"),
            ("bird_bbox", "TEXT"),
            ("location_level1", "TEXT"),
            ("location_level2", "TEXT"),
            ("location_level3", "TEXT"),
            ("outing_id", "INTEGER"),
            ("created_at", "DATETIME DEFAULT CURRENT_TIMESTAMP"),
        ]
        for col_name, col_type in missing_columns:
            if col_name not in existing_columns:
                with engine.begin() as conn:
                    conn.execute(
                        text(f"ALTER TABLE photos ADD COLUMN {col_name} {col_type}")
                    )

    Base.metadata.create_all(engine)


class Species(Base):
    __tablename__ = "species"
    id = Column(Integer, primary_key=True)
    scientific_name = Column(String, unique=True, nullable=False)
    chinese_name = Column(String)
    english_name = Column(String)
    family_cn = Column(String)
    order_cn = Column(String)
    genus_cn = Column(String)
    family_sci = Column(String)
    order_sci = Column(String)
    genus_sci = Column(String)
    photo_count = Column(Integer, default=0)


class Photo(Base):
    __tablename__ = "photos"
    id = Column(Integer, primary_key=True)
    file_path = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    original_path = Column(String)
    file_hash = Column(String, unique=True)
    captured_at = Column(DateTime)
    captured_date = Column(String)
    location_tag = Column(String)
    location_level1 = Column(String)  # 省/直辖市
    location_level2 = Column(String)  # 市/区
    location_level3 = Column(String)  # 公园/具体地点
    latitude = Column(Float)
    longitude = Column(Float)
    primary_bird_cn = Column(String)
    scientific_name = Column(String)
    confidence_score = Column(Float)
    candidates_json = Column(JSON)
    width = Column(Integer)
    height = Column(Integer)
    is_selected = Column(Boolean, default=False)
    rating = Column(Integer)
    quality_score = Column(Integer)
    quality_details = Column(JSON)
    bird_bbox = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    outing_id = Column(Integer, ForeignKey("outings.id"))
    group_id = Column(Integer, ForeignKey("photo_groups.id"))


class PhotoGroup(Base):
    __tablename__ = "photo_groups"
    id = Column(Integer, primary_key=True)
    outing_id = Column(Integer, ForeignKey("outings.id"))
    best_photo_id = Column(Integer, ForeignKey("photos.id"))
    created_at = Column(DateTime, default=datetime.utcnow)


class Outing(Base):
    __tablename__ = "outings"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    start_date = Column(String)
    end_date = Column(String)
    location_tag = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


class BirdReportReport(Base):
    __tablename__ = "birdreport_reports"

    id = Column(Integer, primary_key=True)
    remote_id = Column(String, unique=True, nullable=False, index=True)
    observed_on = Column(String, nullable=False, index=True)
    location_name = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    summary_json = Column(JSON, default=dict)
    species_json = Column(JSON, default=list)
    raw_json = Column(JSON, default=dict)
    content_hash = Column(String, nullable=False, default="")
    taxonomy_version = Column(String)
    first_fetched_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_fetched_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    drafts = relationship("EBirdSyncDraft", back_populates="report")


class EBirdSyncDraft(Base):
    __tablename__ = "ebird_sync_drafts"

    id = Column(Integer, primary_key=True)
    report_id = Column(Integer, ForeignKey("birdreport_reports.id"), nullable=False, index=True)
    outing_id = Column(Integer, ForeignKey("outings.id"), index=True)
    status = Column(String, nullable=False, default=EBirdDraftStatus.PENDING_MATCH.value, index=True)
    location_name = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    protocol = Column(String)
    start_time = Column(String)
    duration_minutes = Column(Integer)
    distance_km = Column(Float)
    observer_count = Column(Integer)
    is_complete_checklist = Column(Boolean)
    suggestion_json = Column(JSON, default=dict)
    source_content_hash = Column(String)
    duplicate_warning = Column(Boolean, default=False, nullable=False)
    ebird_checklist_id = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    report = relationship("BirdReportReport", back_populates="drafts")
    outing = relationship("Outing")
    items = relationship(
        "EBirdSyncItem",
        back_populates="draft",
        cascade="all, delete-orphan",
        order_by="EBirdSyncItem.id",
    )
    export_batches = relationship(
        "EBirdExportBatch",
        back_populates="draft",
        cascade="all, delete-orphan",
        order_by="EBirdExportBatch.id",
    )


class EBirdSyncItem(Base):
    __tablename__ = "ebird_sync_items"

    id = Column(Integer, primary_key=True)
    draft_id = Column(Integer, ForeignKey("ebird_sync_drafts.id"), nullable=False, index=True)
    source = Column(String, nullable=False)
    birdreport_name = Column(String)
    local_name = Column(String)
    ebird_name = Column(String)
    scientific_name = Column(String)
    taxonomy_code = Column(String)
    taxonomy_version = Column(String)
    count_value = Column(String, nullable=False, default="X")
    included = Column(Boolean, nullable=False, default=False)
    mapping_status = Column(String, nullable=False, default="needs_confirmation")
    evidence_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    draft = relationship("EBirdSyncDraft", back_populates="items")


class EBirdExportBatch(Base):
    __tablename__ = "ebird_export_batches"

    id = Column(Integer, primary_key=True)
    draft_id = Column(Integer, ForeignKey("ebird_sync_drafts.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    content_hash = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    draft = relationship("EBirdSyncDraft", back_populates="export_batches")
