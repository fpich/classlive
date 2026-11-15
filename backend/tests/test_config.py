import pytest
from classlive.config import load_settings


def test_config(tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text('classlive:\n  storage:\n    workdir: "/tmp/classlive"\n', encoding="utf-8")
    settings = load_settings(cfg)
    assert settings.port == 8080
    assert settings.events_root.name == "Evts"


def test_relative_workdir_rejected(tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text('classlive:\n  storage:\n    workdir: "relative"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_settings(cfg)
