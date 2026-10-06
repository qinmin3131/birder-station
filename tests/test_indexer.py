import pytest
from pathlib import Path
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, Photo
from src.db.repository import PhotoRepository
from src.core.indexer import PhotoIndexer


@pytest.fixture
def repo(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return PhotoRepository(Session())


def test_index_folder_adds_only_supported_images(repo, tmp_path):
    indexer = PhotoIndexer(repo)

    # Create a JPEG image
    img_path = tmp_path / "bird.jpg"
    Image.new("RGB", (100, 100), color="red").save(img_path)

    # Create a non-image file
    (tmp_path / "notes.txt").write_text("not a photo")

    photos = indexer.index_folder(tmp_path)

    assert len(photos) == 1
    assert photos[0].filename == "bird.jpg"
    assert photos[0].file_hash is not None


def test_index_folder_skips_duplicate_hash(repo, tmp_path):
    indexer = PhotoIndexer(repo)

    img_path = tmp_path / "bird.jpg"
    Image.new("RGB", (100, 100), color="blue").save(img_path)

    first_run = indexer.index_folder(tmp_path)
    second_run = indexer.index_folder(tmp_path)

    assert len(first_run) == 1
    assert len(second_run) == 0

    all_photos = repo.list_photos()
    assert len(all_photos) == 1


def test_index_folder_respects_supported_formats(repo, tmp_path):
    indexer = PhotoIndexer(repo, supported_formats={".jpg"})

    (tmp_path / "bird.jpg").write_bytes(b"fake jpg")
    (tmp_path / "bird.nef").write_bytes(b"fake raw")

    photos = indexer.index_folder(tmp_path)

    assert len(photos) == 1
    assert photos[0].filename == "bird.jpg"


def test_index_folder_with_stats_counts_indexed_and_skipped(repo, tmp_path):
    indexer = PhotoIndexer(repo)

    img_path = tmp_path / "bird.jpg"
    Image.new("RGB", (100, 100), color="green").save(img_path)
    duplicate = tmp_path / "bird_copy.jpg"
    Image.new("RGB", (100, 100), color="green").save(duplicate)
    (tmp_path / "notes.txt").write_text("not a photo")

    result = indexer.index_folder_with_stats(tmp_path)

    assert result["indexed"] == 1
    assert result["skipped"] == 1
    assert result["errors"] == 0
    assert result["overwritten"] == 0
    assert len(result["photo_ids"]) == 1
    assert result["outing_id"] is None

    result_with_outing = indexer.index_folder_with_stats(tmp_path, overwrite=True, outing_id=5)
    assert result_with_outing["outing_id"] == 5
    assert result_with_outing["overwritten"] == 1
    photo = repo.list_photos()[0]
    assert photo.outing_id == 5


def test_index_folder_with_stats_applies_location_info(repo, tmp_path):
    indexer = PhotoIndexer(repo)

    img_path = tmp_path / "bird.jpg"
    Image.new("RGB", (100, 100), color="blue").save(img_path)

    location_info = {
        "location_tag": "福建_福州_森林公园",
        "location_level1": "福建",
        "location_level2": "福州",
        "location_level3": "森林公园",
    }
    result = indexer.index_folder_with_stats(tmp_path, location_info=location_info)

    assert result["indexed"] == 1
    photo = repo.list_photos()[0]
    assert photo.location_tag == "福建_福州_森林公园"
    assert photo.location_level1 == "福建"
    assert photo.location_level2 == "福州"
    assert photo.location_level3 == "森林公园"


def test_reimport_adds_unprocessed_photo_to_recognition_queue(repo, tmp_path):
    """重新导入时，已存在但未处理的照片应加入识别队列。"""
    indexer = PhotoIndexer(repo)

    img_path = tmp_path / "bird.jpg"
    Image.new("RGB", (100, 100), color="red").save(img_path)

    # 首次导入：照片入库但未处理（无 bird_bbox / 鸟种信息）
    first = indexer.index_folder_with_stats(tmp_path)
    assert first["indexed"] == 1
    assert len(first["photo_ids"]) == 1
    photo_id = first["photo_ids"][0]

    # 二次导入：未处理的照片应重新加入识别队列
    second = indexer.index_folder_with_stats(tmp_path)
    assert second["indexed"] == 0
    assert second["skipped"] == 1
    assert second["reprocessed"] == 1
    assert second["photo_ids"] == [photo_id]


def test_reimport_skips_already_processed_photo(repo, tmp_path):
    """重新导入时，已处理（有鸟种或鸟框）的照片不应加入识别队列。"""
    indexer = PhotoIndexer(repo)

    img_path = tmp_path / "bird.jpg"
    Image.new("RGB", (100, 100), color="green").save(img_path)

    first = indexer.index_folder_with_stats(tmp_path)
    photo_id = first["photo_ids"][0]

    # 模拟照片已被处理：设置鸟种信息
    photo = repo.get_by_id(photo_id)
    photo.primary_bird_cn = "麻雀"
    photo.scientific_name = "Passer montanus"
    repo.session.commit()

    second = indexer.index_folder_with_stats(tmp_path)
    assert second["skipped"] == 1
    assert second["reprocessed"] == 0
    assert second["photo_ids"] == []


def test_reimport_updates_existing_photo_outing_id(repo, tmp_path):
    """重新导入时，已有照片的 outing_id 应修正为当前外拍。"""
    indexer = PhotoIndexer(repo)

    img_path = tmp_path / "bird.jpg"
    Image.new("RGB", (100, 100), color="blue").save(img_path)

    # 首次导入到 outing 1
    first = indexer.index_folder_with_stats(tmp_path, outing_id=1)
    photo_id = first["photo_ids"][0]
    assert repo.get_by_id(photo_id).outing_id == 1

    # 二次导入到 outing 2：已有照片应归入 outing 2
    second = indexer.index_folder_with_stats(tmp_path, outing_id=2)
    assert repo.get_by_id(photo_id).outing_id == 2
