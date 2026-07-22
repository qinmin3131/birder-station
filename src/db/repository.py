from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from src.db.models import Photo, Species, Outing, PhotoGroup


class PhotoRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, photo_id: int) -> Optional[Photo]:
        return self.session.query(Photo).filter(Photo.id == photo_id).first()

    def get_by_hash(self, file_hash: str) -> Optional[Photo]:
        return self.session.query(Photo).filter(Photo.file_hash == file_hash).first()

    def add(self, photo: Photo) -> Photo:
        self.session.add(photo)
        self.session.commit()
        self.session.refresh(photo)
        return photo

    def list_photos(self, limit: int = 50, offset: int = 0,
                    is_selected: Optional[bool] = None) -> List[Photo]:
        query = self.session.query(Photo)
        if is_selected is not None:
            query = query.filter(Photo.is_selected == is_selected)
        return query.order_by(Photo.captured_at.desc()).offset(offset).limit(limit).all()

    def update_species(self, photo_id: int, scientific_name: str, chinese_name: str) -> None:
        photo = self.get_by_id(photo_id)
        if photo:
            photo.scientific_name = scientific_name
            photo.primary_bird_cn = chinese_name
            photo.confidence_score = 1.0
            self.session.commit()

    def add_group(self, group: PhotoGroup) -> PhotoGroup:
        self.session.add(group)
        self.session.commit()
        self.session.refresh(group)
        return group


class SpeciesRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_scientific_name(self, name: str) -> Optional[Species]:
        return self.session.query(Species).filter(Species.scientific_name == name).first()

    def add(self, species: Species) -> Species:
        self.session.add(species)
        self.session.commit()
        self.session.refresh(species)
        return species

    def list_unlocked(self) -> List[Species]:
        return self.session.query(Species).filter(Species.photo_count > 0).all()


class OutingRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_or_create(self, name: str, start_date: str) -> Outing:
        outing = self.session.query(Outing).filter(
            Outing.name == name, Outing.start_date == start_date
        ).first()
        if not outing:
            outing = Outing(name=name, start_date=start_date)
            self.session.add(outing)
            self.session.commit()
            self.session.refresh(outing)
        return outing
