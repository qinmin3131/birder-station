from dataclasses import dataclass
from typing import Any, Callable

import requests


class BirdReportError(Exception):
    def __init__(self, message: str, category: str):
        super().__init__(message)
        self.category = category


class BirdReportAuthError(BirdReportError):
    def __init__(self, message: str = "观鸟记录中心登录凭证无效或已过期"):
        super().__init__(message, "auth")


@dataclass(frozen=True)
class NormalizedSpecies:
    name: str
    scientific_name: str | None = None
    count: str = "X"


@dataclass(frozen=True)
class NormalizedReport:
    remote_id: str
    observed_on: str
    location_name: str
    latitude: float | None = None
    longitude: float | None = None
    species: tuple[NormalizedSpecies, ...] = ()
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class ConnectionResult:
    connected: bool
    username: str | None = None


class BirdReportClient:
    def __init__(
        self,
        base_url: str,
        token_provider: Callable[[], str | None],
        session: requests.Session | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token_provider = token_provider
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        token = (self.token_provider() or "").strip()
        if not token:
            raise BirdReportAuthError("请先配置观鸟记录中心 Token")
        return {"X-Auth-Token": token}

    def _get_json(self, path: str, params: dict[str, str] | None = None) -> Any:
        try:
            response = self.session.get(
                f"{self.base_url}{path}",
                headers=self._headers(),
                params=params,
                timeout=20,
            )
        except BirdReportError:
            raise
        except requests.RequestException as exc:
            raise BirdReportError("无法连接观鸟记录中心，请稍后重试", "network") from exc

        if response.status_code in (401, 403):
            raise BirdReportAuthError()
        if response.status_code == 429:
            raise BirdReportError("观鸟记录中心请求过于频繁，请稍后重试", "rate_limit")
        if response.status_code < 200 or response.status_code >= 300:
            raise BirdReportError("观鸟记录中心暂时不可用", "network")
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise BirdReportError("观鸟记录中心返回了无法识别的数据", "invalid_response") from exc
        if payload is None:
            raise BirdReportError("观鸟记录中心返回了空数据", "invalid_response")
        return payload

    def test_connection(self) -> ConnectionResult:
        payload = self._get_json("/api/user")
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        username = data.get("username") if isinstance(data, dict) else None
        return ConnectionResult(connected=True, username=username)

    def fetch_reports(self, date_from: str, date_to: str) -> list[NormalizedReport]:
        payload = self._get_json(
            "/api/reports",
            params={"dateFrom": date_from, "dateTo": date_to},
        )
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise BirdReportError("观鸟记录中心报告格式已变化", "invalid_response")
        try:
            return [self._normalize_report(row) for row in rows]
        except (KeyError, TypeError, ValueError) as exc:
            raise BirdReportError("观鸟记录中心报告缺少必要字段", "invalid_response") from exc

    @staticmethod
    def _normalize_report(row: dict[str, Any]) -> NormalizedReport:
        remote_id = str(row["id"]).strip()
        raw_date = str(row["date"]).strip()
        if not remote_id or not raw_date:
            raise ValueError("empty identifiers")
        observed_on = raw_date.replace("-", "")[:8]
        if len(observed_on) != 8 or not observed_on.isdigit():
            raise ValueError("invalid date")
        species_rows = row.get("species") or []
        if not isinstance(species_rows, list):
            raise ValueError("invalid species")
        species = tuple(
            NormalizedSpecies(
                name=str(item.get("name") or item.get("cnName") or "").strip(),
                scientific_name=(str(item.get("scientificName")).strip() if item.get("scientificName") else None),
                count=str(item.get("count") or "X"),
            )
            for item in species_rows
        )
        if any(not item.name for item in species):
            raise ValueError("species name missing")
        return NormalizedReport(
            remote_id=remote_id,
            observed_on=observed_on,
            location_name=str(row.get("place") or row.get("location") or "").strip(),
            latitude=float(row["latitude"]) if row.get("latitude") is not None else None,
            longitude=float(row["longitude"]) if row.get("longitude") is not None else None,
            species=species,
            raw=dict(row),
        )
