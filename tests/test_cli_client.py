"""CLI-4：EmbeddedAgentClient — 多 Thread、FIFO、steer、审批绑定、幂等、快照。

全部走真实 Harness 生命周期（ThreadSessionManager + EventBroker），Runner 用
可阻塞的 FakeRunner 模拟工具钩子等待。
"""

from __future__ import annotations

import asyncio

import pytest

from app.client import EmbeddedAgentClient
from app.config import ReplConfig
from electromind import RunEnd, TextDelta, ToolCallBegin, ToolResult

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeThread:
    def __init__(self, thread_id):
        self.id = thread_id
        self.meta = {}
        self.project_path = ""
        self.spec = None

    def load_metainfo(self):
        return self.meta

    def save_metainfo(self, meta):
        self.meta = meta


class FakeMessages:
    def __init__(self):
        self.data = []


class FakeInbound:
    def __init__(self, runner):
        self.runner = runner

    def permit(self, tool_call_id):
        self.runner.permitted.append(tool_call_id)

    def deny(self, tool_call_id, reason=""):
        self.runner.denied.append((tool_call_id, reason))


class FakeSandbox:
    def __init__(self, workdir="/workspace"):
        self.workdir = workdir
        self.backend = None


class BlockingRunner:
    """run() 在首个事件后阻塞到 ``release()``；再次调用时若已 release 立即完成。

    模拟真实工具钩子阻塞（wait_tool_permit）。
    """

    def __init__(self, thread_id, events=None, workdir="/workspace"):
        self.thread_id = thread_id
        self.thread = FakeThread(thread_id)
        self.messages = FakeMessages()
        self.sandbox = FakeSandbox(workdir)
        self.agent = None
        self.events = events or [TextDelta("开始")]
        self.released = asyncio.Event()
        self.cancelled = False
        self.fail_gate: asyncio.Event | None = (
            None  # 设置后：等待 → 抛异常（provider 崩溃）
        )
        self.prompts: list[str] = []
        self.steered: list[str] = []
        self.denied: list[tuple[str, str]] = []
        self.permitted: list[str] = []
        self.closed = False

    async def run(self, prompt):
        self.prompts.append(prompt)
        self.cancelled = False  # 取消是 per-run 的，新 Run 重置
        for event in self.events:
            yield event
            if isinstance(event, ToolCallBegin):
                pass  # 模拟钩子：真实 runner 在这里 wait_tool_permit
        if self.fail_gate is not None:
            await self.fail_gate.wait()
            raise RuntimeError("provider boom")  # 下一检查点前异常
        await self.released.wait()
        yield RunEnd(
            turn=1, stop_reason="cancelled" if self.cancelled else "no_tool_calls"
        )

    def cancel_run(self):
        """模拟 Runner.cancel_run：下一次迭代产出 RunEnd(cancelled)。"""
        self.cancelled = True
        self.released.set()

    def steer(self, text):
        self.steered.append(text)

    @property
    def inbound(self):
        return FakeInbound(self)

    async def close(self):
        self.closed = True


class Collector:
    def __init__(self):
        self.lines: list[dict] = []

    def __call__(self, line: dict) -> None:
        self.lines.append(line)

    def methods(self, thread_id: str | None = None) -> list[str]:
        return [
            line["method"]
            for line in self.lines
            if thread_id is None or line["params"].get("thread_id") == thread_id
        ]


def _config(**kwargs) -> ReplConfig:
    base = dict(api_key="sk-test-key")
    base.update(kwargs)
    return ReplConfig(**base)


def _client(runners: dict[str, BlockingRunner], collector: Collector, config=None):
    async def factory(tid: str):
        runner = runners.get(tid)
        if runner is None:
            # 不同 Thread 用不同工作区，避免写租约（Gate 1）互斥
            runner = BlockingRunner(tid, workdir=f"/workspace/{tid}")
            runners[tid] = runner
        return runner

    return EmbeddedAgentClient(
        factory, config=config or _config(), event_sink=collector
    )


async def _wait_for(
    collector: Collector,
    method: str,
    timeout: float = 2.0,
    thread_id: str | None = None,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        methods = collector.methods(thread_id)
        if method in methods:
            return
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"等待事件超时: {method} (已见 {methods})")
        await asyncio.sleep(0.005)


# ---------------------------------------------------------------------------
# 多 Thread：并行运行、取消隔离、Runner 不关闭
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_threads_run_in_parallel():
    collector = Collector()
    runners: dict[str, BlockingRunner] = {}
    client = _client(runners, collector)

    await client.send_input("thread-a", "任务A")
    await client.send_input("thread-b", "任务B")

    # 两个 Thread 同时有活动 Run（不同工作区，避免写租约互斥）
    assert client.has_active_run("thread-a")
    assert client.has_active_run("thread-b")

    # 释放 A：A 完成，B 不受影响
    runners["thread-a"].released.set()
    await _wait_for(collector, "run/completed", thread_id="thread-a")
    assert not client.has_active_run("thread-a")
    assert client.has_active_run("thread-b")

    runners["thread-b"].released.set()
    await _wait_for(collector, "run/completed", thread_id="thread-b")
    assert not client.has_active_run("thread-b")


@pytest.mark.asyncio
async def test_workspace_write_lease_serializes_same_workdir():
    """Gate 1：同一工作区的写 Run 串行；持有者释放后唤醒等待者。"""
    collector = Collector()
    runner_a = BlockingRunner("thread-a", workdir="/shared")
    runner_b = BlockingRunner("thread-b", workdir="/shared")
    runners = {"thread-a": runner_a, "thread-b": runner_b}

    async def factory(tid):
        return runners[tid]

    client = EmbeddedAgentClient(factory, config=_config(), event_sink=collector)

    await client.send_input("thread-a", "任务A", delivery="auto")
    await client.send_input("thread-b", "任务B", delivery="auto")

    # 同一写租约：B 等待，不启动第二个 Run
    await _wait_for(collector, "item/delta", thread_id="thread-a")
    assert client.has_active_run("thread-a")
    assert not client.has_active_run("thread-b")
    assert runner_b.prompts == []

    # 释放 A → 唤醒 B → B 启动
    runner_a.released.set()
    await _wait_for(collector, "run/completed", thread_id="thread-a")
    deadline = asyncio.get_running_loop().time() + 2.0
    while not client.has_active_run("thread-b"):
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("B 未被唤醒")
        await asyncio.sleep(0.005)
    runner_b.released.set()
    await _wait_for(collector, "run/completed", thread_id="thread-b")


@pytest.mark.asyncio
async def test_cancel_bound_to_run_id_rejects_stale():
    """验收 P0-4：旧 Run 的迟到 Cancel 不得取消同 Thread 的新 Run。"""
    collector = Collector()
    runner = BlockingRunner("thread-t1")
    runners = {"thread-t1": runner}

    async def factory(tid):
        return runners[tid]

    client = EmbeddedAgentClient(factory, config=_config(), event_sink=collector)
    await client.send_input("thread-t1", "任务", delivery="auto")
    await _wait_for(collector, "run/started", thread_id="thread-t1")

    # 绑定的 run_id 与活动 Run 一致 → 取消成功
    session = client.manager.get_session("thread-t1")
    stale_run_id = session.active_run_id  # 旧 run_id（先捕获）
    assert await client.cancel_run("thread-t1", stale_run_id) is True
    await _wait_for(collector, "run/completed", thread_id="thread-t1")

    # 新 Run 启动后，旧 run_id 的迟到 Cancel → 拒绝（不触碰新 Run）
    runner.released.set()  # 若上一步 cancel 未生效则超时保护
    collector.lines.clear()  # 清掉旧事件，等新 Run 的 run/started
    await client.send_input("thread-t1", "任务2", delivery="auto")
    await _wait_for(collector, "run/started", thread_id="thread-t1")
    new_session = client.manager.get_session("thread-t1")
    assert new_session.active_run_id != stale_run_id

    ok = await client.cancel_run("thread-t1", stale_run_id)
    assert ok is False  # 迟到 Cancel 被拒绝
    # 新 Run 正常完成（stop_reason 非 cancelled）——迟到 Cancel 未触碰它
    await _wait_for(collector, "run/completed", thread_id="thread-t1")
    completed = [
        line["params"]
        for line in collector.lines
        if line["method"] == "run/completed"
        and line["params"].get("thread_id") == "thread-t1"
    ]
    assert completed[-1]["stop_reason"] == "no_tool_calls"


@pytest.mark.asyncio
async def test_cancel_a_does_not_affect_b():
    collector = Collector()
    runners: dict[str, BlockingRunner] = {}
    client = _client(runners, collector)

    await client.send_input("thread-a", "任务A")
    await client.send_input("thread-b", "任务B")
    session_a = client.manager.get_session("thread-a")
    assert await client.cancel_run("thread-a", session_a.active_run_id) is True

    # A 的 run 收到取消 → RunEnd(cancelled) → run/completed(cancelled)
    await _wait_for(collector, "run/completed", thread_id="thread-a")
    assert not client.has_active_run("thread-a")
    assert client.has_active_run("thread-b")  # B 继续


@pytest.mark.asyncio
async def test_close_cleans_all_runners_and_tasks():
    """无泄漏审计：close() 后 Runner 缓存与 Run 任务全部清空。"""
    collector = Collector()
    runners: dict[str, BlockingRunner] = {}
    client = _client(runners, collector)

    await client.send_input("thread-a", "任务A")
    await client.send_input("thread-b", "任务B")
    await client.send_input("thread-c", "任务C")
    assert len(client._runners) == 3

    await client.close()

    assert client._runners == {}
    assert client._run_tasks == {}
    assert all(r.closed for r in runners.values())
    assert client._closed is True


@pytest.mark.asyncio
async def test_thread_switch_keeps_runners_open():
    collector = Collector()
    runners: dict[str, BlockingRunner] = {}
    client = _client(runners, collector)

    await client.send_input("thread-a", "任务A")
    await client.send_input("thread-b", "任务B")
    # “切换视图” = 不动 Runner
    assert client.runner("thread-a") is runners["thread-a"]
    assert client.runner("thread-b") is runners["thread-b"]
    assert runners["thread-a"].closed is False

    await client.close()
    assert runners["thread-a"].closed is True
    assert runners["thread-b"].closed is True


# ---------------------------------------------------------------------------
# FIFO enqueue / IMMEDIATE steer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_fifo_after_run_completes():
    collector = Collector()
    runner = BlockingRunner("thread-t1")
    runners = {"thread-t1": runner}

    async def factory(tid):
        return runners[tid]

    client = EmbeddedAgentClient(factory, config=_config(), event_sink=collector)

    await client.send_input("thread-t1", "任务1", delivery="auto")
    await _wait_for(collector, "item/delta")  # run 任务已开始迭代（prompts 已记录）
    assert runner.prompts == ["任务1"]

    # 运行中 enqueue：严格 FIFO 排队，不打断当前 Run
    await client.send_input("thread-t1", "任务2", delivery="enqueue")
    await client.send_input("thread-t1", "任务3", delivery="enqueue")
    assert runner.prompts == ["任务1"]  # 当前 Run 未被打断

    # 释放 → Run1 完成 → 自动按序启动 Run2、Run3
    runner.released.set()
    await _wait_for(collector, "run/completed", timeout=2.0)
    deadline = asyncio.get_running_loop().time() + 2.0
    while len(runner.prompts) < 3:
        if asyncio.get_running_loop().time() > deadline:
            break
        await asyncio.sleep(0.005)
    assert runner.prompts == ["任务1", "任务2", "任务3"]


@pytest.mark.asyncio
async def test_immediate_steer_at_checkpoint():
    collector = Collector()
    runner = BlockingRunner("thread-t1")
    runners = {"thread-t1": runner}

    async def factory(tid):
        return runners[tid]

    client = EmbeddedAgentClient(factory, config=_config(), event_sink=collector)

    await client.send_input("thread-t1", "任务1", delivery="auto")
    await _wait_for(collector, "item/delta")
    receipt = await client.send_input("thread-t1", "运行中补充", delivery="immediate")
    assert str(receipt.state) == "immediate_pending"

    # 释放 → 检查点 drain：补充被 steer（applied）
    runner.released.set()
    await _wait_for(collector, "run/completed")
    assert runner.steered == ["运行中补充"]
    states = [
        line["params"]["state"]
        for line in collector.lines
        if line["method"] == "input/state"
    ]
    assert "applied" in states


# ---------------------------------------------------------------------------
# Approval 精确绑定 thread/run/tool_call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_binding_wrong_run_rejected():
    collector = Collector()
    runner = BlockingRunner(
        "thread-t1",
        events=[
            TextDelta("先看"),
            ToolCallBegin("call-1", "run_command", '{"command":"rm -rf x"}'),
        ],
    )
    runners = {"thread-t1": runner}

    async def factory(tid):
        return runners[tid]

    client = EmbeddedAgentClient(factory, config=_config(), event_sink=collector)

    await client.send_input("thread-t1", "任务", delivery="auto")
    await _wait_for(collector, "approval/requested")
    requested = next(
        line["params"]
        for line in collector.lines
        if line["method"] == "approval/requested"
    )

    # 错误的 run_id → 拒绝（不消费、不 deny）
    ok = await client.resolve_approval(
        "thread-t1",
        "run-wrong",
        requested["approval_id"],
        True,
        tool_call_id="call-1",
    )
    assert ok is False
    assert runner.permitted == []

    # 正确的 thread/run/tool_call → 原子消费 + inbound.permit
    ok = await client.resolve_approval(
        "thread-t1",
        requested["run_id"],
        requested["approval_id"],
        True,
        tool_call_id="call-1",
    )
    assert ok is True
    assert runner.permitted == ["call-1"]

    # 已消费的 approval 不可重放
    ok = await client.resolve_approval(
        "thread-t1",
        requested["run_id"],
        requested["approval_id"],
        True,
        tool_call_id="call-1",
    )
    assert ok is False

    runner.released.set()
    await _wait_for(collector, "run/completed")


@pytest.mark.asyncio
async def test_run_end_expires_pending_approvals():
    collector = Collector()
    runner = BlockingRunner(
        "thread-t1",
        events=[ToolCallBegin("call-1", "run_command", '{"command":"rm -rf x"}')],
    )
    runners = {"thread-t1": runner}

    async def factory(tid):
        return runners[tid]

    client = EmbeddedAgentClient(factory, config=_config(), event_sink=collector)
    await client.send_input("thread-t1", "任务", delivery="auto")
    await _wait_for(collector, "approval/requested")

    # Run 终结（释放）→ 待审批自动过期
    runner.released.set()
    await _wait_for(collector, "run/completed")
    await _wait_for(collector, "approval/resolved")
    resolved = [
        line["params"]
        for line in collector.lines
        if line["method"] == "approval/resolved"
    ]
    assert any(p.get("status") == "expired" for p in resolved)
    # 过期审批不可再解析
    requested = next(
        line["params"]
        for line in collector.lines
        if line["method"] == "approval/requested"
    )
    ok = await client.resolve_approval(
        "thread-t1",
        requested["run_id"],
        requested["approval_id"],
        True,
        tool_call_id="call-1",
    )
    assert ok is False


# ---------------------------------------------------------------------------
# 幂等 request_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_input_state_events_carry_request_id():
    """复验 P0：Embedded 的 input/state 事件持续携带 request_id（TUI 可关联）。"""
    collector = Collector()
    runner = BlockingRunner("thread-t1")
    runners = {"thread-t1": runner}

    async def factory(tid):
        return runners[tid]

    client = EmbeddedAgentClient(factory, config=_config(), event_sink=collector)
    await client.send_input(
        "thread-t1", "运行中补充", delivery="immediate", request_id="req-steer"
    )
    runner.released.set()
    await _wait_for(collector, "run/completed")

    states = [
        line["params"] for line in collector.lines if line["method"] == "input/state"
    ]
    # 该输入链路（immediate_pending → applied）的所有状态都带 request_id
    linked = [
        p
        for p in states
        if p.get("state") in ("queued", "immediate_pending", "applied", "deferred")
    ]
    assert linked, "无输入状态事件"
    assert all(p.get("request_id") == "req-steer" for p in linked), [
        p.get("state") for p in linked
    ]


@pytest.mark.asyncio
async def test_delivery_mappings_bounded_after_many_runs():
    """四轮复验 P0：多轮 Run 后关联映射回到 0（queued→applied 终态 + 无泄漏）。"""
    collector = Collector()
    runner = BlockingRunner("thread-t1")
    runners = {"thread-t1": runner}

    async def factory(tid):
        return runners[tid]

    client = EmbeddedAgentClient(factory, config=_config(), event_sink=collector)

    await client.send_input("thread-t1", "任务0", delivery="auto", request_id="req-0")
    await client.send_input(
        "thread-t1", "任务1", delivery="enqueue", request_id="req-1"
    )
    await client.send_input(
        "thread-t1", "任务2", delivery="enqueue", request_id="req-2"
    )
    # 任务0 已被消费（终态清理）；任务1/2 排队中（关联保留）
    assert set(client._message_request.values()) == {"req-1", "req-2"}

    runner.released.set()  # 首轮放行 → FIFO 依次消费 3 个输入
    deadline = asyncio.get_running_loop().time() + 2.0
    while sum(1 for line in collector.lines if line["method"] == "run/completed") < 3:
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("3 个 run/completed 超时")
        await asyncio.sleep(0.005)
    await asyncio.sleep(0.02)

    # 每个被 Run 消费的输入都到达 applied 终态（带原 request_id）
    applied = [
        p["params"]
        for p in collector.lines
        if p["method"] == "input/state"
        and p["params"].get("state") == "applied"
        and p["params"].get("request_id")
    ]
    assert len(applied) == 3, [
        (p["params"].get("state"), p["params"].get("request_id"))
        for p in collector.lines
        if p["method"] == "input/state"
    ]

    # 无持续增长：message_id→request_id 映射回到 0
    assert client._message_request == {}, client._message_request


@pytest.mark.asyncio
async def test_abnormal_run_end_emits_deferred_for_unapplied_immediate():
    """五轮复验 P0：Run 异常结束时，未应用的 immediate 输入发 deferred（带 request_id）。

    场景：Run 启动 → immediate（immediate_pending）→ provider 异常 →
    harness 放回队首 → client 发 deferred + 清理映射 + 下次 Run 仍消费。
    """
    collector = Collector()
    runner = BlockingRunner("thread-t1")
    runner.fail_gate = asyncio.Event()  # 受控失败点：immediate 到达后再崩溃
    runners = {"thread-t1": runner}

    async def factory(tid):
        return runners[tid]

    client = EmbeddedAgentClient(factory, config=_config(), event_sink=collector)
    await client.send_input(
        "thread-t1", "任务", delivery="auto", request_id="req-initial"
    )
    await _wait_for(collector, "run/started", thread_id="thread-t1")
    await client.send_input(
        "thread-t1", "late steer", delivery="immediate", request_id="req-steer"
    )
    await _wait_for(collector, "input/state", thread_id="thread-t1")  # 确保已路由
    runner.fail_gate.set()  # provider 在下一检查点前异常
    await _wait_for(collector, "run/completed", thread_id="thread-t1")
    await asyncio.sleep(0.02)

    states = [p["params"] for p in collector.lines if p["method"] == "input/state"]
    linked = [(p["state"], p.get("request_id")) for p in states if p.get("request_id")]
    # late steer：immediate_pending → deferred（异常结束，未被应用）
    assert ("immediate_pending", "req-steer") in linked, linked
    assert ("deferred", "req-steer") in linked, linked
    # 输入没有丢失：deferred 后仍在队首，下次 Run 会消费
    session = client.manager.get_session("thread-t1")
    assert session is not None and session.queued_inputs
    peek = session.queued_inputs.peek()
    assert peek.text == "late steer"

    # 无持续增长：映射已清理
    assert client._message_request == {}, client._message_request


@pytest.mark.asyncio
async def test_request_id_idempotent_retry():
    collector = Collector()
    runner = BlockingRunner("thread-t1")
    runners = {"thread-t1": runner}

    async def factory(tid):
        return runners[tid]

    client = EmbeddedAgentClient(factory, config=_config(), event_sink=collector)

    r1 = await client.send_input(
        "thread-t1", "任务", delivery="auto", request_id="req-1"
    )
    r2 = await client.send_input(
        "thread-t1", "任务", delivery="auto", request_id="req-1"
    )
    assert r1.message_id == r2.message_id  # 重放原结果
    await _wait_for(collector, "item/delta")
    assert runner.prompts == ["任务"]  # 未启动第二个 Run

    runner.released.set()
    await _wait_for(collector, "run/completed")


# ---------------------------------------------------------------------------
# 事件 envelope / 快照 / RunSnapshot 冻结
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_events_carry_envelope_and_snapshot_recovery():
    collector = Collector()
    runner = BlockingRunner(
        "thread-t1",
        events=[
            TextDelta("好"),
            ToolCallBegin("call-1", "web_search", '{"query":"x"}'),
            ToolResult("call-1", "web_search", "{}", ok=True),
        ],
    )
    runners = {"thread-t1": runner}

    async def factory(tid):
        return runners[tid]

    client = EmbeddedAgentClient(factory, config=_config(), event_sink=collector)
    await client.send_input("thread-t1", "任务", delivery="auto")
    runner.released.set()
    await _wait_for(collector, "run/completed")

    for line in collector.lines:
        params = line["params"]
        assert params["thread_id"] == "thread-t1"
        assert params["protocol_version"] == 2
        assert params["event_id"]
        assert isinstance(params["seq"], int)
    run_events = [
        ln for ln in collector.lines if ln["method"] in ("run/started", "run/completed")
    ]
    assert all(ln["params"].get("run_id") for ln in run_events)
    item_events = [
        ln
        for ln in collector.lines
        if ln["method"] in ("item/started", "item/completed")
    ]
    assert all(ln["params"].get("item_id") for ln in item_events)

    # 断线重连恢复：after_seq 增量 + 全量快照
    last_seq = collector.lines[-1]["params"]["seq"]
    tail = await client.events("thread-t1", after_seq=last_seq - 1)
    assert len(tail) == 1
    snapshot = await client.snapshot("thread-t1")
    assert snapshot["exists"] is True
    assert snapshot["active_run_phase"] in ("completed", "cancelled", "failed")


@pytest.mark.asyncio
async def test_run_snapshot_frozen_at_start():
    collector = Collector()
    runner = BlockingRunner("thread-t1")
    runners = {"thread-t1": runner}

    async def factory(tid):
        return runners[tid]

    client = EmbeddedAgentClient(
        factory,
        config=_config(model="deepseek-v4-pro", session_mode="plan"),
        event_sink=collector,
    )
    await client.send_input("thread-t1", "任务", delivery="auto", mode="plan")
    await _wait_for(collector, "run/started")  # run 任务已冻结 snapshot

    snapshot = await client.snapshot("thread-t1")
    rs = snapshot["run_snapshot"]
    assert rs["session_mode"] == "plan"
    assert rs["model"] == "deepseek-v4-pro"
    assert rs["execution_target"]["kind"] == "local"
    assert rs["permission_policy"]["allow_file_write"] is False  # plan 只读

    runner.released.set()
    await _wait_for(collector, "run/completed")
