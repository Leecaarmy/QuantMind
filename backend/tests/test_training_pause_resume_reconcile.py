"""训练 pause 遗忘恢复（resume_orphaned_paused_containers）单测。

覆盖：
- 无 resumed_at 的孤儿文件 → 停止中的容器被 start，已在跑的不动，已删除的记错跳过；
- 有 resumed_at 的文件 → 跳过；
- paused_at 超 7 天 → 跳过并告警，不拉起（防止复活刻意久停的容器）；
- 坏文件 → 记错跳过；函数永不抛异常。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

try:
    from backend.services.engine.training import local_docker_orchestrator as orch
except Exception as exc:  # pragma: no cover - 重依赖缺失时跳过
    pytest.skip(f"cannot import orchestrator: {exc}", allow_module_level=True)


class _FakeContainer:
    def __init__(self, name: str, status: str = "exited"):
        self.name = name
        self.status = status
        self.started = False

    def start(self):
        self.started = True
        self.status = "running"


class _FakeContainers:
    def __init__(self, existing: dict[str, _FakeContainer]):
        self._existing = existing

    def get(self, name: str) -> _FakeContainer:
        if name not in self._existing:
            raise KeyError(f"no such container: {name}")
        return self._existing[name]


class _FakeClient:
    def __init__(self, existing: dict[str, _FakeContainer]):
        self.containers = _FakeContainers(existing)


def _write_state(root, run_id: str, payload: dict | str) -> None:
    d = root / run_id
    d.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload)
    (d / ".paused_containers.json").write_text(text, encoding="utf-8")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _patch_client(monkeypatch, existing: dict[str, _FakeContainer]):
    fake_client = _FakeClient(existing)

    class _FakeDockerClient:
        @staticmethod
        def from_env():
            return fake_client

    monkeypatch.setattr(orch, "DockerClient", _FakeDockerClient)
    return fake_client


def test_orphan_file_resumes_stopped_and_skips_running(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    _write_state(
        tmp_path,
        "run_orphan",
        {
            "run_id": "run_orphan",
            "paused_at": now.isoformat(timespec="seconds"),
            "containers": ["c_stopped", "c_running", "c_gone"],
        },
    )
    existing = {
        "c_stopped": _FakeContainer("c_stopped", "exited"),
        "c_running": _FakeContainer("c_running", "running"),
    }
    _patch_client(monkeypatch, existing)

    stats = _run(orch.resume_orphaned_paused_containers(jobs_root=tmp_path))

    assert stats["scanned"] == 1
    assert stats["resumed"] == 2  # c_stopped 被拉起，c_running 原本就在跑
    assert stats["errors"] == 1  # c_gone 不存在
    assert existing["c_stopped"].started is True
    assert existing["c_running"].started is False  # 已在跑的不重复 start

    data = json.loads(
        (tmp_path / "run_orphan" / ".paused_containers.json").read_text(encoding="utf-8")
    )
    assert data["resumed_at"]
    assert data["resumed_by"] == "startup-reconcile"
    assert set(data["resumed"]) == {"c_stopped", "c_running"}


def test_resumed_and_ancient_files_are_skipped(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    _write_state(
        tmp_path,
        "run_done",
        {
            "run_id": "run_done",
            "paused_at": now.isoformat(timespec="seconds"),
            "containers": ["c_old"],
            "resumed_at": now.isoformat(timespec="seconds"),
            "resumed": ["c_old"],
        },
    )
    _write_state(
        tmp_path,
        "run_ancient",
        {
            "run_id": "run_ancient",
            "paused_at": (now - timedelta(days=30)).isoformat(timespec="seconds"),
            "containers": ["c_ancient"],
        },
    )
    existing = {
        "c_old": _FakeContainer("c_old", "exited"),
        "c_ancient": _FakeContainer("c_ancient", "exited"),
    }
    _patch_client(monkeypatch, existing)

    stats = _run(orch.resume_orphaned_paused_containers(jobs_root=tmp_path))

    assert stats["scanned"] == 2
    assert stats["resumed"] == 0
    assert stats["skipped"] == 2
    assert existing["c_old"].started is False
    assert existing["c_ancient"].started is False


def test_corrupt_file_counts_error_and_never_raises(tmp_path, monkeypatch):
    _write_state(tmp_path, "run_bad", "not-json{{{")
    _patch_client(monkeypatch, {})

    stats = _run(orch.resume_orphaned_paused_containers(jobs_root=tmp_path))

    assert stats["scanned"] == 1
    assert stats["errors"] == 1
    assert stats["resumed"] == 0


def test_missing_jobs_root_reports_disabled(tmp_path, monkeypatch):
    _patch_client(monkeypatch, {})

    stats = _run(
        orch.resume_orphaned_paused_containers(jobs_root=tmp_path / "no-such-dir")
    )

    assert "disabled" in stats
    assert stats["resumed"] == 0
