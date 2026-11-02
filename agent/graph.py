"""LangGraph control-flow skeleton with interrupt/resume and PostgreSQL checkpoints."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, TypedDict
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agent.contracts import AgentRequest, AgentResponse, AgentResponseStatus, TrustedAgentContext
from agent.localization import contains_cjk, is_english
from agent.routing import Intent
from agent.service import AgentService, Gateway
from agent_tools.contracts import ExecutionContext, ToolResultStatus


class AgentState(TypedDict, total=False):
    task_id: str
    session_id: str
    trace_id: str
    request_text: str
    intent: str
    plan: dict[str, Any]
    step_status: dict[str, str]
    result_reference: dict[str, Any]
    needs_approval: bool
    approval_preview: dict[str, Any]
    authorization_reference: str
    status: str
    error_code: str
    retry_count: int
    request: dict[str, Any]
    context: dict[str, Any]
    response: dict[str, Any]


def _ingest(state: AgentState) -> AgentState:
    return {"status": "INGESTED", "retry_count": state.get("retry_count", 0)}


def _route(_: AgentState) -> AgentState:
    return {"status": "ROUTED"}


def _plan(state: AgentState) -> AgentState:
    return {"status": "PLANNED", "plan": state.get("plan", {})}


def _validate(_: AgentState) -> AgentState:
    return {"status": "VALIDATED"}


def _execute(state: AgentState) -> AgentState:
    return {
        "status": "WAITING_APPROVAL" if state.get("needs_approval") else "EXECUTED",
        "step_status": state.get("step_status", {}),
    }


def _after_execute(state: AgentState) -> str:
    return "authorize" if state.get("needs_approval") else "reconcile"


def _authorize(state: AgentState) -> AgentState:
    resumed = interrupt(
        {
            "kind": "BANKING_APPROVAL",
            "task_id": state["task_id"],
            "preview": state.get("approval_preview", {}),
        }
    )
    if not isinstance(resumed, dict) or not resumed.get("authorization_reference"):
        return {"status": "FAILED", "error_code": "INVALID_RESUME"}
    return {
        "status": "AUTHORIZED",
        "authorization_reference": str(resumed["authorization_reference"]),
    }


def _reconcile(_: AgentState) -> AgentState:
    return {"status": "RECONCILED"}


def _respond(_: AgentState) -> AgentState:
    return {"status": "COMPLETED"}


def _runtime_respond(state: AgentState) -> AgentState:
    """Keep the terminal status produced by processing or commit."""

    return {"status": state.get("status", "FAILED")}


def _reconciliation_call(
    tool_name: str, arguments: dict[str, Any], result_reference: dict[str, Any]
) -> tuple[str, dict[str, Any]] | None:
    resource_id = result_reference.get("id")
    if tool_name == "commit_transfer" and resource_id:
        return "get_transfer_status", {"transfer_id": str(resource_id)}
    if tool_name in {"commit_wealth_subscription", "commit_wealth_redemption"} and resource_id:
        return "get_wealth_order_status", {"resource_id": str(resource_id)}
    if tool_name in {
        "freeze_card",
        "unfreeze_card",
        "report_card_lost",
        "update_card_limit",
    }:
        card_id = arguments.get("resource_id") or arguments.get("card_id")
        if card_id:
            return "get_card_status", {"resource_id": str(card_id)}
    return None


def _reconciliation_confirms(
    tool_name: str, arguments: dict[str, Any], payload: dict[str, Any]
) -> bool:
    if tool_name in {
        "commit_transfer",
        "commit_wealth_subscription",
        "commit_wealth_redemption",
    }:
        return str(payload.get("status", "")).upper() == "COMPLETED"
    expected_card_status = {
        "freeze_card": "FROZEN",
        "unfreeze_card": "ACTIVE",
        "report_card_lost": "LOST",
    }.get(tool_name)
    if expected_card_status is not None:
        return str(payload.get("status", "")).upper() == expected_card_status
    if tool_name == "update_card_limit":
        return str(payload.get("spending_limit")) == str(arguments.get("spending_limit"))
    return False


def build_agent_graph(checkpointer: BaseCheckpointSaver[Any] | None = None):  # type: ignore[no-untyped-def]
    graph = StateGraph(AgentState)
    graph.add_node("ingest", _ingest)
    graph.add_node("route", _route)  # type: ignore[arg-type]
    graph.add_node("plan", _plan)
    graph.add_node("validate", _validate)  # type: ignore[arg-type]
    graph.add_node("execute", _execute)
    graph.add_node("authorize", _authorize)
    graph.add_node("reconcile", _reconcile)  # type: ignore[arg-type]
    graph.add_node("respond", _respond)  # type: ignore[arg-type]
    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "route")
    graph.add_edge("route", "plan")
    graph.add_edge("plan", "validate")
    graph.add_edge("validate", "execute")
    graph.add_conditional_edges(
        "execute", _after_execute, {"authorize": "authorize", "reconcile": "reconcile"}
    )
    graph.add_edge("authorize", "reconcile")
    graph.add_edge("reconcile", "respond")
    graph.add_edge("respond", END)
    return graph.compile(checkpointer=checkpointer, name="finpilot-agent-v1")


def build_runtime_agent_graph(
    service: AgentService,
    gateway: Gateway,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> Any:
    """Build the online graph around the verified Agent service and approval resume."""

    async def process(state: AgentState) -> AgentState:
        request = AgentRequest.model_validate(state["request"])
        raw_context = state["context"]
        context = TrustedAgentContext(
            authenticated_user_id=UUID(raw_context["authenticated_user_id"]),
            session_id=UUID(raw_context["session_id"]),
            task_id=UUID(raw_context["task_id"]),
            trace_id=UUID(raw_context["trace_id"]),
            expected_intent=(
                Intent(raw_context["expected_intent"])
                if raw_context.get("expected_intent")
                else None
            ),
            expected_slots=raw_context.get("expected_slots") or {},
        )
        response = await service.handle(request, context)
        return {
            "status": response.status.value,
            "plan": response.plan.model_dump(mode="json") if response.plan else {},
            "result_reference": response.result if isinstance(response.result, dict) else {},
            "needs_approval": response.status == AgentResponseStatus.WAITING_APPROVAL,
            "response": response.model_dump(mode="json"),
        }

    def after_process(state: AgentState) -> str:
        return "authorize" if state.get("needs_approval") else "respond"

    async def commit(state: AgentState) -> AgentState:
        raw_context = state["context"]
        locale = str(state.get("request", {}).get("locale", "zh-CN"))
        english = is_english(locale)
        result_reference = state.get("result_reference", {})
        response = AgentResponse.model_validate(state["response"])
        steps = response.plan.steps if response.plan else []
        last_call = next(
            (step.tool_call for step in reversed(steps) if step.tool_call is not None), None
        )
        if last_call is None:
            failed = response.model_copy(
                update={
                    "status": AgentResponseStatus.FAILED,
                    "message": (
                        "The approval task has no tool call that can be resumed."
                        if english
                        else "待审批任务没有可恢复的工具调用。"
                    ),
                }
            )
            return {"status": "FAILED", "response": failed.model_dump(mode="json")}
        draft_tools = {
            "create_transfer_draft": ("commit_transfer", "draft_id"),
            "create_wealth_subscription_draft": (
                "commit_wealth_subscription",
                "resource_id",
            ),
            "create_wealth_redemption_draft": (
                "commit_wealth_redemption",
                "resource_id",
            ),
        }
        if last_call.tool_name in draft_tools:
            draft_id = result_reference.get("id")
            if not draft_id:
                failed = response.model_copy(
                    update={
                        "status": AgentResponseStatus.FAILED,
                        "message": (
                            "The approval draft has no trusted resource ID."
                            if english
                            else "待审批草稿缺少可信资源 ID。"
                        ),
                    }
                )
                return {"status": "FAILED", "response": failed.model_dump(mode="json")}
            tool_name, id_field = draft_tools[last_call.tool_name]
            arguments: dict[str, Any] = {id_field: str(draft_id)}
        elif last_call.tool_name in {
            "cancel_subscription",
            "update_card_limit",
            "freeze_card",
            "unfreeze_card",
            "report_card_lost",
        }:
            tool_name = last_call.tool_name
            arguments = dict(last_call.arguments)
        else:
            failed = response.model_copy(
                update={
                    "status": AgentResponseStatus.FAILED,
                    "message": (
                        "This approval task cannot be resumed yet."
                        if english
                        else "该待审批工具尚未实现统一恢复执行。"
                    ),
                }
            )
            return {"status": "FAILED", "response": failed.model_dump(mode="json")}
        execution_context = ExecutionContext(
            authenticated_user_id=UUID(raw_context["authenticated_user_id"]),
            session_id=UUID(raw_context["session_id"]),
            task_id=UUID(raw_context["task_id"]),
            trace_id=UUID(raw_context["trace_id"]),
            authorization_reference=state["authorization_reference"],
        )
        result = await gateway.execute(
            tool_name=tool_name,
            arguments=arguments,
            context=execution_context,
        )
        if result.error_code == "UNKNOWN_OUTCOME":
            reconcile_call = _reconciliation_call(tool_name, arguments, result_reference)
            if reconcile_call is not None:
                reconcile_tool, reconcile_arguments = reconcile_call
                reconciled = await gateway.execute(
                    tool_name=reconcile_tool,
                    arguments=reconcile_arguments,
                    context=execution_context,
                )
                if reconciled.status == ToolResultStatus.SUCCESS and reconciled.data is not None:
                    payload = reconciled.data.model_dump(mode="json")
                    if _reconciliation_confirms(tool_name, arguments, payload):
                        completed = response.model_copy(
                            update={
                                "status": AgentResponseStatus.COMPLETED,
                                "message": (
                                    "A Banking Core status check confirmed that the "
                                    "operation completed."
                                    if english
                                    else "已通过 Banking Core 状态查询确认操作完成。"
                                ),
                                "result": payload,
                                "error": None,
                            }
                        )
                        return {
                            "status": "COMPLETED",
                            "result_reference": payload,
                            "response": completed.model_dump(mode="json"),
                        }
            failed = response.model_copy(
                update={
                    "status": AgentResponseStatus.FAILED,
                    "message": (
                        "The Banking Core result is unknown, and a status check could not "
                        "confirm completion."
                        if english
                        else "Banking Core 返回结果未知，且状态查询未能确认操作完成。"
                    ),
                    "error": {
                        "code": "UNKNOWN_OUTCOME",
                        "message": "manual reconciliation required",
                    },
                }
            )
            return {"status": "FAILED", "response": failed.model_dump(mode="json")}
        if result.status == ToolResultStatus.SUCCESS:
            data = result.data.model_dump(mode="json") if result.data else None
            completed = response.model_copy(
                update={
                    "status": AgentResponseStatus.COMPLETED,
                    "message": (
                        "Approval was verified, and the result came from Banking Core."
                        if english
                        else "审批已验证，操作结果来自 Banking Core。"
                    ),
                    "result": data,
                    "error": None,
                }
            )
            return {
                "status": "COMPLETED",
                "result_reference": data if isinstance(data, dict) else {},
                "response": completed.model_dump(mode="json"),
            }
        failed = response.model_copy(
            update={
                "status": AgentResponseStatus.FAILED,
                "message": (
                    result.message
                    if result.message and (not english or not contains_cjk(result.message))
                    else "Banking Core did not confirm that the operation succeeded."
                    if english
                    else "Banking Core 未确认操作成功。"
                ),
            }
        )
        return {"status": "FAILED", "response": failed.model_dump(mode="json")}

    graph = StateGraph(AgentState)
    graph.add_node("ingest", _ingest)
    graph.add_node("route_plan_validate_execute", process)
    graph.add_node("authorize", _authorize)
    graph.add_node("commit", commit)
    graph.add_node("respond", _runtime_respond)
    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "route_plan_validate_execute")
    graph.add_conditional_edges(
        "route_plan_validate_execute",
        after_process,
        {"authorize": "authorize", "respond": "respond"},
    )
    graph.add_edge("authorize", "commit")
    graph.add_edge("commit", "respond")
    graph.add_edge("respond", END)
    return graph.compile(checkpointer=checkpointer, name="finpilot-runtime-v1")


@contextmanager
def postgres_agent_graph(connection_string: str) -> Iterator[Any]:
    with PostgresSaver.from_conn_string(connection_string) as saver:
        saver.setup()
        yield build_agent_graph(saver)
