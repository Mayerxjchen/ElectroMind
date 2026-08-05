"""``electromind doctor --data``：数据完整性诊断（P1.5）。

逐个 Thread 检查：
1. thread.toml —— 可解析、结构完整（ThreadSpec 能重建）。
2. metainfo.json —— 可解析为 JSON dict。
3. 消息文件（messages.jsonl）—— 每条可解析为 Message，截断/损坏行数。
4. artifacts.jsonl —— 可解析；每个 Manifest 的 SHA-256 与磁盘文件一致
   （verify_all）；损坏时是否可 .bak 恢复。
5. 磁盘写权限 —— home 及该 thread 目录可写。

不修改任何数据（只读诊断）；损坏文件改名 .corrupt 的恢复动作由
atomicfile 读取侧在加载时完成，本检查只报告状态。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ThreadDataCheck:
    thread_id: str
    ok: bool = True
    issues: list[str] = field(default_factory=list)

    def problem(self, msg: str) -> None:
        self.ok = False
        self.issues.append(msg)


def _read_text_or(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return default


def check_single_thread(thread_dir: Path, home: Path) -> ThreadDataCheck:
    """对单个 thread 目录做只读完整性检查。"""
    check = ThreadDataCheck(thread_dir.name)
    spec_path = thread_dir / "thread.toml"
    meta_path = thread_dir / "metainfo.json"

    # 1. thread.toml 配置
    from electromind.atomicfile import load_toml_recover

    if not spec_path.is_file():
        check.problem(f"缺少 thread.toml: {spec_path}")
    else:
        spec = load_toml_recover(spec_path)
        if not isinstance(spec, dict) or not spec:
            check.problem(f"thread.toml 损坏（且无可用 .bak）: {spec_path}")
        else:
            try:
                from electromind.ithread import ThreadSpec

                ThreadSpec.from_dict(spec)
            except (ValueError, TypeError, KeyError) as exc:
                check.problem(f"thread.toml 结构不完整: {spec_path} ({exc})")

    # 2. metainfo.json 元信息
    from electromind.atomicfile import load_json_recover

    if meta_path.is_file():
        meta = load_json_recover(meta_path)
        if not isinstance(meta, dict):
            check.problem(f"metainfo.json 损坏: {meta_path}")
        if (thread_dir / "metainfo.json.corrupt").exists():
            check.problem("metainfo.json 曾损坏，已从 .bak 恢复（留存 .corrupt）")

    # 3. 消息文件 messages.jsonl
    messages_path = thread_dir / "messages" / "messages.jsonl"
    if not messages_path.is_file():
        # 消息文件在 thread 根或 messages/ 下；取任一存在的
        candidates = [
            thread_dir / "messages.jsonl",
            thread_dir / "messages" / "messages.jsonl",
        ]
        messages_path = next((p for p in candidates if p.is_file()), None)
    if messages_path is not None:
        try:
            from electromind.core.message import Message

            bad_lines = 0
            total = 0
            for line in _read_text_or(messages_path).splitlines():
                line = line.strip()
                if not line:
                    continue
                total += 1
                try:
                    Message.model_validate_json(line)
                except Exception:
                    bad_lines += 1
            if total and bad_lines / total > 0.5:
                check.problem(
                    f"messages.jsonl 损坏行过多（{bad_lines}/{total}）: {messages_path}"
                )
            elif bad_lines:
                check.problem(
                    f"messages.jsonl 有 {bad_lines} 行损坏（fail-soft 跳过）: "
                    f"{messages_path}"
                )
        except Exception as exc:  # noqa: BLE001
            check.problem(f"messages.jsonl 读取失败: {exc}")

    # 4. artifacts.jsonl 完整性（Manifest SHA 与磁盘核对）
    artifacts_path = thread_dir / "artifacts.jsonl"
    if artifacts_path.is_file():
        try:
            from electromind.artifacts import ArtifactRegistry

            registry = ArtifactRegistry(artifacts_path)
            errors = registry.verify_all(thread_dir)
            for err in errors:
                check.problem(f"Artifact 完整性: {err}")
        except Exception as exc:  # noqa: BLE001
            check.problem(f"artifacts.jsonl 解析失败: {exc}")
        if (thread_dir / "artifacts.jsonl.corrupt").exists():
            check.problem("artifacts.jsonl 曾损坏，已从 .bak 恢复（留存 .corrupt）")

    # 5. 磁盘写权限（thread 目录 + home）
    if not os.access(thread_dir, os.W_OK):
        check.problem(f"thread 目录不可写: {thread_dir}")
    if not os.access(home, os.W_OK):
        check.problem(f"数据根不可写: {home}")

    return check


def collect_data_checks() -> list[ThreadDataCheck]:
    """扫描全部 threads，逐个做数据完整性检查。"""
    from electromind.paths import default_electromind_home

    home = default_electromind_home()
    threads_root = home / "threads"
    if not threads_root.is_dir():
        return []
    results: list[ThreadDataCheck] = []
    for child in sorted(threads_root.iterdir(), key=lambda p: p.name, reverse=True):
        if not child.is_dir():
            continue
        if not (child / "thread.toml").is_file():
            continue
        results.append(check_single_thread(child, home))
    return results


def data_doctor_summary() -> str:
    """纯文本摘要（供 CLI/REPL 显示）。"""
    checks = collect_data_checks()
    if not checks:
        return "数据诊断：没有找到任何 Thread。"
    lines: list[str] = []
    failed = 0
    for c in checks:
        if c.ok:
            lines.append(f"[ok ] {c.thread_id}")
        else:
            failed += 1
            lines.append(f"[FAIL] {c.thread_id}")
            lines.extend(f"        - {issue}" for issue in c.issues)
    summary = f"数据诊断：{len(checks)} 个 Thread，{failed} 个有问题"
    return "\n".join([summary, *lines])
