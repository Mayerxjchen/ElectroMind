"""原子写与损坏恢复（P1.2 / P1.3）。

原则：
- 所有关键状态文件（thread.toml / metainfo.json / desktop.json /
  artifacts.jsonl / messages.jsonl / plan@*.json …）写盘一律走本模块，
  先写同目录临时文件 + fsync，再 ``os.replace`` 原子落盘。
  崩溃 / 断电只可能留下完整旧文件或完整新文件，绝不出现半写状态。
- ``backup=True`` 时，覆盖前把当前文件复制为 ``<name>.bak``（上一个
  完好版本），供 P1.3 损坏检测时恢复。
- 读侧提供 ``load_jsonl_recover`` / ``load_json_recover`` / ``load_toml_recover``，
  主文件损坏时自动尝试 ``.bak``，损坏文件改名 ``<name>.corrupt`` 留存。
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import tomllib
from pathlib import Path


def _fsync_dir(directory: Path) -> None:
    """fsync 目录本身，确保 rename 条目落盘（POSIX）。"""
    try:
        fd = os.open(str(directory), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass  # 某些文件系统（FAT / 网络盘）不支持目录 fsync


def _backup_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".bak")


def _maybe_backup(path: Path, backup: bool) -> None:
    if not backup or not path.exists():
        return
    bak = _backup_path(path)
    try:
        shutil.copy2(path, bak)
    except OSError:
        pass  # 备份失败不阻断写；损坏恢复会自然退化到只读主文件


def atomic_write_text(
    path: str | Path,
    content: str,
    *,
    encoding: str = "utf-8",
    backup: bool = False,
) -> None:
    """原子写文本文件（临时文件 + fsync + os.replace）。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f"{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        _maybe_backup(target, backup)
        os.replace(tmp_name, target)
        _fsync_dir(target.parent)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_bytes(
    path: str | Path, content: bytes, *, backup: bool = False
) -> None:
    """原子写二进制文件。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f"{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        _maybe_backup(target, backup)
        os.replace(tmp_name, target)
        _fsync_dir(target.parent)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# ── 读侧：损坏检测 + .bak 恢复 ────────────────────────────────────────


def _corrupt_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".corrupt")


def _quarantine(target: Path) -> None:
    """主文件损坏且无可用 .bak：改名 .corrupt 留存现场（不删）。"""
    try:
        if target.exists():
            os.replace(target, _corrupt_path(target))
    except OSError:
        pass


def _candidates(target: Path) -> list[Path]:
    return [target, _backup_path(target)]


def _maybe_quarantine(target: Path, recovered_from_backup: bool) -> None:
    """从 .bak 恢复成功 → 把损坏主文件改名 .corrupt 留存（供诊断）。"""
    if recovered_from_backup:
        _quarantine(target)


def load_json_recover(path: str | Path, *, default=None):
    """读 JSON；主文件损坏 → 尝试 .bak → 均失败返回 default 并留存 .corrupt。"""
    target = Path(path)
    for candidate in _candidates(target):
        if not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
            _maybe_quarantine(target, candidate is not target)
            return data
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    _quarantine(target)
    return default


def load_toml_recover(path: str | Path, *, default=None):
    """读 TOML；主文件损坏 → 尝试 .bak → 均失败返回 default 并留存 .corrupt。"""
    target = Path(path)
    for candidate in _candidates(target):
        if not candidate.exists():
            continue
        try:
            data = tomllib.loads(candidate.read_text(encoding="utf-8"))
            _maybe_quarantine(target, candidate is not target)
            return data
        except (OSError, ValueError, TypeError, tomllib.TOMLDecodeError):
            continue
    _quarantine(target)
    return default


def load_jsonl_recover(
    path: str | Path,
    *,
    parse_line,
    encoding: str = "utf-8",
    min_good_ratio: float = 0.5,
    default=None,
) -> list:
    """读行式 JSON；主文件整体损坏 → 尝试 .bak。

    - ``parse_line``：接收一行 str，返回解析对象；抛异常表示该行损坏。
    - ``min_good_ratio``：可解析行占比低于该阈值视为整份损坏（例如被截断的
      半写文件），转而尝试 .bak；等于 1 表示一行都不能坏（严格模式）。
    - 单条损坏但不至于整体损坏：跳过坏行保留好行（fail-soft），不改名。
    """
    target = Path(path)
    default = default if default is not None else []
    for candidate in _candidates(target):
        if not candidate.exists():
            continue
        try:
            raw = candidate.read_text(encoding=encoding)
        except (OSError, UnicodeDecodeError):
            continue
        good: list = []
        bad = 0
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                good.append(parse_line(line))
            except (ValueError, TypeError, json.JSONDecodeError):
                bad += 1
        total = len(good) + bad
        if total == 0:
            return list(default)
        if good and bad / total <= (1.0 - min_good_ratio):
            _maybe_quarantine(target, candidate is not target)
            return good
        # 整份几乎全坏 → 损坏，尝试下一个候选
    _quarantine(target)
    return list(default)
