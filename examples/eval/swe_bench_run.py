"""SWE-bench_Lite 冒烟测试 — CodeRunner 作 coding agent 修 bug。

每题:clone repo at base_commit → agent 探索+改代码 → 收集 patch → 评估。
评估分档(本机无 docker,非官方 harness,不可与 leaderboard 直接对比):
  - resolved  : agent patch + gold test_patch 在 fresh checkout 上让 FAIL_TO_PASS 全过
                (Tier1, best-effort, 需 --try-tests;装 deps 慢且可能失败)
  - partial   : Tier1 环境正常但部分 FAIL_TO_PASS 未过
  - patch-only: Tier1 未跑或失败;看 patch 能否干净 apply + 与 gold 的文件重合/行相似度
  - failed    : 无 patch 或 patch 无法 apply

数据:SWE-bench_Lite parquet,HF resolve 直链下载(非 gated,无需登录)。

Usage:
    export DEEPSEEK_API_KEY="your-key"
    uv run --with pyarrow python -m examples.eval.swe_bench_run --limit 1 -v
    uv run --with pyarrow python -m examples.eval.swe_bench_run --limit 20
    uv run --with pyarrow python -m examples.eval.swe_bench_run --limit 20 --try-tests
    uv run --with pyarrow python -m examples.eval.swe_bench_run --sample random --seed 0 --limit 20
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

from pagentv4 import AgentCore, CodeRunner, DeepSeek

DATASET_BASE = (
    "https://huggingface.co/datasets/princeton-nlp/SWE-bench_Lite/resolve/main/data"
)
DATA_CACHE = Path(".pagent/swebench_data")
REPO_CACHE = Path(".pagent/swebench_repos")  # bare clones, per-repo
EVAL_ROOT = Path(".pagent/swebench_eval")  # fresh checkouts for scoring

SYSTEM_PROMPT = (
    "You are a software engineer fixing a bug in an open-source Python repository. "
    "The repository is cloned at `./repo` in your workspace, checked out at the base commit.\n\n"
    "Workflow:\n"
    "1. Read the problem statement carefully.\n"
    "2. Explore the repo: use list_dir / read_file / run_command "
    "(e.g. `grep -rn keyword repo/`) to locate the buggy code.\n"
    "3. Make a MINIMAL, targeted fix with str_replace or write_file. "
    "Do not rewrite whole files.\n"
    "4. Optionally sanity-check by running the repo's existing tests for the affected "
    "module (do NOT add or modify tests).\n"
    "5. Keep edits minimal and focused.\n\n"
    "Constraints:\n"
    "- File paths are relative to your workspace (e.g. `repo/django/db/models/sql/query.py`).\n"
    "- Do NOT create a virtualenv or install dependencies; assume the repo is set up.\n"
    "- Do NOT modify test files; only fix source code.\n"
    "- When done, reply with a one-line summary of what you changed."
)

STATUS_MARK = {
    "resolved": "RESOLVED",
    "partial": "PARTIAL",
    "patch-only": "PATCH",
    "failed": "FAIL",
}


def clip(text: str, limit: int = 100) -> str:
    one = text.replace("\n", " ")
    return one if len(one) <= limit else one[: limit - 3] + "..."


def as_list(v) -> list:
    if v is None:
        return []
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except json.JSONDecodeError:
            return []
    return list(v)


def files_in_diff(diff: str) -> set[str]:
    out = set()
    for m in re.finditer(r"^diff --git a/(.+?) b/(.+)$", diff, re.MULTILINE):
        out.add(m.group(2))
    return out


def repo_slug(repo: str) -> str:
    return repo.replace("/", "__")


# ---------- data ----------


def load_split(split: str) -> list[dict]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SystemExit(
            "需要 pyarrow：uv run --with pyarrow python -m examples.eval.swe_bench_run"
        ) from exc
    DATA_CACHE.mkdir(parents=True, exist_ok=True)
    url = f"{DATASET_BASE}/{split}-00000-of-00001.parquet"
    path = DATA_CACHE / f"{split}.parquet"
    if not path.exists():
        print(f"downloading {split} split from HF ...", flush=True)
        urllib.request.urlretrieve(url, path)
    return pq.read_table(path).to_pylist()


def select_rows(rows, *, limit, sample, offset, seed):
    size = len(rows)
    count = min(limit, size) if limit > 0 else size
    if sample == "head":
        start = offset
        end = min(offset + count, size)
        return rows[start:end], f"{size} rows [{start}:{end}]"
    rng = random.Random(seed)
    idx = sorted(rng.sample(range(size), count))
    return [rows[i] for i in idx], f"{size} rows random n={count} seed={seed}"


# ---------- repo cache ----------


def ensure_bare(repo: str) -> Path:
    bare = REPO_CACHE / f"{repo_slug(repo)}.git"
    if (
        bare.exists()
        and subprocess.run(
            ["git", "--git-dir", str(bare), "rev-parse", "--is-bare-repository"],
            capture_output=True,
        ).returncode
        == 0
    ):
        return bare
    REPO_CACHE.mkdir(parents=True, exist_ok=True)
    print(f"  cloning {repo} (bare, one-time cache) ...", flush=True)
    subprocess.run(
        ["git", "clone", "--bare", f"https://github.com/{repo}", str(bare)],
        check=True,
        timeout=600,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return bare


def checkout_at(bare: Path, dest: Path, base_commit: str) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    subprocess.run(
        ["git", "clone", "--no-checkout", str(bare), str(dest)],
        check=True,
        timeout=120,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    r = subprocess.run(
        ["git", "-C", str(dest), "checkout", base_commit],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return r.returncode == 0


# ---------- agent ----------


def build_prompt(row) -> str:
    return (
        f"Problem statement:\n{row['problem_statement']}\n\n"
        f"---\n\nThe repo is at `./repo` (checked out at the base commit). "
        f"Investigate the issue above and produce a minimal fix. "
        f"Do not modify tests."
    )


async def run_agent(row, *, model: str, max_turns: int, bare: Path) -> tuple[str, str]:
    thread_id = f"swe-{row['instance_id']}"
    agent = AgentCore(DeepSeek(model), system=SYSTEM_PROMPT, max_turns=max_turns)
    runner = CodeRunner(
        agent,
        backend="local",
        thread_id=thread_id,
        command_policy="open",
    )
    workdir = Path(runner.thread.workspace_path)
    workdir.mkdir(parents=True, exist_ok=True)
    repo_dir = workdir / "repo"
    if not checkout_at(bare, repo_dir, row["base_commit"]):
        raise RuntimeError(f"checkout base_commit failed: {row['base_commit']}")
    prompt = build_prompt(row)
    try:
        chunks = [t async for t in runner.run(prompt, return_type="text")]
        answer = "".join(c for c in chunks if c)
    finally:
        await runner.close()
    patch = collect_patch(repo_dir)  # workspace persists after close (local backend)
    return answer, patch


def collect_patch(repo_dir: Path) -> str:
    if not (repo_dir / ".git").exists():
        return ""
    subprocess.run(
        ["git", "-C", str(repo_dir), "add", "-A"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    r = subprocess.run(
        ["git", "-C", str(repo_dir), "diff", "--cached"],
        capture_output=True,
        text=True,
    )
    return r.stdout


# ---------- evaluation ----------


def apply_patch(repo_dir: Path, patch: str) -> tuple[bool, str]:
    if not patch.strip():
        return False, "empty patch"
    p = subprocess.run(
        ["git", "-C", str(repo_dir), "apply", "--whitespace=nowarn", "-"],
        input=patch,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return p.returncode == 0, (p.stderr.strip() or "ok")


def eval_patch_only(row, patch: str) -> dict:
    gold = row["patch"] or ""
    gold_files = files_in_diff(gold)
    agent_files = files_in_diff(patch)
    overlap = agent_files & gold_files
    union = agent_files | gold_files
    jaccard = len(overlap) / len(union) if union else 0.0
    sim = difflib.SequenceMatcher(None, gold.splitlines(), patch.splitlines()).ratio()
    return {
        "agent_files": sorted(agent_files),
        "gold_files": sorted(gold_files),
        "file_overlap": sorted(overlap),
        "file_jaccard": round(jaccard, 3),
        "line_similarity": round(sim, 3),
    }


def _run_one_test(repo_dir: Path, py: Path, test_id: str, timeout: int) -> bool:
    try:
        r = subprocess.run(
            [str(py), "-m", "pytest", test_id, "-x", "-q", "--no-header", "--tb=no"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.returncode == 0
    except Exception:
        return False


def _install_and_run(fresh: Path, row, install_timeout: int, test_timeout: int) -> dict:
    """Tier1 best-effort: venv + pip install -e . + run FAIL_TO_PASS."""
    ftp = as_list(row["FAIL_TO_PASS"])
    venv = fresh / ".venv"
    py = venv / "bin" / "python"
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
        )
        inst = subprocess.run(
            [str(py), "-m", "pip", "install", "-e", ".", "-q"],
            cwd=str(fresh),
            capture_output=True,
            text=True,
            timeout=install_timeout,
        )
        if inst.returncode != 0:
            return {
                "env_ok": False,
                "error": f"pip install -e . failed: {inst.stderr[:300]}",
            }
        subprocess.run(
            [str(py), "-m", "pip", "install", "pytest", "-q"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return {"env_ok": False, "error": "install timeout"}
    except Exception as e:
        return {"env_ok": False, "error": f"install error: {e}"}
    passed = sum(1 for t in ftp if _run_one_test(fresh, py, t, test_timeout))
    return {"env_ok": True, "error": "", "f2p_passed": passed, "f2p_total": len(ftp)}


def score_task(
    row,
    patch: str,
    *,
    bare: Path,
    try_tests: bool,
    install_timeout: int,
    test_timeout: int,
) -> dict:
    rec: dict = {
        "instance_id": row["instance_id"],
        "repo": row["repo"],
        "status": "failed",
        "detail": "",
        "patch_preview": clip(patch, 2000),
    }
    if not patch.strip():
        rec["detail"] = "no patch produced"
        return rec

    info = eval_patch_only(row, patch)
    rec.update(info)

    # fresh checkout at base_commit → apply agent patch (clean scoring, isolate stray edits)
    fresh = EVAL_ROOT / repo_slug(row["repo"]) / f"{row['instance_id']}-score"
    if not checkout_at(bare, fresh, row["base_commit"]):
        rec["detail"] = "fresh checkout failed"
        return rec
    ok, msg = apply_patch(fresh, patch)
    rec["applies_cleanly"] = ok
    if not ok:
        rec["detail"] = f"patch apply failed: {msg}"
        return rec
    rec["status"] = "patch-only"
    rec["detail"] = (
        f"applies; jaccard={info['file_jaccard']} sim={info['line_similarity']} "
        f"files={len(info['agent_files'])}"
    )
    if not try_tests:
        return rec

    # Tier1: apply gold test_patch, install, run FAIL_TO_PASS (on the same fresh checkout)
    ok, msg = apply_patch(fresh, row["test_patch"] or "")
    if not ok:
        rec["tier1_error"] = f"test_patch apply failed: {msg}"
        rec["detail"] += f"; tier1: {rec['tier1_error']}"
        return rec
    tr = _install_and_run(fresh, row, install_timeout, test_timeout)
    rec["tier1"] = tr
    if not tr["env_ok"]:
        rec["detail"] += f"; tier1 env failed: {tr['error']}"
        return rec
    rec["f2p_passed"] = tr["f2p_passed"]
    rec["f2p_total"] = tr["f2p_total"]
    if tr["f2p_total"] > 0 and tr["f2p_passed"] == tr["f2p_total"]:
        rec["status"] = "resolved"
        rec["detail"] = f"resolved; FAIL_TO_PASS {tr['f2p_passed']}/{tr['f2p_total']}"
    else:
        rec["status"] = "partial"
        rec["detail"] += f"; FAIL_TO_PASS {tr['f2p_passed']}/{tr['f2p_total']}"
    return rec


# ---------- main ----------


def summarize(results: list[dict]) -> str:
    total = len(results)
    c = Counter(r["status"] for r in results)
    lines = [f"SWE-bench_Lite smoke test: {total} tasks"]
    for s in ("resolved", "partial", "patch-only", "failed"):
        n = c.get(s, 0)
        pct = f"{n / total:.0%}" if total else "0"
        lines.append(f"  {s:11s}: {n}/{total} = {pct}")
    po = [r for r in results if r["status"] == "patch-only" and "file_jaccard" in r]
    if po:
        avg_j = sum(r["file_jaccard"] for r in po) / len(po)
        lines.append(f"  mean file_jaccard (patch-only): {avg_j:.2f}")
    lines.append("  (no docker — NOT comparable to official leaderboard)")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="SWE-bench_Lite smoke test with pagent CodeRunner"
    )
    p.add_argument("--split", default="test", choices=("test", "dev"))
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--sample", default="head", choices=("head", "random"))
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--max-turns", type=int, default=30)
    p.add_argument("--model", default="deepseek-v4-flash")
    p.add_argument(
        "--try-tests",
        action="store_true",
        help="enable Tier1 gold-test run (slow, best-effort deps install)",
    )
    p.add_argument("--install-timeout", type=int, default=180)
    p.add_argument("--test-timeout", type=int, default=120)
    p.add_argument("--task-timeout", type=int, default=1200)
    p.add_argument("--out", default=None, help="append JSONL results to this path")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


async def main() -> None:
    args = parse_args()
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("请先 export DEEPSEEK_API_KEY=<your-key>")

    rows_all = load_split(args.split)
    rows, label = select_rows(
        rows_all,
        limit=args.limit,
        sample=args.sample,
        offset=args.offset,
        seed=args.seed,
    )
    print(
        f"SWE-bench_Lite {label}\n"
        f"model={args.model} max_turns={args.max_turns} try_tests={args.try_tests}\n"
    )

    repos = sorted({r["repo"] for r in rows})
    bares = {repo: ensure_bare(repo) for repo in repos}
    print()

    out = open(args.out, "a") if args.out else None
    results: list[dict] = []
    try:
        for i, row in enumerate(rows, 1):
            iid = row["instance_id"]
            print(f"[{i}/{len(rows)}] {iid} ({row['repo']}) running ...", flush=True)
            if args.verbose:
                print(f"     Q: {clip(row['problem_statement'], 140)}", flush=True)
            t0 = time.monotonic()
            answer, patch = "", ""
            try:
                answer, patch = await asyncio.wait_for(
                    run_agent(
                        row,
                        model=args.model,
                        max_turns=args.max_turns,
                        bare=bares[row["repo"]],
                    ),
                    timeout=args.task_timeout,
                )
            except asyncio.TimeoutError:
                print(f"     agent timeout ({args.task_timeout}s)", flush=True)
            except Exception as e:
                print(f"     agent error: {type(e).__name__}: {e}", flush=True)

            rec = await asyncio.to_thread(
                score_task,
                row,
                patch,
                bare=bares[row["repo"]],
                try_tests=args.try_tests,
                install_timeout=args.install_timeout,
                test_timeout=args.test_timeout,
            )
            rec["elapsed"] = round(time.monotonic() - t0, 1)
            if args.verbose:
                rec["answer"] = clip(answer, 300)
            results.append(rec)
            mark = STATUS_MARK.get(rec["status"], rec["status"])
            print(f"     [{mark}] {rec['detail']} ({rec['elapsed']}s)", flush=True)
            if out:
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
    finally:
        if out:
            out.close()

    print()
    print(summarize(results))


if __name__ == "__main__":
    asyncio.run(main())
