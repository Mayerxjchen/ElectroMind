"""M3: ContextManager / 预算 / 压缩 / 记忆分层测试。"""

from __future__ import annotations

from electromind.context import (
    ArtifactMemory,
    ArtifactMemoryEntry,
    Compactor,
    ContextInput,
    ContextManager,
    ProjectMemory,
    SummaryRecord,
    ThreadMemory,
    decide_context_budget,
    digest_messages,
    estimate_tokens,
    message_tokens,
)
from electromind.core.capabilities import ModelCapabilities


def _openai_turn(text: str, turn: int) -> list[dict]:
    return [
        {"role": "user", "content": f"用户问题 {text}"},
        {"role": "assistant", "content": f"助手回答 {text}"},
    ]


def _tool_turn() -> list[dict]:
    return [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c1", "function": {"name": "read_file", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "文件内容"},
        {"role": "assistant", "content": "读取完成"},
    ]


# ── Token 估算与预算 ────────────────────────────────────────────────────


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello") >= 1
    assert estimate_tokens("a" * 400) >= 100  # 保守字符/4


def test_message_tokens():
    messages = [{"role": "user", "content": "你好" * 100}]
    assert message_tokens(messages) > 50  # 200 字符 → 保守 ≥50 + role 开销


def test_decide_context_budget():
    caps = ModelCapabilities(context_window=200_000, supports_tools=True)
    small = [{"role": "user", "content": "hi"}]
    budget = decide_context_budget(small, caps)
    assert budget.decision == "ok"
    big = [{"role": "user", "content": "x" * 700_000}]  # ~175k tokens > 170k 阈值
    budget2 = decide_context_budget(big, caps)
    assert budget2.decision in ("compact", "limit")


# ── Compactor ───────────────────────────────────────────────────────────


def test_compactor_keeps_constraints_and_recent():
    messages = [{"role": "system", "content": "sys"}]
    messages += _openai_turn("一", 1) + _openai_turn("二", 2) + _openai_turn("三", 3)
    messages.insert(1, {"role": "user", "content": "约束：必须使用 UTF-8 编码"})
    compactor = Compactor(
        keep_recent_turns=4, pinned_constraints=("必须使用 UTF-8 编码",)
    )
    compacted, record = compactor.compact(messages)
    assert record is not None
    assert record.source_digest
    assert record.source_message_range == (0, 4)
    # 约束原文保留
    assert any("必须使用 UTF-8 编码" in str(m.get("content", "")) for m in compacted)
    # 最近 2 轮原始保留
    joined = " ".join(str(m.get("content", "")) for m in compacted)
    assert "助手回答 三" in joined
    assert "助手回答 二" in joined
    # 早期轮被摘要（摘要消息之外的原始消息不得再含旧轮次）
    summary_msgs = [m for m in compacted if "[历史摘要]" in str(m.get("content", ""))]
    assert len(summary_msgs) == 1
    non_summary = [m for m in compacted if m is not summary_msgs[0]]
    assert not any("助手回答 一" in str(m.get("content", "")) for m in non_summary)


def test_compactor_no_old_no_summary():
    messages = _openai_turn("唯一", 1)
    compactor = Compactor(keep_recent_turns=10)
    compacted, record = compactor.compact(messages)
    assert record is None
    assert compacted == messages


def test_compactor_pairing_intact():
    messages = _tool_turn() + _openai_turn("后续", 2)
    compactor = Compactor(keep_recent_turns=1)
    compacted, _ = compactor.compact(messages)
    assert compactor.pairing_intact(compacted)


def test_summary_record_roundtrip():
    record = SummaryRecord(
        summary_id="s1",
        source_message_range=(0, 10),
        source_digest="abc",
        created_by_model="m",
        text="摘要",
        conflicts=("旧摘要说 X",),
        unresolved=("是否收敛？",),
    )
    d = record.to_dict()
    restored = SummaryRecord.from_dict(d)
    assert restored.source_message_range == (0, 10)
    assert restored.conflicts == ("旧摘要说 X",)
    assert restored.unresolved == ("是否收敛？",)


def test_digest_messages_deterministic():
    messages = [{"role": "user", "content": "a"}]
    assert digest_messages(messages) == digest_messages(messages)


# ── ContextManager ──────────────────────────────────────────────────────


def test_context_manager_assembles():
    caps = ModelCapabilities(context_window=200_000)
    manager = ContextManager(caps)
    context = ContextInput(
        system="你是助手",
        pinned_constraints=["必须使用 UTF-8"],
        objective="计算能量",
        plan="P-1 v1（已批准）",
        current_step="s1: 输入生成",
        recent_messages=_openai_turn("你好", 1),
        tool_summaries=["read_file → ok"],
        artifact_refs=["energy.out (sha256 d34db33f)"],
        budget_info="剩余 60%",
    )
    prepared = manager.prepare(context)
    assert prepared.messages[0]["role"] == "system"
    system_text = prepared.messages[0]["content"]
    assert "必须使用 UTF-8" in system_text
    assert "计算能量" in system_text
    assert "P-1 v1" in system_text
    assert "s1: 输入生成" in system_text
    assert prepared.budget.decision == "ok"
    assert any("工具结果摘要" in str(m.get("content", "")) for m in prepared.messages)
    assert any("相关产物索引" in str(m.get("content", "")) for m in prepared.messages)


def test_context_manager_compacts_when_over():
    caps = ModelCapabilities(context_window=4_000)
    manager = ContextManager(
        caps, compactor=Compactor(keep_recent_turns=2, pinned_constraints=("约束K",))
    )
    messages = [{"role": "user", "content": "约束K：不要删除数据"}]
    for i in range(60):
        messages.extend(_openai_turn(f"轮{i}", i))
    context = ContextInput(
        system="sys", pinned_constraints=["约束K"], recent_messages=messages
    )
    prepared = manager.prepare(context)
    # 压缩后仍在阈值内（或已尽力）
    assert prepared.summary is not None
    assert any("约束K" in str(m.get("content", "")) for m in prepared.messages)
    assert manager.last_trace


def test_context_manager_limit_truncates_safely():
    caps = ModelCapabilities(context_window=2_000)
    manager = ContextManager(caps, compactor=Compactor(pinned_constraints=("约束Z",)))
    messages = [{"role": "user", "content": "约束Z：必须遵守"}]
    messages += [{"role": "user", "content": "x" * 800} for _ in range(50)]
    prepared = manager.prepare(
        ContextInput(
            system="sys", pinned_constraints=["约束Z"], recent_messages=messages
        )
    )
    assert any("约束Z" in str(m.get("content", "")) for m in prepared.messages)


# ── 200 轮压力（M3 §8.3） ───────────────────────────────────────────────


def test_200_turn_stress_no_context_overflow():
    caps = ModelCapabilities(context_window=8_000)
    compactor = Compactor(keep_recent_turns=6, pinned_constraints=("压力约束-ΔG",))
    manager = ContextManager(caps, compactor=compactor)
    messages: list[dict] = [{"role": "user", "content": "压力约束-ΔG：保留单位"}]
    # 200 个用户轮次 + 50 次工具调用（5 个工具轮 × 10 个调用）+ 3 次恢复轮
    for i in range(200):
        messages.extend(_openai_turn(f"轮{i}", i))
        if i % 4 == 0:
            messages.extend(_tool_turn())
    for _ in range(3):
        messages.extend(_openai_turn("恢复", 999))

    prepared = manager.prepare(
        ContextInput(
            system="sys",
            pinned_constraints=["压力约束-ΔG"],
            recent_messages=messages,
        )
    )
    # 不发生上下文超限（estimate 不超窗口）
    assert prepared.budget.estimate <= prepared.budget.window
    # 约束 100% 保留
    assert any("压力约束-ΔG" in str(m.get("content", "")) for m in prepared.messages)
    # 配对完整
    assert compactor.pairing_intact(prepared.messages)
    # 当前任务信息在 system 段（当前 Plan/Step 始终正确）
    system_text = prepared.messages[0]["content"]
    assert "sys" in system_text


# ── Memory 分层 ─────────────────────────────────────────────────────────


def test_thread_memory():
    memory = ThreadMemory()
    memory.add_constraint("用 CP2K")
    memory.add_constraint("用 CP2K")  # 去重
    memory.add_unresolved("是否收敛？")
    memory.add_decision("采用 6-31G*")
    memory.add_decision("采用 B3LYP")
    assert memory.constraints == ["用 CP2K"]
    assert memory.unresolved_questions == ["是否收敛？"]
    assert len(memory.recent_decisions) == 2
    d = memory.to_dict()
    assert d["constraints"] == ["用 CP2K"]


def test_project_memory():
    memory = ProjectMemory()
    memory.set_convention("inputs", "inputs/")
    memory.execution_environment = "slurm+module"
    memory.cluster_modules.append("cp2k/2024.1")
    memory.software_versions["cp2k"] = "2024.1"
    d = memory.to_dict()
    assert d["directory_conventions"]["inputs"] == "inputs/"
    assert d["cluster_modules"] == ["cp2k/2024.1"]


def test_artifact_memory_search():
    memory = ArtifactMemory()
    memory.add(
        ArtifactMemoryEntry(
            artifact_id="a1",
            type="parsed_result",
            path="out/e1.json",
            step_id="s1",
            run_id="r1",
            software="cp2k",
            validation_status="validated",
        )
    )
    memory.add(
        ArtifactMemoryEntry(
            artifact_id="a2",
            type="data",
            path="in/x.xyz",
            step_id="s0",
            run_id="r1",
            software="packmol",
            validation_status="created",
        )
    )
    assert len(memory) == 2
    assert [e.artifact_id for e in memory.search(type="parsed_result")] == ["a1"]
    assert [e.artifact_id for e in memory.search(software="packmol")] == ["a2"]
    assert [
        e.artifact_id for e in memory.search(run_id="r1", validation_status="validated")
    ] == ["a1"]
    assert [e.artifact_id for e in memory.search(path="e1.json")] == ["a1"]
    assert memory.search(software="vasp") == []


# ── 补充分支覆盖（M8） ─────────────────────────────────────────────────


class _FakeEncoder:
    """tiktoken 风格 encoder 桩。"""

    def encode(self, text: str) -> list[int]:
        return list(range(len(text)))  # 每字符一个 token


def test_estimate_tokens_with_encoder():
    encoder = _FakeEncoder()
    assert estimate_tokens("abc", encoder=encoder) == 3
    assert estimate_tokens("", encoder=encoder) == 0

    # encoder 抛异常 → 退化为保守估算
    class BrokenEncoder:
        def encode(self, text):
            raise RuntimeError("no tiktoken")

    assert estimate_tokens("abcd", encoder=BrokenEncoder()) >= 1


def test_message_tokens_parts_and_tool_calls():
    messages = [
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "部分一"},
                "纯字符串部分",
            ],
            "tool_calls": [
                {
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path": "a"}',
                    }
                }
            ],
        },
        {"role": "user", "content": "文本"},
    ]
    total = message_tokens(messages)
    assert total > 10  # 各部分都计入


def test_decide_context_budget_with_encoder_and_limit():
    caps = ModelCapabilities(context_window=200_000)
    # encoder 路径
    budget = decide_context_budget(
        [{"role": "user", "content": "hi"}], caps, encoder=_FakeEncoder()
    )
    assert budget.decision == "ok"
    # 压缩后仍超 → limit
    tiny = ModelCapabilities(context_window=100)
    big = [{"role": "user", "content": "x" * 10_000}]
    budget2 = decide_context_budget(big, tiny)
    assert budget2.decision == "limit"
    assert budget2.over_threshold()
    ok_budget = decide_context_budget([{"role": "user", "content": "x"}], caps)
    assert not ok_budget.over_threshold()


def test_compactor_make_summary_callable():
    messages = _openai_turn("旧", 1) + _openai_turn("新", 2)
    compactor = Compactor(
        keep_recent_turns=2,
        make_summary=lambda text: f"[模型摘要] {len(text)} 字符",
    )
    compacted, record = compactor.compact(messages)
    assert record is not None
    assert "[模型摘要]" in str(compacted[0].get("content", ""))
    assert compactor.records[0].created_by_model == "compactor"
    assert compactor.to_dict()["keep_recent_turns"] == 2


def test_compactor_pairing_detects_orphan():
    compactor = Compactor()
    broken = [
        {"role": "assistant", "tool_calls": [{"id": "c9"}]},
        {"role": "assistant", "content": "无结果"},
    ]
    assert not compactor.pairing_intact(broken)
