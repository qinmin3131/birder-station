import numpy as np
import pytest
from pathlib import Path
from PIL import Image
from unittest.mock import MagicMock

from src.core import indexer as indexer_module
from src.core.indexer import load_image


def test_load_jpeg(tmp_path):
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    path = tmp_path / "test.jpg"
    Image.fromarray(img).save(path)

    arr = load_image(path)

    assert arr.shape == (100, 100, 3)


def test_load_raw_uses_rawpy_when_available(tmp_path, monkeypatch):
    fake_raw = np.zeros((120, 160, 3), dtype=np.uint8)

    mock_rawpy = MagicMock()
    mock_raw_object = MagicMock()
    mock_raw_object.postprocess.return_value = fake_raw
    mock_rawpy.imread.return_value.__enter__ = MagicMock(return_value=mock_raw_object)
    mock_rawpy.imread.return_value.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr(indexer_module, "RAWPY_AVAILABLE", True)
    monkeypatch.setattr(indexer_module, "rawpy", mock_rawpy)

    raw_path = tmp_path / "test.nef"
    raw_path.write_bytes(b"fake raw data")

    arr = load_image(raw_path)

    assert arr.shape == (120, 160, 3)
    mock_rawpy.imread.assert_called_once_with(str(raw_path))


def test_load_raw_raises_when_rawpy_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer_module, "RAWPY_AVAILABLE", False)

    raw_path = tmp_path / "test.nef"
    raw_path.write_bytes(b"fake raw data")

    with pytest.raises(RuntimeError, match="rawpy is not installed"):
        load_image(raw_path)
