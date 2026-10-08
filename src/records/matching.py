from dataclasses import dataclass
from datetime import datetime, time
from difflib import SequenceMatcher
from math import asin, cos, radians, sin, sqrt
from typing import Iterable

from .birdreport_client import NormalizedReport


@dataclass(frozen=True)
class ReportCandidate:
    remote_id: str
    score: float
    reasons: tuple[str, ...]
    report: NormalizedReport
    is_bound: bool = False


@dataclass(frozen=True)
class EffortSuggestion:
    start_time: time | None
    duration_minutes: int | None
    source_photo_count: int
    first_captured_at: datetime | None
    last_captured_at: datetime | None
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    split_recommended: bool = False


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    value = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * earth_radius * asin(sqrt(value))


def rank_report_candidates(outing, reports: Iterable[NormalizedReport]) -> list[ReportCandidate]:
    outing_date = str(getattr(outing, "start_date", "") or "").replace("-", "")[:8]
    outing_location = str(getattr(outing, "location_tag", "") or "").strip()
    candidates = []
    for report in reports:
        score = 0.0
        reasons = []
        if report.observed_on == outing_date:
            score += 100
            reasons.append("日期相同")
        similarity = SequenceMatcher(None, outing_location, report.location_name).ratio() if outing_location and report.location_name else 0.0
        score += similarity * 50
        if similarity >= 0.8:
            reasons.append("地点名称高度相似")
        coordinates = (
            getattr(outing, "latitude", None),
            getattr(outing, "longitude", None),
            report.latitude,
            report.longitude,
        )
        if all(value is not None for value in coordinates):
            distance = _distance_km(*coordinates)
            score += max(0, 30 - distance)
            reasons.append(f"坐标相距 {distance:.1f} 公里")
        candidates.append(ReportCandidate(report.remote_id, score, tuple(reasons), report))
    return sorted(candidates, key=lambda item: (-item.score, item.remote_id))


def derive_effort_from_photos(photos) -> EffortSuggestion:
    captured = sorted(
        value for value in (getattr(photo, "captured_at", None) for photo in photos) if isinstance(value, datetime)
    )
    if not captured:
        return EffortSuggestion(None, None, 0, None, None, errors=("没有有效的照片拍摄时间",))
    first, last = captured[0], captured[-1]
    if first.date() != last.date():
        return EffortSuggestion(None, None, len(captured), first, last, errors=("照片时间跨日，需要人工确认",))
    seconds = (last - first).total_seconds()
    if seconds > 12 * 3600:
        return EffortSuggestion(None, None, len(captured), first, last, errors=("照片时间跨度超过 12 小时",))
    gaps = [(right - left).total_seconds() for left, right in zip(captured, captured[1:])]
    split = any(gap > 2 * 3600 for gap in gaps)
    warnings = ("照片间隔超过 2 小时，建议拆分清单",) if split else ()
    duration = max(10, int(seconds / 60 + 0.5))
    return EffortSuggestion(first.time(), duration, len(captured), first, last, warnings=warnings, split_recommended=split)
