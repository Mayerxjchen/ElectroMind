"""PR-7: TESLA Golden Path fixture test (V2 决策③，不跑真实计算).

Tiny fixture TESLA project with fake init_data, fake lcurve.out, fake
model_devi.out, tiny CP2K success/failed outputs, and fake Slurm state
files. Exercises the logic chain INIT -> TRAIN -> EXPLORE -> SCREEN -> LABEL
-> UPDATE -> VALIDATED through the tesla-mlp-training validation scripts:

- check_tesla_project.py        (project skeleton)
- check_dataset_fingerprint.py  (INIT / UPDATE dataset contract)
- check_iteration.py            (TRAIN..VALIDATED markers + manifest)

Semantics under test (frozen spec §5/§30): `*.done` = COMPLETED, never
VALIDATED; iteration validated only when every stage carries a
`.validated` marker; the iteration manifest carries the dataset-digest
chain and balanced label counts. No real DFT/MD/Slurm is involved.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

TESLA_SCRIPTS = (
    Path(__file__).resolve().parents[1]
    / "skills/procedures/tesla-mlp-training/scripts"
)

STAGES = ["01_train", "02_explore", "03_screen", "04_label", "05_update"]

DIGEST_A = "sha256:aaaa"
DIGEST_B = "sha256:bbbb"
DIGEST_C = "sha256:cccc"


def _run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TESLA_SCRIPTS / script), *args],
        capture_output=True,
        text=True,
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ── fixture builders ────────────────────────────────────────────────────


def build_project(root: Path, workdir: str = "20-workdir") -> None:
    """Minimal TESLA skeleton: 00-config, 01-workflow, workdir, run.sh."""
    (root / "00-config").mkdir(parents=True)
    (root / "01-workflow").mkdir(parents=True)
    (root / workdir).mkdir(parents=True)
    _write(root / "run.sh", "#!/bin/bash\n# fake driver — never executed\n")


def build_dpdata_system(path: Path, frames: int = 1) -> None:
    """Tiny dpdata System: 2 H atoms, 1 frame, energy+force labels."""
    natoms = 2
    _write(path / "type.raw", "0 0\n")
    _write(path / "type_map.raw", "H\n")
    _write(path / "set.000" / "coord.raw", " ".join(["0.0 0.0 0.0"] * natoms) + "\n")
    _write(path / "set.000" / "energy.raw", "-0.5\n")
    _write(path / "set.000" / "force.raw", " ".join(["0.0 0.0 0.0"] * natoms) + "\n")
    assert frames == 1, "fixture is single-frame by construction"


def build_iteration(
    root: Path,
    *,
    done: bool = True,
    validated: bool = True,
    manifest: dict | None = None,
) -> None:
    """One iteration dir with stage artifacts; markers controlled by flags."""
    for stage in STAGES:
        (root / stage).mkdir(parents=True, exist_ok=True)
        if done:
            _write(root / f"{stage}.done", "")
        if validated:
            _write(root / f"{stage}.validated", "")
    # stage artifacts matching check_iteration DEFAULT_ARTIFACTS globs
    _write(root / "01_train" / "graph.000.pb", "fake model")
    _write(root / "01_train" / "lcurve.out", "# fake learning curve\n0 1.0 1.1\n")
    _write(root / "01_train" / "slurm-42.out", "State: COMPLETED\n")
    _write(root / "02_explore" / "model_devi.out", "0 0.05 0.02 0.01\n")
    _write(root / "03_screen" / "candidates.xyz", "2\nfake\nH 0 0 0\nH 0.7 0 0\n")
    _write(root / "04_label" / "cp2k_success.out", "SCF run converged\nPROGRAM ENDED AT\n")
    _write(root / "04_label" / "cp2k_failed.out", "SCF run not converged\n")
    build_dpdata_system(root / "05_update")
    if manifest is not None:
        _write(root / "iteration-manifest.json", json.dumps(manifest, indent=2))


def build_golden_project(root: Path) -> dict:
    """Full golden-path fixture; returns the iter-1 manifest."""
    build_project(root)
    build_dpdata_system(root / "init_data")
    manifest = {
        "iteration_id": "iter-1",
        "parent_dataset_digest": DIGEST_A,
        "training_dataset_digest": DIGEST_A,  # equals previous updated digest
        "models": ["20-workdir/iter-1/01_train/graph.000.pb"],
        "exploration_conditions": [
            {"replica": 0, "temperature_k": 300, "pressure_bar": 1, "steps": 1000, "seed": 7}
        ],
        "candidate_count": 3,
        "selected_count": 2,
        "label_success_count": 2,
        "label_failure_count": 0,
        "updated_dataset_digest": DIGEST_B,
        "validation_status": "validated",
    }
    build_iteration(root / "20-workdir" / "iter-1", manifest=manifest)
    return manifest


# ── tests: logic chain INIT -> TRAIN -> EXPLORE -> SCREEN -> LABEL -> UPDATE -> VALIDATED


def test_project_skeleton_passes(tmp_path):
    build_project(tmp_path / "p")
    r = _run("check_tesla_project.py", "--project-root", str(tmp_path / "p"))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["status"] == "pass"


def test_init_dataset_fingerprint_passes(tmp_path):
    build_dpdata_system(tmp_path / "init_data")
    r = _run(
        "check_dataset_fingerprint.py",
        "--system", str(tmp_path / "init_data"),
        "--expected-frames", "1",
        "--expected-natoms", "2",
        "--expected-type-map", "H",
        "--expected-labels", "energy,force",
    )
    assert r.returncode == 0, r.stdout
    v = json.loads(r.stdout)
    assert v["status"] == "pass"
    assert v["computed"] == {
        "frames": 1, "natoms": 2, "type_map": ["H"],
        "labels": {"energy": True, "force": True, "virial": False},
    }


def test_iteration_validated_passes(tmp_path):
    """TRAIN..UPDATE 全链：done + validated 齐备 -> pass。"""
    build_iteration(tmp_path / "iter-1")
    r = _run("check_iteration.py", "--workdir", str(tmp_path), "--iteration", "iter-1")
    assert r.returncode == 0, r.stderr
    v = json.loads(r.stdout)
    assert v["status"] == "pass"
    assert v["all_completed"] is True and v["all_validated"] is True
    assert {s["stage"] for s in v["stages"]} == set(STAGES)


def test_done_does_not_equal_validated(tmp_path):
    """*.done 只等于 COMPLETED：缺 validated 标记 -> degraded（exit 1）。"""
    build_iteration(tmp_path / "iter-0", done=True, validated=False)
    r = _run("check_iteration.py", "--workdir", str(tmp_path), "--iteration", "iter-0")
    assert r.returncode == 1
    v = json.loads(r.stdout)
    assert v["status"] == "degraded"
    assert v["all_completed"] is True and v["all_validated"] is False
    assert any("completed but NOT validated" in w for w in v["warnings"])


def test_missing_stage_fails(tmp_path):
    """缺一个 stage 目录 -> fail（链路不完整）。"""
    build_iteration(tmp_path / "iter-1")
    shutil.rmtree(tmp_path / "iter-1" / "04_label")
    r = _run("check_iteration.py", "--workdir", str(tmp_path), "--iteration", "iter-1")
    assert r.returncode == 1
    assert json.loads(r.stdout)["status"] == "fail"


def test_manifest_digest_chain_and_label_balance(tmp_path):
    """Golden Path manifest：digest 链闭合、label 计数平衡、validation_status 一致。"""
    build_golden_project(tmp_path / "p")
    manifest = json.loads(
        (tmp_path / "p/20-workdir/iter-1/iteration-manifest.json").read_text()
    )
    # chain: TRAIN consumed parent digest; UPDATE produced a new dataset digest
    assert manifest["training_dataset_digest"] == manifest["parent_dataset_digest"]
    assert manifest["updated_dataset_digest"] != manifest["parent_dataset_digest"]
    # label balance: success + failure == selected (after dedupe)
    assert (
        manifest["label_success_count"] + manifest["label_failure_count"]
        == manifest["selected_count"]
    )
    # check_iteration echoes the manifest and agrees it is validated
    r = _run(
        "check_iteration.py",
        "--workdir", str(tmp_path / "p/20-workdir"),
        "--iteration", "iter-1",
    )
    assert r.returncode == 0, r.stderr
    v = json.loads(r.stdout)
    assert v["manifest"]["validation_status"] == "validated"
    assert v["manifest"]["iteration_id"] == "iter-1"


def test_fingerprint_mismatch_detected(tmp_path):
    """UPDATE 后 dataset 必须与声明的 fingerprint 一致；不一致 -> fail。"""
    build_dpdata_system(tmp_path / "sys")
    r = _run(
        "check_dataset_fingerprint.py",
        "--system", str(tmp_path / "sys"),
        "--expected-frames", "7",  # wrong on purpose
    )
    assert r.returncode == 1
    v = json.loads(r.stdout)
    assert v["status"] == "fail"
    assert any("frames 1 != expected 7" in e for e in v["errors"])


def test_golden_path_end_to_end(tmp_path):
    """完整 Golden Path 验收：INIT -> TRAIN -> EXPLORE -> SCREEN -> LABEL -> UPDATE -> VALIDATED。

    每个环节都在纯 fixture 上通过；全程无真实计算（无 DFT、无 MD、无 Slurm 提交）。
    """
    root = tmp_path / "p"
    manifest = build_golden_project(root)

    # INIT: 初始数据集 fingerprint 校验
    init = _run(
        "check_dataset_fingerprint.py",
        "--system", str(root / "init_data"),
        "--expected-frames", "1", "--expected-natoms", "2",
        "--expected-type-map", "H", "--expected-labels", "energy,force",
    )
    assert init.returncode == 0, init.stdout

    # TRAIN/EXPLORE/SCREEN/LABEL/UPDATE: 每阶段产物存在且完成
    it = _run(
        "check_iteration.py",
        "--workdir", str(root / "20-workdir"),
        "--iteration", "iter-1",
    )
    assert it.returncode == 0, it.stderr
    v = json.loads(it.stdout)
    artifacts = {s["stage"]: s["artifacts"] for s in v["stages"]}
    assert any(a.endswith("graph.000.pb") for a in artifacts["01_train"])
    assert any(a.endswith("model_devi.out") for a in artifacts["02_explore"])
    assert any(a.endswith("candidates.xyz") for a in artifacts["03_screen"])
    assert any(a.endswith("cp2k_success.out") for a in artifacts["04_label"])
    assert any(a.endswith("type.raw") for a in artifacts["05_update"])

    # LABEL: tiny CP2K 输出语义（成功含 PROGRAM ENDED AT；失败输出不含）
    success = (root / "20-workdir/iter-1/04_label/cp2k_success.out").read_text()
    failed = (root / "20-workdir/iter-1/04_label/cp2k_failed.out").read_text()
    assert "PROGRAM ENDED AT" in success and "PROGRAM ENDED AT" not in failed

    # UPDATE: 更新后的 dataset fingerprint
    upd = _run(
        "check_dataset_fingerprint.py",
        "--system", str(root / "20-workdir/iter-1/05_update"),
        "--expected-frames", "1", "--expected-natoms", "2",
        "--expected-type-map", "H", "--expected-labels", "energy,force",
    )
    assert upd.returncode == 0, upd.stdout

    # VALIDATED: 迭代整体 validated（且 manifest 断言 validation_status）
    assert v["all_validated"] is True
    assert v["manifest"]["validation_status"] == "validated"
    assert v["manifest"]["updated_dataset_digest"] == DIGEST_B
