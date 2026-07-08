from __future__ import annotations

from app.config import Settings
from app.config import _default_project_data_dir, _migrate_legacy_database


def test_default_project_data_dir_points_to_writer_data():
    data_dir = _default_project_data_dir()

    assert data_dir.name == "data"
    assert data_dir.parent.name == "writer"


def test_migrate_legacy_database_copies_only_when_new_db_missing(tmp_path):
    legacy = tmp_path / "legacy" / "LamWriter"
    target = tmp_path / "target"
    legacy.mkdir(parents=True)
    target.mkdir()
    (legacy / "lamwriter.db").write_bytes(b"old-db")

    copied = _migrate_legacy_database(target, legacy)

    assert copied is True
    assert (target / "lamwriter.db").read_bytes() == b"old-db"


def test_migrate_legacy_database_does_not_overwrite_existing_db(tmp_path):
    legacy = tmp_path / "legacy" / "LamWriter"
    target = tmp_path / "target"
    legacy.mkdir(parents=True)
    target.mkdir()
    (legacy / "lamwriter.db").write_bytes(b"old-db")
    (target / "lamwriter.db").write_bytes(b"new-db")

    copied = _migrate_legacy_database(target, legacy)

    assert copied is False
    assert (target / "lamwriter.db").read_bytes() == b"new-db"


def test_explicit_data_dir_wins_over_project_default(tmp_path):
    explicit = tmp_path / "explicit"

    settings = Settings(data_dir=str(explicit), _env_file=None)

    assert settings.data_dir == str(explicit)
    assert settings.database_url.endswith("lamwriter.db")
    assert explicit.exists()
