"""ModelResolver —— P3：Auto Model 的确定性解析（唯一权威）。

输入：
    Thread Model Policy（用户选择：auto / profile / hybrid / named）
    + Session Mode（ask / plan / agent）
    + Skill Requirement（可选：要求的最低档位）
    + Provider Availability（可用模型列表）
    + Configured Route Table（档位 → 模型）

输出：
    ModelResolution(policy, effective_model, reason, phase, fallback?)

规则（修订版文档 §7）：
    Ask   → fast
    Plan  → best
    Agent → balanced
    复杂失败恢复 / 科学验证 → best
    Skill 声明最低能力 → 满足要求的模型
    Plan → Execute（hybrid）：plan 阶段 best，批准后 execute 阶段 balanced

固定规则：
    - 每次 Run 开始时解析一次；Run 开始后不因普通重试切换模型
    - 实际模型必须从可用模型列表中选择；第一版不自动跨服务商切换
    - Fallback 必须携带原模型/替代模型/错误分类/时间/是否已产生副作用

纯模块（无 IO / 无 harness 依赖）—— 可单测。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# ── 档位 ────────────────────────────────────────────────────────────

Profile = Literal["fast", "balanced", "best"]

# 默认路由表：档位 → 模型 id。用户配置可覆盖。
DEFAULT_ROUTE: dict[Profile, str] = {
    "fast": "deepseek-v4-flash",
    "balanced": "deepseek-v4-pro",
    "best": "deepseek-v4-pro",
}

# 默认可用模型（未显式配置时）
DEFAULT_AVAILABLE_MODELS: tuple[str, ...] = (
    "deepseek-v4-flash",
    "deepseek-v4-pro",
)

# 档位排序（用于 Skill Requirement 的"至少达到"判断）
_PROFILE_RANK: dict[Profile, int] = {"fast": 1, "balanced": 2, "best": 3}


# ── 政策 ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ModelPolicy:
    """Thread 的模型选择。kind + 具体字段。"""

    kind: Literal["auto", "profile", "hybrid", "named"]
    profile: Profile | None = None  # kind=profile
    hybrid: Literal["plan-execute"] | None = None  # kind=hybrid
    model_id: str | None = None  # kind=named


AUTO_POLICY = ModelPolicy(kind="auto")

# 用户配置路由表：档位 → 模型 id（缺省回退 DEFAULT_ROUTE）。
RouteTable = dict[Profile, str]


def parse_model_policy(raw: str | None) -> ModelPolicy:
    """把 model 字段字符串解析为 ModelPolicy。

    "auto" → auto；"fast"/"balanced"/"best" → profile；
    "plan-execute" → hybrid；其余非空串 → named(model_id)；
    空/None → auto。
    """
    if not raw:
        return AUTO_POLICY
    value = raw.strip()
    if value == "auto":
        return AUTO_POLICY
    if value in ("fast", "balanced", "best"):
        return ModelPolicy(kind="profile", profile=value)  # type: ignore[arg-type]
    if value == "plan-execute":
        return ModelPolicy(kind="hybrid", hybrid="plan-execute")
    return ModelPolicy(kind="named", model_id=value)


def policy_label(policy: ModelPolicy) -> str:
    """展示用政策标签：Auto / Fast / Balanced / Best / Plan→Execute / named:<id>。"""
    if policy.kind == "auto":
        return "Auto"
    if policy.kind == "profile":
        return policy.profile.title() if policy.profile else "Auto"
    if policy.kind == "hybrid":
        return "Plan→Execute"
    return f"named:{policy.model_id}" if policy.model_id else "Auto"


# ── 解析结果 ────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ModelResolution:
    policy: str  # 展示标签（policy_label）
    effective_model: str
    reason: str  # 机器可读原因，如 "session-mode:plan"
    phase: Literal["plan", "execute"] = "plan"
    fallback: "ModelFallback | None" = None


@dataclass(frozen=True, slots=True)
class ModelFallback:
    """Fallback 审计记录（文档 §7：必须记录原/替代/分类/时间/副作用）。"""

    from_model: str
    to_model: str
    error_class: str  # provider_unavailable | context_too_long | ...
    occurred_at: str  # ISO 时间（调用方填入）
    before_side_effects: bool = True


# ── 解析 ────────────────────────────────────────────────────────────


def _model_for_profile(
    profile: Profile,
    route: RouteTable,
    available: tuple[str, ...],
) -> str:
    """档位 → 模型；若路由目标不在可用列表，回退到可用列表里档位最高的模型。"""
    candidate = route.get(profile)
    if candidate and candidate in available:
        return candidate
    # 路由目标不可用 → 按档位降序在可用列表里找（第一版不跨服务商）。
    rank = _PROFILE_RANK[profile]
    for p, r in sorted(_PROFILE_RANK.items(), key=lambda kv: -kv[1]):
        if r <= rank:
            m = route.get(p)
            if m and m in available:
                return m
    if available:
        return available[-1]
    return route.get(profile) or "deepseek-v4-flash"


def resolve_model(
    policy: ModelPolicy,
    *,
    session_mode: str,
    available_models: tuple[str, ...] | None = None,
    route: RouteTable | None = None,
    skill_requirement: Profile | None = None,
    phase: Literal["plan", "execute"] = "plan",
) -> ModelResolution:
    """解析一次（Run 开始时调用；Run 开始后固定）。

    session_mode: "ask" | "plan" | "agent"（run 视为 agent）
    skill_requirement: Skill 声明的最低档位（如 "best"）
    phase: hybrid plan-execute 的阶段；plan → best，execute → balanced
    """
    available = available_models or DEFAULT_AVAILABLE_MODELS
    table: RouteTable = {**DEFAULT_ROUTE, **(route or {})}

    # 1. named：用户指定，不做解析
    if policy.kind == "named" and policy.model_id:
        return ModelResolution(
            policy=policy_label(policy),
            effective_model=policy.model_id,
            reason="policy:named",
            phase=phase,
        )

    # 2. profile：直接查路由表
    if policy.kind == "profile" and policy.profile:
        return ModelResolution(
            policy=policy_label(policy),
            effective_model=_model_for_profile(policy.profile, table, available),
            reason=f"policy:profile:{policy.profile}",
            phase=phase,
        )

    # 3. hybrid plan-execute：plan 阶段 best，execute 阶段 balanced
    if policy.kind == "hybrid":
        prof: Profile = "best" if phase == "plan" else "balanced"
        return ModelResolution(
            policy=policy_label(policy),
            effective_model=_model_for_profile(prof, table, available),
            reason=f"policy:hybrid:phase:{phase}:{prof}",
            phase=phase,
        )

    # 4. auto：按 Session Mode + Skill Requirement
    # Skill 声明最低能力 → 优先满足（至少达到该档位）
    if skill_requirement and skill_requirement in _PROFILE_RANK:
        return ModelResolution(
            policy=policy_label(policy),
            effective_model=_model_for_profile(skill_requirement, table, available),
            reason=f"skill-requirement:{skill_requirement}",
            phase=phase,
        )
    mode = session_mode.lower()
    if mode == "ask":
        prof = "fast"
    elif mode == "plan":
        prof = "best"
    else:  # agent / run
        prof = "balanced"
    return ModelResolution(
        policy=policy_label(policy),
        effective_model=_model_for_profile(prof, table, available),
        reason=f"session-mode:{mode}:{prof}",
        phase=phase,
    )
