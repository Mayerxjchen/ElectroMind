"""DeePMD 训练数据门（P2.5）。

铁律：只有用户/独立 Reviewer 确认后的 ACCEPTED Artifact 才能进入
DeePMD 训练数据。COMPLETED / VALIDATED / REJECTED / SUPERSEDED /
未验证一律排除。

- :func:`accepted_for_training`：从 registry 取 ACCEPTED Artifact，
  返回可写盘的结构化训练样本（带 SHA 校验，防读取时文件被改）。
- 训练数据打包方只允许调用本模块；任何跳过 ACCEPTED 门去拿
  VALIDATED/COMPLETED 产物的路径都是 bug。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .manifest import ArtifactManifest, ArtifactStatus
from .registry import ArtifactIntegrityError, ArtifactRegistry


class TrainingDataGateError(ValueError):
    """试图把未 ACCEPTED 的 Artifact 放进训练集。"""


def accepted_for_training(
    registry: ArtifactRegistry,
    *,
    root: Path,
    verify_sha: bool = True,
) -> list[dict[str, Any]]:
    """返回可进入 DeePMD 训练数据的样本。

    每个样本 = {artifact_id, path, sha256, units, parser, accepted_by, run_id}。
    只含 ACCEPTED 且（可选）SHA 校验通过的 Artifact。
    """
    samples: list[dict[str, Any]] = []
    for manifest in registry.training_data_candidates():
        assert manifest.acceptance_status is ArtifactStatus.ACCEPTED
        if verify_sha:
            try:
                registry.verify_integrity(manifest, root)
            except ArtifactIntegrityError as exc:
                # 文件被改过 → 数据不可信，绝不能进训练集
                raise TrainingDataGateError(
                    f"training data gate: {exc}（文件内容与登记时不一致，"
                    "禁止进入训练集）"
                ) from exc
        samples.append(
            {
                "artifact_id": manifest.artifact_id,
                "path": str(Path(manifest.path)),
                "sha256": manifest.sha256,
                "units": manifest.units,
                "parser": manifest.parser,
                "accepted_by": manifest.accepted_by,
                "run_id": manifest.run_id,
            }
        )
    return samples


def assert_accepted(manifest: ArtifactManifest) -> None:
    """断言单个 manifest 已达到 ACCEPTED；否则抛 TrainingDataGateError。"""
    if manifest.acceptance_status is not ArtifactStatus.ACCEPTED:
        raise TrainingDataGateError(
            f"artifact {manifest.artifact_id} 状态为 {manifest.acceptance_status}，"
            "未 ACCEPTED，不能进入 DeePMD 训练数据"
        )
