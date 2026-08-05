"""Artifact 与 Provenance（M6，非 HPC 部分）。

- ``manifest``：ArtifactManifest + 严格状态语义（completed ≠ validated ≠ accepted）
- ``registry``：ArtifactRegistry（SHA-256、完整性、依赖图、事件记录）
"""

from .manifest import (
    ArtifactManifest,
    ArtifactStatus,
    ArtifactTransitionError,
    allowed_artifact_transitions,
)
from .provenance import ProvenanceStore, ValueProvenance
from .registry import (
    ArtifactIntegrityError,
    ArtifactRegistry,
    sha256_file,
)
from .training import TrainingDataGateError, accepted_for_training, assert_accepted

__all__ = [
    "ArtifactIntegrityError",
    "ArtifactManifest",
    "ArtifactRegistry",
    "ArtifactStatus",
    "ArtifactTransitionError",
    "allowed_artifact_transitions",
    "ProvenanceStore",
    "ValueProvenance",
    "sha256_file",
    "TrainingDataGateError",
    "accepted_for_training",
    "assert_accepted",
]
