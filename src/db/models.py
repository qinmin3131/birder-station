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
        # 模型驱动的列迁移：对照 Photo 模型补齐旧表缺失的全部列，
        # 避免硬编码清单随模型演进不断遗漏（只加类型，不带 NOT NULL/外键，
        # 模型中唯一 NOT NULL 的 file_path/filename 在最旧的表里也已存在）
        existing_columns = {c["name"] for c in inspector.get_columns("photos")}
        photo_table = Base.metadata.tables["photos"]
        for column in photo_table.columns:
            if column.name in existing_columns:
                continue
            col_type = column.type.compile(engine.dialect)
            with engine.begin() as conn:
                conn.execute(
                    text(
                        f"ALTER TABLE photos ADD COLUMN {column.name} {col_type}"
                    )
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
        "CREATE INDEX IF NOT EXISTS ix_videos_outing_id ON videos(outing_id)",
        "CREATE INDEX IF NOT EXISTS ix_videos_captured_date ON videos(captured_date)",
        "CREATE INDEX IF NOT EXISTS ix_videos_location_level1 ON videos(location_level1)",
        "CREATE INDEX IF NOT EXISTS ix_videos_location_level2 ON videos(location_level2)",
        "CREATE INDEX IF NOT EXISTS ix_videos_location_level3 ON videos(location_level3)",
        "CREATE INDEX IF NOT EXISTS ix_video_markers_video_id ON video_markers(video_id)",
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


class Video(Base):
    """视频素材记录：仅索引不移动源文件，不做内容识别。"""
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True)
    file_path = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    original_path = Column(String)
    file_hash = Column(String, unique=True)
    captured_at = Column(DateTime)
    captured_date = Column(String, index=True)
    duration = Column(Float)  # 秒
    width = Column(Integer)
    height = Column(Integer)
    fps = Column(Float)
    video_codec = Column(String)
    audio_codec = Column(String)
    thumbnail_path = Column(String)
    location_tag = Column(String)
    location_level1 = Column(String, index=True)  # 省/直辖市
    location_level2 = Column(String, index=True)  # 市/区
    location_level3 = Column(String, index=True)  # 具体地点
    note = Column(Text)
    tags = Column(JSON)
    probe_failed = Column(Boolean, default=False)
    outing_id = Column(Integer, ForeignKey("outings.id"), index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class VideoMarker(Base):
    """视频时间线标记：kind=point 为时间点备注，kind=segment 为入/出点片段。"""
    __tablename__ = "video_markers"
    id = Column(Integer, primary_key=True)
    video_id = Column(Integer, ForeignKey("videos.id"), index=True)
    kind = Column(String, nullable=False)  # point | segment
    time = Column(Float)       # point: 打点时间（秒）
    in_time = Column(Float)    # segment: 入点
    out_time = Column(Float)   # segment: 出点
    value = Column(Text)
    category = Column(String)  # 片段分类：可用/采访/B-roll/弃用
    completed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
