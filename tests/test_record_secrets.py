import yaml

from src.records.secrets import (
    clear_birdreport_token,
    load_birdreport_token,
    save_birdreport_token,
)


def test_secret_round_trip_preserves_other_settings(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "secrets.yaml").write_text("cloud:\n  enabled: true\n", encoding="utf-8")

    save_birdreport_token(tmp_path, " token-value ")

    assert load_birdreport_token(tmp_path) == "token-value"
    saved = yaml.safe_load((config_dir / "secrets.yaml").read_text(encoding="utf-8"))
    assert saved["cloud"]["enabled"] is True
    clear_birdreport_token(tmp_path)
    assert load_birdreport_token(tmp_path) is None
    assert yaml.safe_load((config_dir / "secrets.yaml").read_text(encoding="utf-8"))["cloud"]["enabled"] is True


def test_blank_token_is_not_persisted(tmp_path):
    save_birdreport_token(tmp_path, "   ")
    assert load_birdreport_token(tmp_path) is None
