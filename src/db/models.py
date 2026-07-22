from sqlalchemy import create_engine, inspect, Column, Integer, String, Float, DateTime, Boolean, ForeignKey, JSON, Text, text
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()


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
