"""Template baseline planner and deterministic plan verifier."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from agent.context import FactSource, SlotFact, SlotState
from agent.contracts import (
    AgentRequest,
    ArgumentSource,
    ArgumentSourceKind,
    PlanStep,
    TaskPlan,
    ToolCall,
)
from agent.routing import Intent, IntentResult
from agent_tools.registry import ToolRegistry


class PlanValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class VerificationResult:
    plan: TaskPlan
    ordered_step_ids: tuple[str, ...]


class BaselinePlanner:
    def create(
        self,
        intent: IntentResult,
        slots: SlotState,
        *,
        system_idempotency_key: str | None = None,
        request: AgentRequest | None = None,
        allowed_tools: list[dict[str, object]] | None = None,
    ) -> TaskPlan:
        del request, allowed_tools
        if slots.missing:
            raise PlanValidationError("MISSING_SLOTS", ",".join(slots.missing))
        if intent.intent == Intent.LIST_ACCOUNTS:
            return TaskPlan(
                goal="列出当前用户的银行账户",
                steps=[
                    PlanStep(
                        step_id="list_accounts",
                        purpose="读取账户列表",
                        tool_call=ToolCall(tool_name="get_accounts", arguments={}),
                    )
                ],
            )
        if intent.intent == Intent.GET_BALANCE:
            return self._single_account_plan("get_balance", "读取账户余额", slots)
        if intent.intent == Intent.GET_TRANSACTIONS:
            return self._single_account_plan("get_transactions", "读取账户流水", slots)
        if intent.intent == Intent.TRANSFER:
            if system_idempotency_key is None:
                raise PlanValidationError("MISSING_SYSTEM_IDEMPOTENCY", "task-bound key required")
            financial_names = {
                "source_account_id",
                "destination_account_id",
                "amount",
                "currency",
            }
            arguments = {
                name: fact.value for name, fact in slots.facts.items() if name in financial_names
            }
            arguments["idempotency_key"] = system_idempotency_key
            sources = {
                name: ArgumentSource(
                    kind=(
                        ArgumentSourceKind.USER_EXPLICIT
                        if fact.source == FactSource.USER_EXPLICIT
                        else ArgumentSourceKind.TOOL_VERIFIED
                    ),
                    reference=f"slot:{name}",
                )
                for name, fact in slots.facts.items()
                if name in financial_names
            }
            sources["idempotency_key"] = ArgumentSource(
                kind=ArgumentSourceKind.SYSTEM_CONSTANT, reference="trusted task id binding"
            )
            steps: list[PlanStep] = []
            if "include_balance" in slots.facts:
                steps.append(
                    PlanStep(
                        step_id="get_balance",
                        purpose="转账前读取来源账户余额",
                        tool_call=ToolCall(
                            tool_name="get_balance",
                            arguments={"account_id": arguments["source_account_id"]},
                        ),
                        argument_sources={
                            "account_id": ArgumentSource(
                                kind=ArgumentSourceKind.USER_EXPLICIT,
                                reference="slot:source_account_id",
                            )
                        },
                    )
                )
            steps.append(
                PlanStep(
                    step_id="create_transfer_draft",
                    purpose="准备转账，不提交资金",
                    depends_on=["get_balance"] if steps else [],
                    tool_call=ToolCall(tool_name="create_transfer_draft", arguments=arguments),
                    argument_sources=sources,
                )
            )
            return TaskPlan(goal="查询余额并创建转账草稿", steps=steps)
        simple_tools: dict[Intent, tuple[str, str, dict[str, str]]] = {
            Intent.ANALYZE_SPENDING: (
                "analyze_spending",
                "分析指定月份消费",
                {"year": "year", "month": "month"},
            ),
            Intent.LIST_BUDGETS: ("list_budgets", "读取预算列表", {}),
            Intent.GET_BUDGET_STATUS: (
                "get_budget_status",
                "读取预算使用状态",
                {"resource_id": "resource_id"},
            ),
            Intent.CREATE_BUDGET: (
                "create_budget",
                "创建预算",
                {
                    "category": "category",
                    "month": "month_date",
                    "limit_amount": "limit_amount",
                    "currency": "currency",
                },
            ),
            Intent.UPDATE_BUDGET: (
                "update_budget",
                "更新预算",
                {"budget_id": "budget_id", "limit_amount": "limit_amount"},
            ),
            Intent.LIST_SUBSCRIPTIONS: ("list_subscriptions", "读取订阅列表", {}),
            Intent.DETECT_RECURRING: (
                "detect_recurring_payments",
                "检测周期性付款",
                {},
            ),
            Intent.CANCEL_SUBSCRIPTION: (
                "cancel_subscription",
                "取消订阅",
                {"resource_id": "resource_id"},
            ),
            Intent.LIST_CARDS: ("list_cards", "读取银行卡列表", {}),
            Intent.GET_CARD: (
                "get_card_status",
                "读取银行卡状态",
                {"resource_id": "resource_id"},
            ),
            Intent.UPDATE_CARD_LIMIT: (
                "update_card_limit",
                "更新银行卡限额",
                {"card_id": "card_id", "spending_limit": "spending_limit"},
            ),
            Intent.FREEZE_CARD: (
                "freeze_card",
                "冻结银行卡",
                {"resource_id": "resource_id"},
            ),
            Intent.UNFREEZE_CARD: (
                "unfreeze_card",
                "解冻银行卡",
                {"resource_id": "resource_id"},
            ),
            Intent.REPORT_CARD_LOST: (
                "report_card_lost",
                "挂失银行卡",
                {"resource_id": "resource_id"},
            ),
            Intent.LIST_WEALTH_PRODUCTS: (
                "list_wealth_products",
                "读取理财产品列表",
                {},
            ),
            Intent.COMPARE_WEALTH_PRODUCTS: (
                "compare_wealth_products",
                "比较理财产品",
                {"product_ids": "product_ids"},
            ),
            Intent.GET_WEALTH_RECOMMENDATIONS: (
                "get_wealth_recommendations",
                "读取理财推荐",
                {},
            ),
            Intent.ASSESS_RISK_PROFILE: (
                "assess_risk_profile",
                "执行确定性风险测评",
                {"answers": "answers"},
            ),
            Intent.GET_HOLDINGS: ("get_holdings", "读取理财持仓", {}),
            Intent.SUBSCRIBE_WEALTH: (
                "create_wealth_subscription_draft",
                "创建理财申购草稿",
                {
                    "account_id": "account_id",
                    "product_id": "product_id",
                    "amount": "amount",
                },
            ),
            Intent.REDEEM_WEALTH: (
                "create_wealth_redemption_draft",
                "创建理财赎回草稿",
                {
                    "account_id": "account_id",
                    "product_id": "product_id",
                    "amount": "amount",
                },
            ),
            Intent.LIST_SAVINGS_POTS: ("list_savings_pots", "读取储蓄罐列表", {}),
            Intent.CREATE_SAVINGS_POT: (
                "create_savings_pot",
                "创建账户出资型储蓄目标",
                {
                    "name": "name",
                    "target_amount": "target_amount",
                    "target_date": "target_date",
                    "currency": "currency",
                },
            ),
            Intent.CONTRIBUTE_SAVINGS_POT: (
                "contribute_savings_pot",
                "从账户转入储蓄目标",
                {
                    "pot_id": "pot_id",
                    "source_account_id": "source_account_id",
                    "amount": "amount",
                },
            ),
        }
        if intent.intent in simple_tools:
            tool_name, purpose, fields = simple_tools[intent.intent]
            constants = (
                {"idempotency_key": system_idempotency_key}
                if intent.intent
                in {
                    Intent.CREATE_SAVINGS_POT,
                    Intent.CONTRIBUTE_SAVINGS_POT,
                    Intent.SUBSCRIBE_WEALTH,
                    Intent.REDEEM_WEALTH,
                }
                and system_idempotency_key is not None
                else {}
            )
            return self._fact_plan(tool_name, purpose, fields, slots, constants)
        raise PlanValidationError("UNSUPPORTED_INTENT", intent.intent.value)

    def _fact_plan(
        self,
        tool_name: str,
        purpose: str,
        fields: dict[str, str],
        slots: SlotState,
        constants: dict[str, str],
    ) -> TaskPlan:
        arguments = {argument: slots.facts[slot].value for argument, slot in fields.items()}
        arguments.update(constants)
        sources = {
            argument: self._argument_source(slots.facts[slot]) for argument, slot in fields.items()
        }
        sources.update(
            {
                name: ArgumentSource(
                    kind=ArgumentSourceKind.SYSTEM_CONSTANT,
                    reference="trusted task id binding",
                )
                for name in constants
            }
        )
        return TaskPlan(
            goal=purpose,
            steps=[
                PlanStep(
                    step_id=tool_name,
                    purpose=purpose,
                    tool_call=ToolCall(tool_name=tool_name, arguments=arguments),
                    argument_sources=sources,
                )
            ],
        )

    @staticmethod
    def _argument_source(fact: SlotFact) -> ArgumentSource:
        kinds = {
            FactSource.USER_EXPLICIT: ArgumentSourceKind.USER_EXPLICIT,
            FactSource.TOOL_VERIFIED: ArgumentSourceKind.TOOL_VERIFIED,
            FactSource.SYSTEM_CONSTANT: ArgumentSourceKind.SYSTEM_CONSTANT,
            FactSource.MODEL_INFERRED: ArgumentSourceKind.MODEL_INFERRED,
        }
        return ArgumentSource(kind=kinds[fact.source], reference=f"slot:{fact.name}")

    def _single_account_plan(self, tool_name: str, purpose: str, slots: SlotState) -> TaskPlan:
        account = slots.facts["account_id"]
        return TaskPlan(
            goal=purpose,
            steps=[
                PlanStep(
                    step_id=tool_name,
                    purpose=purpose,
                    tool_call=ToolCall(
                        tool_name=tool_name, arguments={"account_id": account.value}
                    ),
                    argument_sources={
                        "account_id": ArgumentSource(
                            kind=ArgumentSourceKind.USER_EXPLICIT,
                            reference="slot:account_id",
                        )
                    },
                )
            ],
        )


class PlanVerifier:
    def __init__(self, registry: ToolRegistry, *, max_steps: int = 20, max_depth: int = 10) -> None:
        self._registry = registry
        self._max_steps = max_steps
        self._max_depth = max_depth

    def verify(self, plan: TaskPlan, allowed_actions: set[str]) -> VerificationResult:
        if len(plan.steps) > self._max_steps:
            raise PlanValidationError("PLAN_TOO_LARGE", "plan exceeds step limit")
        steps = {step.step_id: step for step in plan.steps}
        if len(steps) != len(plan.steps):
            raise PlanValidationError("DUPLICATE_STEP", "step ids must be unique")
        for step in plan.steps:
            if step.step_id in step.depends_on:
                raise PlanValidationError("PLAN_CYCLE", "step cannot depend on itself")
            if missing := set(step.depends_on).difference(steps):
                raise PlanValidationError("MISSING_DEPENDENCY", f"missing dependencies: {missing}")
            if step.tool_call is None:
                continue
            tool = self._registry.get(step.tool_call.tool_name)
            if tool is None:
                raise PlanValidationError("UNKNOWN_TOOL", step.tool_call.tool_name)
            if tool.action not in allowed_actions:
                raise PlanValidationError("TOOL_NOT_ALLOWED", tool.action)
            argument_names = set(step.tool_call.arguments)
            if argument_names != set(step.argument_sources):
                raise PlanValidationError(
                    "ARGUMENT_SOURCE_MISMATCH", "every argument requires exact provenance"
                )
            if any(
                source.kind == ArgumentSourceKind.MODEL_INFERRED
                for source in step.argument_sources.values()
            ):
                raise PlanValidationError(
                    "INFERRED_ARGUMENT", "model-inferred financial arguments are not executable"
                )
            try:
                tool.input_model.model_validate(step.tool_call.arguments)
            except ValidationError as exc:
                raise PlanValidationError("INVALID_TOOL_ARGUMENTS", str(exc)) from None
        ordered = self._topological_order(steps)
        return VerificationResult(plan=plan, ordered_step_ids=tuple(ordered))

    def _topological_order(self, steps: dict[str, PlanStep]) -> list[str]:
        visiting: set[str] = set()
        visited: set[str] = set()
        ordered: list[str] = []

        def visit(step_id: str, depth: int) -> None:
            if depth > self._max_depth:
                raise PlanValidationError("PLAN_TOO_DEEP", "dependency depth exceeded")
            if step_id in visiting:
                raise PlanValidationError("PLAN_CYCLE", "dependency cycle detected")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in steps[step_id].depends_on:
                visit(dependency, depth + 1)
            visiting.remove(step_id)
            visited.add(step_id)
            ordered.append(step_id)

        for step_id in steps:
            visit(step_id, 1)
        return ordered
