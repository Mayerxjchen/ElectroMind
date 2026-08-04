"""Identity Sweep 回归：活跃源码不得再出现旧项目身份。

旧身份包括：旧项目名（含旧数据目录、旧镜像名）、旧仓库与文档站点的
旧 owner 组织名（两种大小写）、以及旧 v4 模块名。本文件用拼接构造
搜索串，避免自匹配。

有意保留、不参与扫描：
- ``docs/superpowers/``：历史设计文档（plans / specs）
- ``LICENSE``：版权归属行
- ``.gitignore``：遗留旧名的忽略条目（防止旧文件被误提交）
- 构建产物 / 依赖目录 / 二进制资源
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 拼接以避免本测试文件自匹配。
_FORBIDDEN = (
    re.compile("pa" + "gent"),
    re.compile("Sync" + "LionPaw"),
    re.compile("sync" + "lionpaw"),
    re.compile("electromind" + "v4"),
)

_SKIP_DIRS = {
    ".git",
    ".claude",
    ".venv",
    "dist",
    "docs",  # 历史设计文档
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "hpc test",  # 未跟踪目录
}
_SKIP_NAMES = {"LICENSE", ".gitignore", "package-lock.json"}
_BINARY_SUFFIXES = (".vsix", ".png", ".ico", ".ttf", ".woff", ".woff2", ".jpg", ".gif")


def _iter_source_files():
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(REPO_ROOT)
        if rel.parts[0] in _SKIP_DIRS:
            continue
        if "node_modules" in rel.parts:
            continue
        if rel.name in _SKIP_NAMES or rel.name.endswith(_BINARY_SUFFIXES):
            continue
        yield rel, path


def test_no_old_identity_in_active_source():
    hits: list[str] = []
    count = 0
    for rel, path in _iter_source_files():
        count += 1
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # 二进制资源
        for pattern in _FORBIDDEN:
            if pattern.search(text):
                hits.append(f"{rel}: {pattern.pattern!r}")
    assert count > 200, "扫描范围异常缩小（排除项疑似误改）"
    assert not hits, "活跃源码出现旧身份：\n" + "\n".join(hits)
