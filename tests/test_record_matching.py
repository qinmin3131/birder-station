from datetime import datetime, time
from types import SimpleNamespace

import pytest

from src.records.birdreport_client import NormalizedReport
from src.records.matching import derive_effort_from_photos, rank_report_candidates


def test_candidates_are_ranked_but_not_bound():
    outing = SimpleNamespace(start_date="20261007", location_tag="奥森北园", latitude=None, longitude=None)
    reports = [
        NormalizedReport("R1", "20261007", "柳荫公园"),
        NormalizedReport("R2", "20261007", "奥森北园"),
    ]
    candidates = rank_report_candidates(outing, reports)
    assert [candidate.remote_id for candidate in candidates] == ["R2", "R1"]
    assert all(candidate.is_bound is False for candidate in candidates)


def test_photo_effort_detects_two_hour_gap():
    photos = [SimpleNamespace(captured_at=datetime.fromisoformat(value)) for value in ["2026-10-07T08:00:00", "2026-10-07T08:05:00", "2026-10-07T10:06:00"]]
    result = derive_effort_from_photos(photos)
    assert result.start_time == time(8, 0)
    assert result.duration_minutes == 126
    assert result.split_recommended is True


@pytest.mark.parametrize(
    ("timestamps", "duration", "has_error"),
    [
        (["2026-10-07T08:00:00"], 10, False),
        (["2026-10-07T08:00:00", "2026-10-07T08:05:00"], 10, False),
        (["2026-10-07T08:00:00", "2026-10-07T20:00:00"], 720, False),
        (["2026-10-07T08:00:00", "2026-10-07T20:00:01"], None, True),
        (["2026-10-07T23:59:00", "2026-10-08T00:01:00"], None, True),
    ],
)
def test_effort_boundaries(timestamps, duration, has_error):
    photos = [SimpleNamespace(captured_at=datetime.fromisoformat(value)) for value in reversed(timestamps)]
    result = derive_effort_from_photos(photos)
    assert result.duration_minutes == duration
    assert bool(result.errors) is has_error


def test_missing_photo_times_returns_explainable_error():
    result = derive_effort_from_photos([SimpleNamespace(captured_at=None)])
    assert result.duration_minutes is None
    assert result.errors == ("没有有效的照片拍摄时间",)
