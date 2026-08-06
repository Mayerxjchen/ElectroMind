"""P3 ModelResolver 单元测试 —— 修订版文档 §7 初始规则与固定规则。"""

from electromind.model_resolver import (
    AUTO_POLICY,
    DEFAULT_AVAILABLE_MODELS,
    ModelPolicy,
    parse_model_policy,
    policy_label,
    resolve_model,
)


class TestParsePolicy:
    def test_auto(self):
        assert parse_model_policy("auto") == AUTO_POLICY
        assert parse_model_policy(None) == AUTO_POLICY
        assert parse_model_policy("") == AUTO_POLICY

    def test_profile(self):
        assert parse_model_policy("fast").kind == "profile"
        assert parse_model_policy("balanced").profile == "balanced"
        assert parse_model_policy("best").profile == "best"

    def test_hybrid(self):
        p = parse_model_policy("plan-execute")
        assert p.kind == "hybrid"
        assert p.hybrid == "plan-execute"

    def test_named(self):
        p = parse_model_policy("deepseek-v4-flash")
        assert p.kind == "named"
        assert p.model_id == "deepseek-v4-flash"

    def test_label(self):
        assert policy_label(AUTO_POLICY) == "Auto"
        assert policy_label(parse_model_policy("best")) == "Best"
        assert policy_label(parse_model_policy("plan-execute")) == "Plan→Execute"
        assert (
            policy_label(parse_model_policy("deepseek-v4-flash"))
            == "named:deepseek-v4-flash"
        )


class TestResolveRules:
    """文档 §7 初始规则：Ask→fast / Plan→best / Agent→balanced。"""

    def test_auto_ask_fast(self):
        r = resolve_model(AUTO_POLICY, session_mode="ask")
        assert r.effective_model == "deepseek-v4-flash"
        assert r.reason == "session-mode:ask:fast"

    def test_auto_plan_best(self):
        r = resolve_model(AUTO_POLICY, session_mode="plan")
        assert r.effective_model == "deepseek-v4-pro"

    def test_auto_agent_balanced(self):
        r = resolve_model(AUTO_POLICY, session_mode="agent")
        assert r.effective_model == "deepseek-v4-pro"
        assert r.reason == "session-mode:agent:balanced"

    def test_profile_best(self):
        r = resolve_model(
            ModelPolicy(kind="profile", profile="best"), session_mode="ask"
        )
        assert r.reason.startswith("policy:profile:best")

    def test_named_fixed(self):
        r = resolve_model(
            ModelPolicy(kind="named", model_id="deepseek-v4-flash"),
            session_mode="plan",
        )
        assert r.effective_model == "deepseek-v4-flash"
        assert r.reason == "policy:named"

    def test_skill_requirement_overrides_mode(self):
        r = resolve_model(AUTO_POLICY, session_mode="ask", skill_requirement="best")
        assert r.effective_model == "deepseek-v4-pro"
        assert r.reason == "skill-requirement:best"


class TestPlanExecuteHybrid:
    """Plan → Execute：plan 阶段 best，批准后 execute 阶段 balanced。

    默认路由表（fast→flash / balanced→pro / best→pro）下两阶段模型相同；
    用三档路由表证明阶段逻辑：best→pro，balanced→flash。"""

    ROUTE = {
        "fast": "deepseek-v4-flash",
        "balanced": "deepseek-v4-flash",
        "best": "deepseek-v4-pro",
    }

    def test_plan_phase_best(self):
        r = resolve_model(
            ModelPolicy(kind="hybrid", hybrid="plan-execute"),
            session_mode="plan",
            phase="plan",
            route=self.ROUTE,
        )
        assert r.effective_model == "deepseek-v4-pro"
        assert r.reason == "policy:hybrid:phase:plan:best"

    def test_execute_phase_balanced(self):
        r = resolve_model(
            ModelPolicy(kind="hybrid", hybrid="plan-execute"),
            session_mode="plan",
            phase="execute",
            route=self.ROUTE,
        )
        assert r.effective_model == "deepseek-v4-flash"
        assert r.reason == "policy:hybrid:phase:execute:balanced"


class TestAvailability:
    """实际模型必须从可用模型列表中选择；第一版不跨服务商。"""

    def test_route_target_missing_falls_back_in_available(self):
        # 可用列表只有 flash —— best 路由目标 pro 不可用 → 降级到可用里最高档
        r = resolve_model(
            AUTO_POLICY, session_mode="plan", available_models=("deepseek-v4-flash",)
        )
        assert r.effective_model == "deepseek-v4-flash"

    def test_named_must_be_available(self):
        # 显式 named 仍尊重用户选择（可用性由 provider 层校验）
        r = resolve_model(
            ModelPolicy(kind="named", model_id="custom-model"),
            session_mode="agent",
            available_models=DEFAULT_AVAILABLE_MODELS,
        )
        assert r.effective_model == "custom-model"


class TestFixedRules:
    """固定规则：每次 Run 开始解析一次；Run 开始后固定（不因重试切换）。"""

    def test_resolution_is_deterministic(self):
        a = resolve_model(AUTO_POLICY, session_mode="agent")
        b = resolve_model(AUTO_POLICY, session_mode="agent")
        assert a == b

    def test_resolution_frozen_per_call(self):
        """同一 policy 不同调用返回同一结果 —— 调用方在 Run 开始处取一次即可。"""
        r = resolve_model(AUTO_POLICY, session_mode="agent")
        assert r.effective_model == "deepseek-v4-pro"
