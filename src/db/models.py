from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, ForeignKey, JSON, Text
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()


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
    created_at = Column(DateTime, default=datetime.utcnow)


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
