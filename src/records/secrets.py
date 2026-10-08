from pathlib import Path

import yaml


def _secrets_path(base_dir: Path) -> Path:
    return Path(base_dir) / "config" / "secrets.yaml"


def _load(base_dir: Path) -> dict:
    path = _secrets_path(base_dir)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _save(base_dir: Path, data: dict) -> None:
    path = _secrets_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)


def load_birdreport_token(base_dir: Path) -> str | None:
    value = _load(base_dir).get("birdreport", {}).get("token")
    token = str(value).strip() if value is not None else ""
    return token or None


def save_birdreport_token(base_dir: Path, token: str) -> None:
    data = _load(base_dir)
    cleaned = (token or "").strip()
    birdreport = data.setdefault("birdreport", {})
    if cleaned:
        birdreport["token"] = cleaned
    else:
        birdreport.pop("token", None)
    _save(base_dir, data)


def clear_birdreport_token(base_dir: Path) -> None:
    data = _load(base_dir)
    birdreport = data.get("birdreport")
    if isinstance(birdreport, dict):
        birdreport.pop("token", None)
        if not birdreport:
            data.pop("birdreport", None)
    _save(base_dir, data)
