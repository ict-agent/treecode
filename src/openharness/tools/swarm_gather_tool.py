"""Deterministic recursive gather tool."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Awaitable, Callable
import uuid

from pydantic import BaseModel, ConfigDict, Field

from openharness.engine.stream_events import AssistantTurnComplete
from openharness.swarm.event_store import get_event_store
from openharness.swarm.gather import (
    GatherSynthesisResult,
    GatherNodeResult,
    run_recursive_gather,
    wait_for_child_gather_results,
)
from openharness.swarm.session_scope import (
    filter_agent_ids_for_leader_session,
    filter_live_nodes_for_leader_session,
)
from openharness.swarm.gather_spec import GatherSpec, load_gather_spec
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolRegistry, ToolResult
from openharness.tools.send_message_tool import SendMessageTool, SendMessageToolInput
from openharness.tools.swarm_context_tool import _current_session_tree, resolve_swarm_identity

if TYPE_CHECKING:
    from openharness.engine.query_engine import QueryEngine
from openharness.swarm.topology_reader import build_projection, live_runtime_state, materialize_topology

LocalGatherRunner = Callable[..., Awaitable[GatherSynthesisResult | dict[str, Any] | Any]]
VisibleModelTurnRunner = Callable[[str], Awaitable[str]]


class SwarmGatherToolInput(BaseModel):
    """Arguments for one recursive gather request."""

    model_config = ConfigDict(extra="forbid")

    request: str = Field(description="What to gather from the subtree.")
    spec_name: str | None = Field(
        default=None,
        description="Optional gather spec name from .openharness/gather/*.md. Defaults to a generic inline gather spec.",
    )
    target_agent_id: str | None = Field(
        default=None,
        description="Optional subtree root to ask. Defaults to the current swarm agent.",
    )
    gather_id: str | None = Field(
        default=None,
        description="Internal correlation id for recursive gather fan-out/fan-in.",
    )
    origin_agent_id: str | None = Field(
        default=None,
        description="Internal initiator id for recursive gather fan-out/fan-in.",
    )


class SwarmGatherTool(BaseTool):
    """Recursively gather structured results from a swarm subtree."""

    name = "swarm_gather"
    description = (
        "Run a deterministic recursive gather across the current swarm subtree. "
        "Use this or /gather when you want one node to ask its descendants for structured results and "
        "roll them back up into a tree."
    )
    input_model = SwarmGatherToolInput

    def is_read_only(self, arguments: SwarmGatherToolInput) -> bool:
        del arguments
        return False

    async def execute(self, arguments: SwarmGatherToolInput, context: ToolExecutionContext) -> ToolResult:
        resolved = resolve_swarm_identity(context)
        if resolved is None:
            return ToolResult(output="No active swarm context for recursive gather.", is_error=True)
        current_agent_id, parent_agent_id, root_agent_id, _lineage_path = resolved
        spec = _resolve_gather_spec(arguments.spec_name, context.cwd)
        gather_id = arguments.gather_id or str(uuid.uuid4())
        target_agent_id = _resolve_live_target_agent_id(
            context,
            requested_target_id=arguments.target_agent_id or current_agent_id,
        )
        session_id = str(context.metadata.get("session_id") or current_agent_id)
        event_store = get_event_store()

        async def send_to_agent(agent_id: str, command: str) -> None:
            result = await SendMessageTool().execute(
                SendMessageToolInput(task_id=agent_id, message=command),
                context,
            )
            if result.is_error:
                raise ValueError(result.output)

        if target_agent_id != current_agent_id:
            await send_to_agent(
                target_agent_id,
                _build_delegated_gather_command(
                    request=arguments.request,
                    spec_name=spec.name,
                    gather_id=gather_id,
                    origin_agent_id=arguments.origin_agent_id or current_agent_id,
                ),
            )
            delegated = await wait_for_child_gather_results(
                event_store=event_store,
                gather_id=gather_id,
                child_agent_ids=[target_agent_id],
                timeout_seconds=spec.timeout_seconds,
            )
            result = delegated[target_agent_id]
            return ToolResult(
                output=_format_gather_output(
                    result=result,
                    gather_id=gather_id,
                    session_id=session_id,
                    spec=spec,
                ),
                metadata={
                    "gather_id": gather_id,
                    "spec_name": spec.name,
                    "result": result.to_payload(),
                },
            )

        child_agent_ids = resolve_live_child_agent_ids(context, current_agent_id)
        local_runner = context.metadata.get("run_gather_local")

        async def synthesize_node(*, child_results) -> GatherSynthesisResult | dict[str, Any] | Any:
            if callable(local_runner):
                return await local_runner(
                    request=arguments.request,
                    spec=spec,
                    agent_id=current_agent_id,
                    parent_agent_id=parent_agent_id,
                    root_agent_id=root_agent_id,
                    child_agent_ids=child_agent_ids,
                    child_results=child_results,
                )
            return _default_local_synthesis_output(
                spec=spec,
                agent_id=current_agent_id,
                child_agent_ids=child_agent_ids,
                child_results=child_results,
            )

        result = await run_recursive_gather(
            event_store=event_store,
            gather_id=gather_id,
            current_agent_id=current_agent_id,
            root_agent_id=root_agent_id,
            parent_agent_id=parent_agent_id,
            session_id=session_id,
            spec=spec,
            request=arguments.request,
            child_agent_ids=child_agent_ids,
            send_to_agent=send_to_agent,
            synthesize_node=synthesize_node,
        )
        return ToolResult(
            output=_format_gather_output(
                result=result,
                gather_id=gather_id,
                session_id=session_id,
                spec=spec,
            ),
            metadata={
                "gather_id": gather_id,
                "spec_name": spec.name,
                "result": result.to_payload(),
            },
        )


def _leader_session_from_gather_context(context: ToolExecutionContext) -> str | None:
    md = context.metadata or {}
    raw = md.get("swarm_leader_session_id")
    if raw is not None and str(raw).strip():
        return str(raw).strip()
    return None


def resolve_live_child_agent_ids(context: ToolExecutionContext, current_agent_id: str) -> list[str]:
    """Return current live direct children using session-scoped swarm rules."""

    events = get_event_store().all_events()
    leader = _leader_session_from_gather_context(context)
    topology = materialize_topology(
        build_projection(events),
        view="live",
        runtime_state_provider=live_runtime_state,
    )
    summary = topology.lookup(current_agent_id)
    if summary is not None:
        return filter_agent_ids_for_leader_session(
            list(summary["children"]),
            leader,
            events,
        )
    if current_agent_id == "main@default":
        current_tree = _current_session_tree(
            events=events,
            base_tree=topology.tree,
            runtime_state=topology.runtime_state,
            current_agent_id=current_agent_id,
            current_parent_agent_id=None,
            current_root_agent_id=current_agent_id,
            current_lineage_path=(current_agent_id,),
            current_session_id=str(context.metadata.get("session_id") or current_agent_id),
        )
        node = current_tree["nodes"].get(current_agent_id, {})
        return filter_agent_ids_for_leader_session(
            list(node.get("children", [])),
            leader,
            events,
        )
    return []


def _resolve_live_target_agent_id(context: ToolExecutionContext, requested_target_id: str) -> str:
    """Resolve an explicit gather target to the unique matching live agent when possible."""

    events = get_event_store().all_events()
    topology = materialize_topology(
        build_projection(events),
        view="live",
        runtime_state_provider=live_runtime_state,
    )
    live_nodes = topology.tree.get("nodes", {})
    leader = _leader_session_from_gather_context(context)
    if leader:
        live_nodes = filter_live_nodes_for_leader_session(live_nodes, leader, events)
    if requested_target_id in live_nodes:
        return requested_target_id
    candidate_ids = _candidate_live_target_agent_ids(live_nodes, requested_target_id)
    if len(candidate_ids) == 1:
        return candidate_ids[0]
    return requested_target_id


def _candidate_live_target_agent_ids(live_nodes: dict[str, object], requested_target_id: str) -> list[str]:
    """Return live gather target candidates for a requested agent id."""

    agent_ids = [str(agent_id) for agent_id in live_nodes.keys()]
    if requested_target_id in agent_ids:
        return [requested_target_id]
    if "@" in requested_target_id:
        name_part, team_part = requested_target_id.split("@", 1)
        exact_id = f"{name_part}@{team_part}"
        if exact_id in agent_ids:
            return [exact_id]
        pattern = re.compile(rf"^{re.escape(name_part)}-\d+@{re.escape(team_part)}$")
        return sorted(agent_id for agent_id in agent_ids if pattern.match(agent_id))
    pattern = re.compile(rf"^{re.escape(requested_target_id)}(?:-\d+)?@")
    return sorted(agent_id for agent_id in agent_ids if pattern.match(agent_id))


def build_engine_gather_local_runner(engine: QueryEngine) -> LocalGatherRunner:
    """Return the narrow callback exposed to the gather tool in prompt/tool mode."""

    async def _runner(
        *,
        request: str,
        spec: GatherSpec,
        agent_id: str,
        parent_agent_id: str | None,
        root_agent_id: str,
        child_agent_ids: list[str],
        child_results: dict[str, GatherNodeResult],
    ) -> GatherSynthesisResult:
        from openharness.engine.query_engine import QueryEngine as QueryEngineCls

        query_context = engine.to_query_context()
        ephemeral = QueryEngineCls(
            api_client=query_context.api_client,
            tool_registry=ToolRegistry(),
            permission_checker=query_context.permission_checker,
            cwd=query_context.cwd,
            model=query_context.model,
            system_prompt=query_context.system_prompt,
            max_tokens=query_context.max_tokens,
            max_turns=4,
            permission_prompt=query_context.permission_prompt,
            ask_user_prompt=query_context.ask_user_prompt,
            hook_executor=query_context.hook_executor,
            tool_metadata=query_context.tool_metadata,
        )
        ephemeral.load_messages(engine.messages)
        prompt = _build_local_gather_prompt(
            request=request,
            spec=spec,
            agent_id=agent_id,
            parent_agent_id=parent_agent_id,
            root_agent_id=root_agent_id,
            child_agent_ids=child_agent_ids,
            child_results=child_results,
        )
        final_text = ""
        async for event in ephemeral.submit_message(prompt):
            if isinstance(event, AssistantTurnComplete):
                final_text = event.message.text.strip()
        return _parse_local_gather_json(final_text)

    return _runner


def build_contextual_gather_local_runner(run_model_turn: VisibleModelTurnRunner) -> LocalGatherRunner:
    """Return a gather synthesis runner that uses the current session's live engine turn."""

    async def _runner(
        *,
        request: str,
        spec: GatherSpec,
        agent_id: str,
        parent_agent_id: str | None,
        root_agent_id: str,
        child_agent_ids: list[str],
        child_results: dict[str, GatherNodeResult],
    ) -> GatherSynthesisResult:
        prompt = _build_local_gather_prompt(
            request=request,
            spec=spec,
            agent_id=agent_id,
            parent_agent_id=parent_agent_id,
            root_agent_id=root_agent_id,
            child_agent_ids=child_agent_ids,
            child_results=child_results,
        )
        return _parse_local_gather_json(await run_model_turn(prompt))

    return _runner


def _resolve_gather_spec(spec_name: str | None, cwd: Path) -> GatherSpec:
    if spec_name:
        loaded = load_gather_spec(spec_name, cwd)
        if loaded is None:
            raise ValueError(f"Unknown gather spec: {spec_name}")
        return loaded
    return GatherSpec(
        name="generic_gather",
        description="Ad-hoc recursive gather request.",
        version=1,
        allow_none=True,
        timeout_seconds=30.0,
        ordering="topology",
        return_mode="tree",
        instructions="Return a JSON self_result for this node, or null when there is no local contribution.",
        path=Path("<inline>"),
    )


def _default_local_synthesis_output(
    *,
    spec: GatherSpec,
    agent_id: str,
    child_agent_ids: list[str],
    child_results: dict[str, GatherNodeResult],
) -> GatherSynthesisResult:
    del child_results
    self_result = {
        "agent_id": agent_id,
        "role": "branch" if child_agent_ids else "leaf",
        "ready": True,
        "status_note": (
            f"managing {len(child_agent_ids)} live child agent(s)"
            if child_agent_ids
            else "leaf node ready"
        ),
        "spec_name": spec.name,
    }
    summary_text = (
        f"{agent_id} [branch, ready]\n"
        + "\n".join(f"- {child_id}" for child_id in child_agent_ids)
        if child_agent_ids
        else f"{agent_id} [leaf, ready]"
    )
    return GatherSynthesisResult(self_result=self_result, summary_text=summary_text)


def _build_local_gather_prompt(
    *,
    request: str,
    spec: GatherSpec,
    agent_id: str,
    parent_agent_id: str | None,
    root_agent_id: str,
    child_agent_ids: list[str],
    child_results: dict[str, GatherNodeResult],
) -> str:
    child_results_preview = json.dumps(
        {agent_id: result.to_payload() for agent_id, result in child_results.items()},
        ensure_ascii=False,
        indent=2,
    )
    return (
        "You are processing a recursive gather turn inside your current session.\n"
        "You have already received any direct child gather results for this subtree.\n"
        "Synthesize the result you will pass upward.\n"
        "Do not recurse again. Do not call tools. Return a short human-readable topology-like summary first, "
        "then a fenced JSON block.\n"
        "The JSON block must have exactly these keys: self_result, summary_text.\n\n"
        f"Gather request: {request}\n"
        f"Gather spec: {spec.name}\n"
        f"Spec description: {spec.description}\n"
        f"Spec instructions:\n{spec.instructions}\n\n"
        f"Current agent id: {agent_id}\n"
        f"Parent agent id: {parent_agent_id or '(root)'}\n"
        f"Root agent id: {root_agent_id}\n"
        f"Current live child agent ids: {child_agent_ids}\n"
        f"Collected child results:\n{child_results_preview}\n\n"
        "Your JSON must look like:\n"
        '```json\n{"self_result": {...}, "summary_text": "..."}\n```\n'
    )


def _parse_local_gather_json(raw: str) -> GatherSynthesisResult:
    text = raw.strip()
    if not text:
        return GatherSynthesisResult(self_result=None, summary_text=None)
    if text == "null":
        return GatherSynthesisResult(self_result=None, summary_text=None)
    if "```" in text:
        segments = text.split("```")
        for segment in reversed(segments):
            candidate = segment.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            if not candidate:
                continue
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return GatherSynthesisResult(
                        self_result=parsed.get("self_result"),
                        summary_text=(
                            str(parsed.get("summary_text"))
                            if parsed.get("summary_text") not in {None, ""}
                            else None
                        ),
                    )
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
    parsed = json.loads(text)
    if isinstance(parsed, dict):
        return GatherSynthesisResult(
            self_result=parsed.get("self_result"),
            summary_text=(
                str(parsed.get("summary_text"))
                if parsed.get("summary_text") not in {None, ""}
                else None
            ),
        )
    return GatherSynthesisResult(self_result=parsed, summary_text=None)


def _build_delegated_gather_command(
    *,
    request: str,
    spec_name: str,
    gather_id: str,
    origin_agent_id: str,
) -> str:
    import shlex

    return (
        "/gather "
        f"--gather-id {shlex.quote(gather_id)} "
        f"--spec {shlex.quote(spec_name)} "
        f"--origin-agent-id {shlex.quote(origin_agent_id)} "
        f"--request {shlex.quote(request)}"
    )


def _render_gather_result(result: GatherNodeResult) -> str:
    if result.summary_text:
        return result.summary_text
    child_count = len(result.children)
    return (
        f"Gather result for {result.agent_id}: status={result.status}, "
        f"children={child_count}, self_result={'present' if result.self_result is not None else 'null'}."
    )


def _format_gather_output(
    *,
    result: GatherNodeResult,
    gather_id: str,
    session_id: str,
    spec: GatherSpec,
) -> str:
    header = (
        f"gather_id: {gather_id}\n"
        f"session_id: {session_id}\n"
        f"loaded_spec: {spec.path}\n"
        f"timeout_seconds: {spec.timeout_seconds}"
    )
    body = _render_gather_result(result)
    return f"{header}\n\n{body}"
