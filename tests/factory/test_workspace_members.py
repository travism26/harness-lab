import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def unlisted_manifests(root: Path) -> list[str]:
    """Repo-root paths of every pyproject.toml under projects/ whose directory
    is not an exact string in the root manifest's tool.uv.workspace.members."""
    members: list[str] = []
    try:
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    listed = data.get("tool", {}).get("uv", {}).get("workspace", {})
    listed = listed.get("members") if isinstance(listed, dict) else None
    if isinstance(listed, list) and all(isinstance(m, str) for m in listed):
        members = listed

    found = []
    for manifest in (root / "projects").rglob("pyproject.toml"):
        relative = manifest.relative_to(root)
        if relative.parent.as_posix() not in members:
            found.append(relative.as_posix())
    return sorted(found)


def test_lab_checkout_has_no_unlisted_manifest():
    assert unlisted_manifests(REPO_ROOT) == []


def test_manifest_outside_members_is_reported(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "root"\n')
    (tmp_path / "projects" / "foo").mkdir(parents=True)
    (tmp_path / "projects" / "foo" / "pyproject.toml").write_text("")
    assert unlisted_manifests(tmp_path) == ["projects/foo/pyproject.toml"]
