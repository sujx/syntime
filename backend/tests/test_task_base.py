"""§5.1 Celery 任务公共基类单测：互斥锁语义（不依赖 DB / 真实 Redis）。

用内存 FakeRedis 替代 Redis，验证 SET NX EX 互斥、令牌比对释放、异常路径释放、
互斥占用时跳过并记审计。audit_log 实际落库由 DB 测试覆盖（test_audit.py）。
"""

from typing import cast

import pytest
import redis
from celery import Celery
from celery.exceptions import Ignore

import common.tasks as tasks_mod
from common.tasks import SynTimeTask

app = Celery("test", broker="memory://", backend="cache+memory://")

CALLS: list[str] = []


class FakeRedis:
    """最小 Redis 替身：实现互斥锁用到的 set(nx,ex) 与 eval(比对令牌删除)。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self._audits: list[dict] = []

    def set(self, key, value, nx=False, ex=None):  # noqa: ANN001, ANN201
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def eval(self, script, numkeys, *keys_and_args):  # noqa: ANN001, ANN201
        key, token = keys_and_args[0], keys_and_args[1]
        if self.store.get(key) == token:
            del self.store[key]
            return 1
        return 0


class _NoRetryTask(SynTimeTask):
    """关闭自动重试，便于验证异常路径的锁释放（重试语义归 §5.1 类属性，非本测）。"""

    abstract = True
    autoretry_for: tuple[type[BaseException], ...] = ()


@app.task(base=SynTimeTask, bind=True, name="t.succ")
def succ(self, x):  # noqa: ANN001, ANN201
    CALLS.append(f"succ:{x}")
    return x * 2


@app.task(base=_NoRetryTask, bind=True, name="t.boom")
def boom(self):  # noqa: ANN001, ANN201
    CALLS.append("boom")
    raise RuntimeError("boom")


class _NoLockTask(SynTimeTask):
    abstract = True

    def get_lock_key(self, args, kwargs):  # noqa: ANN001, ANN201
        return None


@app.task(base=_NoLockTask, bind=True, name="t.nolock")
def nolock(self, x):  # noqa: ANN001, ANN201
    CALLS.append(f"nolock:{x}")
    return x


@pytest.fixture
def fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(tasks_mod, "get_lock_client", lambda: fake)
    audits: list[dict] = []
    monkeypatch.setattr(
        tasks_mod, "record_audit", lambda action, **kw: audits.append({"action": action, **kw})
    )
    CALLS.clear()
    fake._audits = audits  # 便于断言
    return fake


def test_task_runs_and_releases_lock(fake_redis):
    assert succ(3) == 6
    assert CALLS == ["succ:3"]
    assert fake_redis.store == {}  # 锁已释放


def test_mutex_busy_raises_ignore_and_skips_body(fake_redis):
    fake_redis.store["syntime:mutex:t.succ"] = "held-by-other"
    with pytest.raises(Ignore):
        succ(3)
    assert CALLS == []  # body 未执行
    # 互斥跳过写审计（result=skipped）
    assert any(a.get("result") == "skipped" for a in fake_redis._audits)


def test_lock_released_on_body_error(fake_redis):
    with pytest.raises(RuntimeError):
        boom()
    assert fake_redis.store == {}  # finally 释放


def test_no_lock_key_skips_mutex(fake_redis):
    assert nolock(5) == 5
    assert CALLS == ["nolock:5"]
    assert fake_redis.store == {}  # 从未加锁


def test_acquire_and_release_primitives():
    fake = FakeRedis()
    client = cast("redis.Redis", fake)
    token = tasks_mod.acquire_mutex(client, "k", 60)
    assert token is not None
    assert "syntime:mutex:k" in fake.store
    # 二次获取失败（NX）
    assert tasks_mod.acquire_mutex(client, "k", 60) is None
    # 错误令牌不释放
    tasks_mod.release_mutex(client, "k", "wrong-token")
    assert "syntime:mutex:k" in fake.store
    # 正确令牌释放
    tasks_mod.release_mutex(client, "k", token)
    assert fake.store == {}
