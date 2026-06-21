"""Project-local data directory helpers."""

from __future__ import annotations

from pathlib import Path


DATA_DIR_NAME = "data"
AIRFOILS_DIR_NAME = "airfoils"
BLADE_GEOMETRIES_DIR_NAME = "blade_geometries"
DESIGNS_DIR_NAME = "designs"


def project_root() -> Path:
    """Return the source project root."""

    return Path(__file__).resolve().parents[2]


def local_data_dir(root: str | Path | None = None) -> Path:
    """Return the local data directory for a project root."""

    return _root_path(root) / DATA_DIR_NAME


def local_data_dirs(root: str | Path | None = None) -> dict[str, Path]:
    """Return named local data directories."""

    base = local_data_dir(root)
    return {
        "data": base,
        "airfoils": base / AIRFOILS_DIR_NAME,
        "blade_geometries": base / BLADE_GEOMETRIES_DIR_NAME,
        "designs": base / DESIGNS_DIR_NAME,
    }


def ensure_local_data_dirs(root: str | Path | None = None) -> dict[str, Path]:
    """Create local data directories if they do not exist."""

    dirs = local_data_dirs(root)
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def _root_path(root: str | Path | None) -> Path:
    """Return an explicit root or the current source project root."""

    return Path(root).resolve() if root is not None else project_root()
