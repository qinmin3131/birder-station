import json
from typing import Optional, List, Dict
from sqlalchemy import or_, exists, func
from sqlalchemy.orm import Session
from src.db.models import (
    Photo,
    Species,
    Outing,
    PhotoGroup,
    Video,
    VideoMarker,
)


class PhotoRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, photo_id: int) -> Optional[Photo]:
        return self.session.query(Photo).filter(Photo.id == photo_id).first()

    def get_by_hash(self, file_hash: str) -> Optional[Photo]:
        return self.session.query(Photo).filter(Photo.file_hash == file_hash).first()

    def get_by_path_and_name(self, file_path: str, filename: str) -> Optional[Photo]:
        return self.session.query(Photo).filter(
            Photo.file_path == file_path, Photo.filename == filename
        ).first()

    def delete(self, photo: Photo) -> None:
        self.session.delete(photo)
        self.session.commit()

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

    def get_or_create(self, name: str, start_date: str = None) -> Outing:
        """按外拍名称查找已有外拍，找不到则新建。

        文件夹名通常已包含日期（如 20260101_北京_奥森），按 name 匹配即可
        保证重复导入同一文件夹时沿用原有外拍 ID，而不会因导入日期不同
        创建重复外拍。
        """
        outing = self.session.query(Outing).filter(Outing.name == name).first()
        if not outing:
            outing = Outing(name=name, start_date=start_date)
            self.session.add(outing)
            self.session.commit()
            self.session.refresh(outing)
        return outing

    def get_by_id(self, outing_id: int) -> Optional[Outing]:
        return self.session.query(Outing).filter(Outing.id == outing_id).first()

    def list_recent(self, limit: int = 20) -> List[Outing]:
        return self.session.query(Outing).order_by(Outing.created_at.desc()).limit(limit).all()


class VideoRepository:
    """视频素材与时间线标记的数据访问。"""

    def __init__(self, session: Session):
        self.session = session

    # -- Video -------------------------------------------------------------
    def add(self, video: Video) -> Video:
        self.session.add(video)
        self.session.commit()
        self.session.refresh(video)
        return video

    def get_by_id(self, video_id: int) -> Optional[Video]:
        return self.session.query(Video).filter(Video.id == video_id).first()

    def get_by_hash(self, file_hash: str) -> Optional[Video]:
        return self.session.query(Video).filter(Video.file_hash == file_hash).first()

    def get_by_path_and_name(self, file_path: str, filename: str) -> Optional[Video]:
        return self.session.query(Video).filter(
            Video.file_path == file_path, Video.filename == filename
        ).first()

    def delete(self, video: Video) -> None:
        self.session.query(VideoMarker).filter(
            VideoMarker.video_id == video.id
        ).delete()
        self.session.delete(video)
        self.session.commit()

    @staticmethod
    def _apply_filters(
        query,
        outing_id: Optional[int] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        location_level1: Optional[str] = None,
        location_level2: Optional[str] = None,
        location_level3: Optional[str] = None,
        tag: Optional[str] = None,
        q: Optional[str] = None,
    ):
        if outing_id:
            query = query.filter(Video.outing_id == outing_id)
        if date_from:
            query = query.filter(Video.captured_date >= date_from)
        if date_to:
            query = query.filter(Video.captured_date <= date_to)
        if location_level1:
            query = query.filter(Video.location_level1 == location_level1)
        if location_level2:
            query = query.filter(Video.location_level2 == location_level2)
        if location_level3:
            query = query.filter(Video.location_level3 == location_level3)
        if tag:
            # tags 以 JSON 数组存储。SQLAlchemy JSON 默认 ensure_ascii=True，
            # 中文会被转义成 \uXXXX，因此同时匹配原文与转义两种形式。
            escaped_tag = json.dumps(tag, ensure_ascii=True)[1:-1]
            query = query.filter(
                or_(
                    Video.tags.like(f'%"{tag}"%'),
                    Video.tags.like(f'%"{escaped_tag}"%'),
                )
            )
        if q:
            marker_match = exists().where(
                VideoMarker.video_id == Video.id,
                VideoMarker.value.like(f"%{q}%"),
            )
            query = query.filter(
                or_(
                    Video.filename.like(f"%{q}%"),
                    Video.note.like(f"%{q}%"),
                    marker_match,
                )
            )
        return query

    def list_videos(
        self,
        outing_id: Optional[int] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        location_level1: Optional[str] = None,
        location_level2: Optional[str] = None,
        location_level3: Optional[str] = None,
        tag: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Video]:
        query = self._apply_filters(
            self.session.query(Video),
            outing_id=outing_id, date_from=date_from, date_to=date_to,
            location_level1=location_level1, location_level2=location_level2,
            location_level3=location_level3, tag=tag, q=q,
        )
        return (
            query.order_by(Video.captured_at.desc(), Video.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def count_videos(self, **filters) -> int:
        """Return total count for the same filter set as list_videos."""
        query = self._apply_filters(
            self.session.query(func.count(Video.id)), **filters
        )
        return query.scalar()

    # -- VideoMarker -------------------------------------------------------
    def add_marker(self, marker: VideoMarker) -> VideoMarker:
        self.session.add(marker)
        self.session.commit()
        self.session.refresh(marker)
        return marker

    def get_marker(self, marker_id: int) -> Optional[VideoMarker]:
        return (
            self.session.query(VideoMarker)
            .filter(VideoMarker.id == marker_id)
            .first()
        )

    def list_markers(
        self, video_id: int, kind: Optional[str] = None
    ) -> List[VideoMarker]:
        query = self.session.query(VideoMarker).filter(
            VideoMarker.video_id == video_id
        )
        if kind:
            query = query.filter(VideoMarker.kind == kind)
        # point 用 time、segment 用 in_time 作为统一排序键；
        # 不能直接按两列排序，否则 time 为 NULL 的 segment 会排到最前
        order_key = func.coalesce(VideoMarker.time, VideoMarker.in_time)
        return query.order_by(order_key.asc()).all()

    def update_marker(self, marker_id: int, fields: dict) -> Optional[VideoMarker]:
        marker = self.get_marker(marker_id)
        if not marker:
            return None
        for key, value in fields.items():
            setattr(marker, key, value)
        self.session.commit()
        self.session.refresh(marker)
        return marker

    def delete_marker(self, marker: VideoMarker) -> None:
        self.session.delete(marker)
        self.session.commit()
