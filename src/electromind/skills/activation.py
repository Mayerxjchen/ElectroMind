"""SKILL-4: atomic Skill activation.

The activation transaction (RFC section 六) runs in strict order:

    1. resolve from the run-frozen catalog generation
    2. validate trust / enabled state / capability
    3. parse and validate invocation arguments
    4. create the content-addressed snapshot (private store)
    5. complete the target-environment mount
    6. persist the ``SkillActivationItem``
    7. return the payload — the *caller* injects the body into the model
       context only after steps 1–6 succeeded
    8. publish the ``skill/activated`` event (via callback)

Invariants:

- The body never reaches the model context before snapshot + mount + item
  persistence have all succeeded.
- A failed activation leaves no half-activated state (no item, mount rolled
  back).
- Re-submitting the same ``(request_id, run_id, skill_id)`` returns the same
  activation result (idempotent).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

from .candidate import SkillCandidate
from .catalog import MultiCandidateCatalog, SkillResolutionError, SkillResolver
from .snapshot import hash_content
from .snapstore import PrivateSnapshotStore, SkillSnapshotRef

# Activation states (RFC section 六).
REQUESTED = "requested"
RESOLVING = "resolving"
SNAPSHOTTING = "snapshotting"
MOUNTING = "mounting"
ACTIVATED = "activated"
FAILED = "failed"
CANCELLED = "cancelled"

_TERMINAL = {ACTIVATED, FAILED, CANCELLED}


# ---------------------------------------------------------------------------
# Structured invocation protocol (RFC section 十二)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SkillInput:
    """Structured skill invocation (the CLI parses ``/cp2k input.inp`` into this)."""

    type: str = "skill"
    skillId: str | None = None
    name: str | None = None
    arguments: str | Mapping[str, str] | None = None

    def as_argument_map(self) -> dict[str, str]:
        """Normalize ``arguments`` into a mapping.

        A plain string becomes ``{"_": "<string>"}``; a mapping is copied
        verbatim.
        """
        if self.arguments is None:
            return {}
        if isinstance(self.arguments, str):
            return {"_": self.arguments}
        return dict(self.arguments)


@dataclass(frozen=True, slots=True)
class ActivationRequest:
    """A request to activate one Skill within a run."""

    request_id: str
    thread_id: str
    run_id: str
    skill_id: str  # qualified id — the resolver persists the qualified form
    arguments: Mapping[str, str] = field(default_factory=dict)
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SkillActivationItem:
    """The persisted record of one activation (RFC section 六)."""

    activation_id: str
    request_id: str
    thread_id: str
    run_id: str
    skill_id: str
    catalog_generation: int
    descriptor_digest: str
    snapshot_ref: str
    target_id: str | None
    mounted_root: str | None
    arguments: Mapping[str, str]
    status: str
    created_at: str


@dataclass(frozen=True, slots=True)
class SkillActivationResult:
    """Outcome of a successful activation (payload for context injection)."""

    item: SkillActivationItem
    payload: dict
    reused: bool = False


class ActivationError(Exception):
    """An activation that cannot complete."""

    def __init__(self, message: str, *, needs_trust: bool = False) -> None:
        super().__init__(message)
        self.needs_trust = needs_trust


# ---------------------------------------------------------------------------
# Mounter interface
# ---------------------------------------------------------------------------


class SkillMounter(Protocol):
    """Mounts a snapshot into the target execution environment.

    Implementations: Local / Container in SKILL-5; SSH separately.
    """

    async def mount(self, ref: SkillSnapshotRef) -> str:
        """Mount *ref* and return the agent-visible mounted root."""
        ...

    async def rollback(self, mounted_root: str) -> None:
        """Undo a mount when a later transaction step fails."""
        ...


# ---------------------------------------------------------------------------
# Parameter substitution (RFC section 十二)
# ---------------------------------------------------------------------------


_SUBSTITUTION_NAMES = ("$ARGUMENTS", "$0", "$1", "$filename", "$format")


def substitute_body(
    body: str,
    arguments: Mapping[str, str],
    *,
    positional: tuple[str, ...] = (),
) -> str:
    """Apply parameter substitution to *body* before snapshotting.

    Supported tokens (RFC section 十二): ``$ARGUMENTS`` (all arguments joined),
    ``$0``/``$1``/… (positional), ``$filename`` and ``$format`` (named
    arguments).  Missing values substitute as empty strings; the final body's
    digest is computed after substitution.
    """
    values = dict(arguments)
    positional_list = list(positional)

    def _value(token: str) -> str:
        if token == "$ARGUMENTS":
            return " ".join(v for v in values.values() if v)
        if token == "$0":
            return positional_list[0] if positional_list else ""
        if token.startswith("$") and token[1:].isdigit():
            idx = int(token[1:])
            return positional_list[idx] if idx < len(positional_list) else ""
        if token == "$filename":
            return values.get("filename", "")
        if token == "$format":
            return values.get("format", "")
        return values.get(token[1:], "")

    out = body
    for token in _SUBSTITUTION_NAMES:
        if token in out:
            out = out.replace(token, _value(token))
    # Named argument tokens ($name for arbitrary keys)
    for key, value in values.items():
        out = out.replace(f"${key}", value)
    return out


def digest_of_body(body: str) -> str:
    """Content digest of the (possibly substituted) activation body."""
    return hash_content(body)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SkillActivationService:
    """Executes the atomic activation transaction (RFC section 六)."""

    def __init__(
        self,
        catalog: MultiCandidateCatalog,
        *,
        store: PrivateSnapshotStore | None = None,
        mounter: SkillMounter | None = None,
        items_dir: Path | None = None,
        on_activated: Callable[[SkillActivationItem], None] | None = None,
        now: Callable[[], str] | None = None,
        resolution: Mapping[str, str] | None = None,
    ) -> None:
        self.catalog = catalog
        self.store = store or PrivateSnapshotStore()
        self.mounter = mounter
        self.items_dir = items_dir or self.store.root.parent / "activations"
        self.on_activated = on_activated
        self._now = now or _default_now
        # RFC section 十一: default-resolution pins.  When the caller does not
        # pass them explicitly, the pins carried by the frozen catalog are
        # used — so `SkillCatalogService(...).list()` → `SkillActivationService`
        # wiring keeps pins working without manual re-passing.  The SAME map
        # feeds the qualified-resolve path and the name-resolution path, so a
        # pinned same-name skill is never reported ambiguous.
        self.resolution = dict(
            resolution if resolution is not None else (catalog.resolution or {})
        )
        self._resolver = SkillResolver(catalog, resolution=self.resolution)
        self._items: dict[tuple[str, str, str], SkillActivationItem] = {}

    # -- public -----------------------------------------------------------

    async def activate(
        self,
        request: ActivationRequest,
    ) -> SkillActivationResult:
        """Run the activation transaction.

        Raises ``ActivationError`` on any failure.  The returned payload must
        be injected into the model context *by the caller* — only after this
        method returns does the body exist on the mount.
        """
        # Idempotency: same (request_id, run_id, skill_id) → same result.
        # The replay payload is restored from the private snapshot store so a
        # repeated request returns the SAME body, not an empty instructions.
        key = (request.request_id, request.run_id, request.skill_id)
        existing = self._items.get(key)
        if existing is not None:
            replay_payload = self._restore_payload(existing)
            return SkillActivationResult(
                item=existing,
                payload=replay_payload,
                reused=True,
            )

        item = self._begin_item(request)
        mounted_root: str | None = None
        ref: SkillSnapshotRef | None = None
        try:
            # 1. resolve from the run-frozen catalog generation
            item = self._with_status(item, RESOLVING)
            resolved = self._resolver.resolve_qualified(
                request.skill_id, capabilities=request.capabilities
            )
            item = replace(
                item,
                descriptor_digest=resolved.candidate.descriptor.content_digest,
            )
            # 2. trust / enabled / capability — validated by the resolver
            # 3. read + validate the body (substitution before snapshot)
            body = self._read_body(resolved.candidate)
            substituted = substitute_body(body, request.arguments)
            # 4. content-addressed snapshot
            item = self._with_status(item, SNAPSHOTTING)
            ref = self._snapshot(resolved.candidate, substituted)
            resources = self.store.read_resources(ref)
            # 5. target-environment mount
            item = self._with_status(item, MOUNTING)
            mounted_root = await self._mount(ref)
            # 6. persist the activation item — only now may the body be seen
            item = self._with_status(
                item, ACTIVATED, ref=ref, mounted_root=mounted_root
            )
            self._persist(item)
            self._items[key] = item
            # 8. publish the event
            if self.on_activated is not None:
                self.on_activated(item)
            return SkillActivationResult(
                item=item,
                payload=_build_payload(
                    item,
                    body=substituted,
                    ref=ref,
                    candidate=resolved.candidate,
                    resources=resources,
                ),
            )
        except SkillResolutionError as exc:
            self._mark_failed(item)
            raise ActivationError(str(exc), needs_trust=exc.needs_trust) from exc
        except Exception as exc:
            # Roll back the mount — no half-activated state.
            if mounted_root is not None and self.mounter is not None:
                try:
                    await self.mounter.rollback(mounted_root)
                except Exception:
                    pass
            self._mark_failed(item)
            raise ActivationError(str(exc)) from exc

    def _restore_payload(self, item: SkillActivationItem) -> dict:
        """Rebuild the activation payload from the persisted snapshot.

        The stored body (post-substitution) is read from the private snapshot
        store via ``item.snapshot_ref`` (a digest).  When the snapshot is gone
        (e.g. GC'd), the item's descriptor digest is returned instead of an
        empty body — the caller sees a degraded but honest payload.
        """
        body = ""
        resources: tuple[str, ...] = ()
        if item.snapshot_ref:
            ref = SkillSnapshotRef(
                digest=item.snapshot_ref,
                store="private",
                locator="",
            )
            stored = self.store.read_body(ref)
            if stored is not None:
                body = stored
            resources = self.store.read_resources(ref)
        # P1-4: replay keeps the full payload contract — candidate metadata
        # (resource_digest etc.) is resolved from the frozen catalog.
        candidate = next(
            (c for c in self.catalog.candidates if c.skill_id == item.skill_id),
            None,
        )
        payload = _build_payload(item, candidate=candidate, resources=resources)
        payload["instructions"] = body
        return payload

    # -- transaction steps ------------------------------------------------

    def _begin_item(self, request: ActivationRequest) -> SkillActivationItem:
        activation_id = _activation_id(
            request.request_id, request.run_id, request.skill_id
        )
        return SkillActivationItem(
            activation_id=activation_id,
            request_id=request.request_id,
            thread_id=request.thread_id,
            run_id=request.run_id,
            skill_id=request.skill_id,
            catalog_generation=self.catalog.generation,
            descriptor_digest="",
            snapshot_ref="",
            target_id=None,
            mounted_root=None,
            arguments=dict(request.arguments),
            status=REQUESTED,
            created_at=self._now(),
        )

    def _read_body(self, candidate: SkillCandidate) -> str:
        """Return the body frozen at catalog construction (run-freeze).

        Activation NEVER re-reads the live SKILL.md file: the current run
        must consume exactly the content captured by its frozen catalog
        generation (RFC section 八).  A missing frozen body (e.g. restored
        catalog without a snapshot) fails the activation instead of falling
        back to disk.
        """
        bodies = self.catalog.frozen_bodies or {}
        body = bodies.get(candidate.skill_id)
        if body is None:
            raise ActivationError(
                f"no frozen body for {candidate.skill_id} in catalog "
                f"generation {self.catalog.generation}"
            )
        return body

    def _snapshot(
        self, candidate: SkillCandidate, substituted_body: str
    ) -> SkillSnapshotRef:
        # P0-2: build the snapshot ONLY from the frozen catalog resources —
        # never a live re-read of resource files (TOCTOU closure).
        frozen = self.catalog.frozen_resources or {}
        resources = frozen.get(candidate.skill_id)
        return self.store.save(
            name=candidate.descriptor.name,
            body=substituted_body,
            resources=resources,
        )

    async def _mount(self, ref: SkillSnapshotRef) -> str | None:
        if self.mounter is None:
            return None
        return await self.mounter.mount(ref)

    # -- item bookkeeping -------------------------------------------------

    def _with_status(
        self,
        item: SkillActivationItem,
        status: str,
        *,
        ref: SkillSnapshotRef | None = None,
        mounted_root: str | None = None,
    ) -> SkillActivationItem:
        """Return *item* with the given status (items are immutable)."""
        return replace(
            item,
            status=status,
            snapshot_ref=(ref.digest if ref is not None else item.snapshot_ref),
            mounted_root=(
                mounted_root if mounted_root is not None else item.mounted_root
            ),
        )

    def _mark_failed(self, item: SkillActivationItem) -> None:
        failed = replace(item, status=FAILED)
        self._persist(failed)

    def _persist(self, item: SkillActivationItem) -> None:
        self.items_dir.mkdir(parents=True, exist_ok=True)
        path = self.items_dir / f"{item.activation_id}.json"
        path.write_text(
            json.dumps(
                {
                    "activation_id": item.activation_id,
                    "request_id": item.request_id,
                    "thread_id": item.thread_id,
                    "run_id": item.run_id,
                    "skill_id": item.skill_id,
                    "catalog_generation": item.catalog_generation,
                    "descriptor_digest": item.descriptor_digest,
                    "snapshot_ref": item.snapshot_ref,
                    "target_id": item.target_id,
                    "mounted_root": item.mounted_root,
                    "arguments": dict(item.arguments),
                    "status": item.status,
                    "created_at": item.created_at,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def load_persisted(self, activation_id: str) -> SkillActivationItem | None:
        """Load an item persisted by a previous run (resume support)."""
        path = self.items_dir / f"{activation_id}.json"
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return SkillActivationItem(**data)


def _activation_id(request_id: str, run_id: str, skill_id: str) -> str:
    """Deterministic activation id — retries of the same request map to it."""
    return f"act-{hash_content(request_id, run_id, skill_id)[:12]}"


# ---------------------------------------------------------------------------
# use_skill compat adapter (RFC section 九 / 十四)
# ---------------------------------------------------------------------------


def make_activation_use_skill_tool(
    service: SkillActivationService,
    *,
    thread_id: str,
    run_id: str,
    request_id_factory: Callable[[], str] | None = None,
    capabilities: Sequence[str] = (),
):
    """Build a ``use_skill(name)`` tool backed by ``SkillActivationService``.

    Compatible entry point: the legacy ``make_use_skill_tool`` read the body
    directly from the registry; this adapter constructs an ``ActivationRequest``
    and runs the atomic transaction instead.  The name is kept for at least one
    formal release cycle (RFC section 九), and the new model tool is
    ``activate_skill`` (see ``make_activate_skill_tool``).

    ``capabilities`` are the frozen Run capabilities: name resolution and the
    activation request both carry them, so an SSH-only Skill cannot be
    activated from a local-only run through this tool.
    """
    from ..core.tool import FunctionTool

    capabilities = tuple(capabilities)

    async def use_skill(name: str) -> str:
        request_id = (
            request_id_factory()
            if request_id_factory is not None
            else _new_request_id()
        )
        skill_id = _resolve_invocation_skill_id(
            service, name, capabilities=capabilities
        )
        if skill_id is None:
            return json.dumps(
                {
                    "ok": False,
                    "error": f"无法解析 skill: {name!r}（无可用候选或存在歧义）",
                    "error_code": "skill_unresolved",
                    "skill_id": name,
                    "status": f"required capability unavailable: {name}",
                    "available": service.catalog.names(),
                },
                ensure_ascii=False,
            )
        request = ActivationRequest(
            request_id=request_id,
            thread_id=thread_id,
            run_id=run_id,
            skill_id=skill_id,
            capabilities=capabilities,
        )
        try:
            result = await service.activate(request)
        except ActivationError as exc:
            return json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "error_code": "activation_failed",
                    "skill_id": name,
                    "needs_trust": exc.needs_trust,
                },
                ensure_ascii=False,
            )
        return json.dumps(result.payload, ensure_ascii=False)

    return FunctionTool(
        name="use_skill",
        description=(
            "加载一个 skill 的完整说明书并挂载其资源。"
            "当任意 skill 文档说“Activate the `X` skill”时，即表示调用本工具"
            "（name=X）。"
            "返回 JSON：{ok, name, skill_id, instructions, snapshot_ref, "
            "mounted_root, generation, status}。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "要加载的 skill 名字（或 qualified id）。",
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        func=use_skill,
    )


def make_activate_skill_tool(
    service: SkillActivationService,
    *,
    thread_id: str,
    run_id: str,
    capabilities: Sequence[str] = (),
):
    """The new model tool: structured ``activate_skill`` (RFC section 九).

    Accepts ``{skillId?, name?, arguments?}`` matching ``SkillInput``.
    ``capabilities`` are the frozen Run capabilities — name resolution and
    the activation request both carry them.
    """
    from ..core.tool import FunctionTool

    capabilities = tuple(capabilities)

    async def activate_skill(
        skillId: str | None = None,
        name: str | None = None,
        arguments: str | Mapping[str, str] | None = None,
    ) -> str:
        request_id = _new_request_id()
        if skillId is None and name is None:
            return json.dumps(
                {
                    "ok": False,
                    "error": "skillId or name is required",
                    "error_code": "invalid_request",
                },
                ensure_ascii=False,
            )
        target = skillId or name or ""
        # A plain `name` must go through the unqualified resolver — it is NOT
        # a qualified id and would otherwise be reported unknown.
        if skillId is None:
            resolved = _resolve_invocation_skill_id(
                service, target, capabilities=capabilities
            )
            if resolved is None:
                return json.dumps(
                    {
                        "ok": False,
                        "error": f"无法解析 skill: {target!r}（无可用候选或存在歧义）",
                        "error_code": "skill_unresolved",
                        "skill_id": target,
                        "status": f"required capability unavailable: {target}",
                        "available": service.catalog.names(),
                    },
                    ensure_ascii=False,
                )
            target = resolved
        request = ActivationRequest(
            request_id=request_id,
            thread_id=thread_id,
            run_id=run_id,
            skill_id=target,
            arguments=SkillInput(name=name, arguments=arguments).as_argument_map(),
            capabilities=capabilities,
        )
        try:
            result = await service.activate(request)
        except ActivationError as exc:
            return json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "error_code": "activation_failed",
                    "skill_id": target,
                    "needs_trust": exc.needs_trust,
                },
                ensure_ascii=False,
            )
        return json.dumps(result.payload, ensure_ascii=False)

    return FunctionTool(
        name="activate_skill",
        description=(
            "激活一个 skill：解析候选、校验信任、创建快照、挂载资源后返回"
            "完整说明书。当任意 skill 文档说“Activate the `X` skill”时，即表示"
            "调用本工具（name=X）。skillId 优先（qualified id），否则按 name 解析。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "skillId": {
                    "type": "string",
                    "description": "Qualified skill id（如 project:repo:agents:cp2k）。",
                },
                "name": {
                    "type": "string",
                    "description": "Skill 名字（无歧义时可用）。",
                },
                "arguments": {
                    "description": "调用参数（字符串或映射）。",
                },
            },
            "additionalProperties": False,
        },
        func=activate_skill,
    )


def _new_request_id() -> str:
    return f"req-{uuid.uuid4().hex[:12]}"


def _resolve_invocation_skill_id(
    service: "SkillActivationService",
    name_or_id: str,
    *,
    capabilities: Sequence[str] = (),
) -> str | None:
    """Resolve a user/model invocation target to a qualified skill id.

    - Exact qualified id in the catalog → used as-is.
    - Otherwise treated as a bare name → resolved through the unqualified
      resolver (unique candidate or resolution pin) with the Run
      capabilities applied.  Ambiguity or capability mismatch returns
      ``None`` (the caller reports the failure — never a silent pick).
    """
    from .catalog import SkillResolutionAmbiguous, SkillResolutionError

    catalog = service.catalog
    by_qualified = catalog.by_qualified_id()
    if name_or_id in by_qualified:
        return name_or_id
    # Use the service's resolver so [skills.resolution] pins apply — a pinned
    # same-name skill resolves instead of being reported ambiguous.
    resolver = service._resolver
    try:
        resolved = resolver.resolve_unqualified(
            name_or_id, interactive=False, capabilities=capabilities
        )
    except (SkillResolutionAmbiguous, SkillResolutionError):
        return None
    return resolved.candidate.skill_id


def _build_payload(
    item: SkillActivationItem,
    *,
    body: str = "",
    ref: SkillSnapshotRef | None = None,
    candidate: SkillCandidate | None = None,
    resources: tuple[str, ...] = (),
) -> dict:
    """The payload the caller may inject into the model context.

    Only called after the transaction fully succeeded.  Includes the legacy
    ``description`` field when the candidate is known so the phase-2 runtime
    keeps the compat ``use_skill`` contract (RFC section 九).

    A+ §7: during the compat period the payload carries both the legacy
    ``mounted_root`` and the standard-skill ``skill_root`` (equal for now),
    plus the mounted ``resources`` as skill-relative paths.  No destructive
    payload removal happens in this migration.
    """
    payload = {
        "ok": True,
        "name": item.skill_id.rsplit(":", 1)[-1],
        "skill_id": item.skill_id,
        "activation_id": item.activation_id,
        "instructions": body,
        "snapshot_ref": str(ref) if ref else item.snapshot_ref,
        "mounted_root": item.mounted_root,
        "skill_root": item.mounted_root,
        "generation": item.catalog_generation,
        "status": item.status,
    }
    if candidate is not None:
        payload["description"] = candidate.descriptor.description
        payload["resource_digest"] = candidate.descriptor.resource_digest
    # P1-4: `resources` is always present (empty list for resource-less
    # skills) so the payload schema is stable across activations/replays.
    payload["resources"] = list(resources)
    return payload


def _default_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
