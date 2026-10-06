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
            ("location_level1", "TEXT"),
            ("location_level2", "TEXT"),
            ("location_level3", "TEXT"),
            ("outing_id", "INTEGER"),
            ("tags", "TEXT"),
            ("note", "TEXT"),
            ("created_at", "DATETIME DEFAULT CURRENT_TIMESTAMP"),
        ]
        for col_name, col_type in missing_columns:
            if col_name not in existing_columns:
                with engine.begin() as conn:
                    conn.execute(
                        text(f"ALTER TABLE photos ADD COLUMN {col_name} {col_type}")
                    )

    Base.metadata.create_all(engine)

    # Create missing indexes on existing tables (idempotent).
    # SQLAlchemy's create_all does not add indexes to pre-existing tables.
    index_statements = [
        "CREATE INDEX IF NOT EXISTS ix_photos_primary_bird_cn ON photos(primary_bird_cn)",
        "CREATE INDEX IF NOT EXISTS ix_photos_scientific_name ON photos(scientific_name)",
        "CREATE INDEX IF NOT EXISTS ix_photos_location_level1 ON photos(location_level1)",
        "CREATE INDEX IF NOT EXISTS ix_photos_location_level2 ON photos(location_level2)",
        "CREATE INDEX IF NOT EXISTS ix_photos_location_level3 ON photos(location_level3)",
        "CREATE INDEX IF NOT EXISTS ix_photos_is_selected ON photos(is_selected)",
        "CREATE INDEX IF NOT EXISTS ix_photos_outing_id ON photos(outing_id)",
        "CREATE INDEX IF NOT EXISTS ix_photos_group_id ON photos(group_id)",
        "CREATE INDEX IF NOT EXISTS ix_taxonomy_family_cn ON taxonomy(family_cn)",
        "CREATE INDEX IF NOT EXISTS ix_taxonomy_order_cn ON taxonomy(order_cn)",
        "CREATE INDEX IF NOT EXISTS ix_taxonomy_chinese_name ON taxonomy(chinese_name)",
    ]
    with engine.begin() as conn:
        for stmt in index_statements:
            conn.execute(text(stmt))


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


class Taxonomy(Base):
    """IOC taxonomy reference table (read-only, pre-populated)."""
    __tablename__ = "taxonomy"
    id = Column(Integer, primary_key=True)
    scientific_name = Column(String, unique=True, nullable=False)
    chinese_name = Column(String, index=True)
    english_name = Column(String)
    family_cn = Column(String, index=True)
    family_sci = Column(String)
    order_cn = Column(String, index=True)
    order_sci = Column(String)
    genus_cn = Column(String)
    genus_sci = Column(String)


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
    location_level1 = Column(String, index=True)  # 省/直辖市
    location_level2 = Column(String, index=True)  # 市/区
    location_level3 = Column(String, index=True)  # 公园/具体地点
    latitude = Column(Float)
    longitude = Column(Float)
    primary_bird_cn = Column(String, index=True)
    scientific_name = Column(String, index=True)
    confidence_score = Column(Float)
    candidates_json = Column(JSON)
    width = Column(Integer)
    height = Column(Integer)
    is_selected = Column(Boolean, default=False, index=True)
    rating = Column(Integer)
    quality_score = Column(Integer)
    quality_details = Column(JSON)
    bird_bbox = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    tags = Column(JSON)
    note = Column(Text)
    outing_id = Column(Integer, ForeignKey("outings.id"), index=True)
    group_id = Column(Integer, ForeignKey("photo_groups.id"), index=True)


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
