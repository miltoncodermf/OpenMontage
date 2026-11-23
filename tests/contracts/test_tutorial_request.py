"""Fast checks for lib/tutorial_request.py (the /tutorial plugin's input resolver)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from lib import tutorial_request as tr


def _profile(root: Path, pid: str, locked: bool = True, standin: bool = False) -> None:
    d = root / pid
    d.mkdir(parents=True)
    (d / "profile.json").write_text(json.dumps({"locked": locked, "standin": standin}))


@pytest.fixture
def env(tmp_path):
    work = tmp_path / "work"
    (work / "myrepo").mkdir(parents=True)
    (work / "spec.pdf").write_bytes(b"%PDF-1.4\n%fake\n")
    (work / "notes.md").write_text("# Notes\n\nHello tutorial.\n")
    (work / "photo.png").write_bytes(b"\x89PNG")
    projects = tmp_path / "projects"
    profiles = tmp_path / "profiles"
    _profile(profiles, "ming")
    _profile(profiles, "standin-dev", standin=True)
    return work, projects, profiles


def test_repo_url_parts():
    assert tr.repo_url_parts("https://github.com/org/repo") == ("https://github.com/org/repo.git", "repo", None)
    assert tr.repo_url_parts("https://github.com/org/repo.git") == ("https://github.com/org/repo.git", "repo", None)
    assert tr.repo_url_parts("https://github.com/org/repo/tree/main/docs/api") == ("https://github.com/org/repo.git", "repo", "docs/api")
    assert tr.repo_url_parts("https://docs.python.org/3/library") is None
    assert tr.repo_url_parts("https://github.com/org") is None


def test_classify_mixed(env):
    work, _, _ = env
    c = tr.classify([".", "./myrepo", "spec.pdf", "notes.md", "https://docs.x.com/guide",
                     "https://github.com/a/b", "how", "Node.js works"], work)
    assert [r.get("path") for r in c.repos[:2]] == [str(work.resolve()), str((work / "myrepo").resolve())]
    assert c.repos[2] == {"clone": "https://github.com/a/b.git", "name": "b"}
    assert c.pdfs == [str((work / "spec.pdf").resolve())]
    assert c.docs == [(work / "notes.md").resolve()]
    assert c.urls == ["https://docs.x.com/guide"]
    assert c.topic_words == ["how", "Node.js works"]


def test_classify_errors(env):
    work, _, _ = env
    with pytest.raises(tr.RequestError, match="path not found"):
        tr.classify(["./missing"], work)
    with pytest.raises(tr.RequestError, match="unsupported file type"):
        tr.classify(["photo.png"], work)


def test_build_project_topic_and_folder(env):
    work, projects, profiles = env
    s = tr.build_project(["./myrepo", "how caching works"], cwd=work, length_min=4, projects_dir=projects, profile_root=profiles)
    pdir = Path(s["project_dir"])
    spec = yaml.safe_load((pdir / "inputs" / "inputs.yaml").read_text())
    assert spec == {"topic": "how caching works", "repos": [{"path": str((work / "myrepo").resolve())}]}
    req = json.loads((pdir / "inputs" / "request.json").read_text())
    assert req["presenter_profile"] == "ming" and req["length_min"] == 4 and req["aspect"] == "16:9"
    assert json.loads((pdir / "project.json").read_text())["pipeline_type"] == "topic-tutorial"
    assert s["project_id"].startswith("tutorial-how-caching-works-")


def test_unique_ids_and_presenter_none(env):
    work, projects, profiles = env
    a = tr.build_project(["a topic here"], cwd=work, projects_dir=projects, profile_root=profiles)
    b = tr.build_project(["a topic here"], cwd=work, presenter="none", projects_dir=projects, profile_root=profiles)
    assert a["project_id"] != b["project_id"] and b["project_id"].endswith("-2")
    assert b["request"]["presenter_profile"] is None


def test_presenter_rules(env):
    work, projects, profiles = env
    _profile(profiles, "other")
    with pytest.raises(tr.RequestError, match="several locked"):
        tr.build_project(["a topic"], cwd=work, projects_dir=projects, profile_root=profiles)
    with pytest.raises(tr.RequestError, match="not a locked profile"):
        tr.build_project(["a topic"], cwd=work, presenter="nobody", projects_dir=projects, profile_root=profiles)
    s = tr.build_project(["a topic"], cwd=work, presenter="other", projects_dir=projects, profile_root=profiles)
    assert s["request"]["presenter_profile"] == "other"


def test_bad_request_leaves_no_project(env):
    work, projects, profiles = env
    with pytest.raises(tr.RequestError):
        tr.build_project([], cwd=work, projects_dir=projects, profile_root=profiles)
    with pytest.raises(tr.RequestError):
        tr.build_project(["x"], cwd=work, aspect="4:3", projects_dir=projects, profile_root=profiles)
    assert not projects.exists() or not any(projects.iterdir())


def test_github_url_is_cloned(env, monkeypatch):
    work, projects, profiles = env
    calls = []

    def fake_clone(url, dest):
        calls.append(url)
        dest.mkdir(parents=True)
        return dest

    monkeypatch.setattr(tr, "clone_repo", fake_clone)
    s = tr.build_project(["https://github.com/org/cool-lib/tree/main/src"], cwd=work, projects_dir=projects, profile_root=profiles)
    assert calls == ["https://github.com/org/cool-lib.git"]
    repo = s["inputs"]["repos"][0]
    assert repo["path"].endswith("inputs/repos/cool-lib") and repo["focus"] == ["src"]


def test_failed_clone_cleans_up(env, monkeypatch):
    work, projects, profiles = env

    def boom(url, dest):
        raise tr.RequestError("git clone failed")

    monkeypatch.setattr(tr, "clone_repo", boom)
    with pytest.raises(tr.RequestError, match="clone failed"):
        tr.build_project(["https://github.com/org/x"], cwd=work, projects_dir=projects, profile_root=profiles)
    assert not any(projects.iterdir())


@pytest.mark.skipif(not shutil.which("cupsfilter"), reason="macOS cupsfilter not available")
def test_markdown_converted_to_pdf(env):
    work, projects, profiles = env
    s = tr.build_project(["notes.md"], cwd=work, projects_dir=projects, profile_root=profiles)
    pdf = Path(s["inputs"]["pdfs"][0])
    assert pdf.parent.name == "docs" and pdf.read_bytes().startswith(b"%PDF")
    assert (work / "notes.md").read_text().startswith("# Notes")  # source untouched


def test_cli_json(env, capsys, monkeypatch):
    work, projects, profiles = env
    monkeypatch.setattr("lib.checkpoint.PROJECTS_DIR", projects)
    monkeypatch.setenv("OPENMONTAGE_PROFILE_ROOT", str(profiles))
    rc = tr.main(["--cwd", str(work), "./myrepo", "--length", "3", "intro to the repo"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["ok"] and out["request"]["length_min"] == 3
    rc = tr.main(["--cwd", str(work), "./nope"])
    assert rc == 2 and json.loads(capsys.readouterr().out)["ok"] is False
