"""Tests for project-local storage helpers."""

from __future__ import annotations

from propeller_lab.core.storage import ensure_local_data_dirs, local_data_dirs


def test_local_data_dirs_names(tmp_path):
    """Local data directory helpers should expose stable names."""

    dirs = local_data_dirs(tmp_path)

    assert dirs["data"] == tmp_path / "data"
    assert dirs["airfoils"] == tmp_path / "data" / "airfoils"
    assert dirs["blade_geometries"] == tmp_path / "data" / "blade_geometries"
    assert dirs["designs"] == tmp_path / "data" / "designs"


def test_ensure_local_data_dirs_creates_directories(tmp_path):
    """Directory creation helper should create the full local data tree."""

    dirs = ensure_local_data_dirs(tmp_path)

    for path in dirs.values():
        assert path.exists()
        assert path.is_dir()
