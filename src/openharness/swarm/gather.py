"""Deterministic recursive gather protocol helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import shlex
from typing import Any

from openharness.swarm.event_store import EventStore
from openharness.swarm.events import SwarmEvent, new_swarm_event
from openharness.swarm.gather_spec import GatherSpec


@dataclass(frozen=True)
class GatherNodeResult:
    """Structured recursive gather result for one subtree root."""

    agent_id: str
    status: str
    self_result: Any
    children: list["GatherNodeResult"] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    summary_text: str | None = None

    def to_payload(self) -> dict[str, Any]:
        """Serialize this result into an event payload fragment."""

        return {
            "agent_id": self.agent_id,
            "status": self.status,
            "self_result": self.self_result,
            "children": [child.to_payload() for child in self.children],
            "errors": list(self.errors),
            "summary_text": self.summary_text,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "GatherNodeResult":
        """Deserialize one result previously stored in an event payload."""

        raw_children = payload.get("children")
        children: list[GatherNodeResult] = []
        if isinstance(raw_children, list):
            for child in raw_children:
                if isinstance(child, dict):
                    children.append(cls.from_payload(child))
        raw_errors = payload.get("errors")
        errors = [str(item) for item in raw_errors] if isinstance(raw_errors, list) else []
        return cls(
            agent_id=str(payload.get("agent_id", "")),
            status=str(payload.get("status", "ok")),
            self_result=payload.get("self_result"),
            children=children,
            errors=errors,
            summary_text=(
                str(payload.get("summary_text"))
                if payload.get("summary_text") not in {None, ""}
                else None
            ),
        )


@dataclass(frozen=True)
class GatherSynthesisResult:
    """LLM- or helper-produced payload for one node before protocol assembly."""

    self_result: Any
    summary_text: str | None = None


def emit_gather_requested(
    *,
    event_store: EventStore,
    gather_id: str,
    agent_id: str,
    root_agent_id: str,
    parent_agent_id: str | None,
    session_id: str | None,
    target_agent_ids: list[str],
    request: str,
    spec_name: str,
) -> None:
    """Emit the start of one gather turn."""

    event_store.append(
        new_swarm_event(
            "gather_requested",
            agent_id=agent_id,
            root_agent_id=root_agent_id,
            parent_agent_id=parent_agent_id,
            session_id=session_id,
            correlation_id=gather_id,
            payload={
                "target_agent_ids": list(target_agent_ids),
                "request": request,
                "spec_name": spec_name,
            },
        )
    )


def emit_gather_result(
    *,
    event_store: EventStore,
    gather_id: str,
    agent_id: str,
    root_agent_id: str,
    parent_agent_id: str | None,
    session_id: str | None,
    result: GatherNodeResult,
) -> None:
    """Emit one successful gather result for a subtree root."""

    event_store.append(
        new_swarm_event(
            "gather_result_reported",
            agent_id=agent_id,
            root_agent_id=root_agent_id,
            parent_agent_id=parent_agent_id,
            session_id=session_id,
            correlation_id=gather_id,
            payload={"result": result.to_payload()},
        )
    )


def emit_gather_failed(
    *,
    event_store: EventStore,
    gather_id: str,
    agent_id: str,
    root_agent_id: str,
    parent_agent_id: str | None,
    session_id: str | None,
    error: str,
) -> None:
    """Emit one failed gather result for a subtree root."""

    event_store.append(
        new_swarm_event(
            "gather_failed",
            agent_id=agent_id,
            root_agent_id=root_agent_id,
            parent_agent_id=parent_agent_id,
            session_id=session_id,
            correlation_id=gather_id,
            payload={"error": error},
        )
    )


async def wait_for_child_gather_results(
    *,
    event_store: EventStore,
    gather_id: str,
    child_agent_ids: list[str],
    timeout_seconds: float,
    poll_interval: float = 0.05,
) -> dict[str, GatherNodeResult]:
    """Wait until all expected child gather results arrive or timeout expires."""

    expected = list(child_agent_ids)
    seen: dict[str, GatherNodeResult] = {}
    deadline = asyncio.get_running_loop().time() + max(timeout_seconds, 0)

    while True:
        _update_seen_results(
            events=event_store.all_events(),
            gather_id=gather_id,
            expected_child_ids=expected,
            seen=seen,
        )
        if all(agent_id in seen for agent_id in expected):
            break
        now = asyncio.get_running_loop().time()
        if now >= deadline:
            break
        await asyncio.sleep(min(poll_interval, max(deadline - now, 0)))

    ordered: dict[str, GatherNodeResult] = {}
    for agent_id in expected:
        ordered[agent_id] = seen.get(
            agent_id,
            GatherNodeResult(agent_id=agent_id, status="timeout", self_result=None, children=[]),
        )
    return ordered


def assemble_gather_result(
    *,
    agent_id: str,
    self_result: Any,
    child_results: dict[str, GatherNodeResult],
    child_agent_ids: list[str],
    ordering: str,
    errors: list[str] | None = None,
    summary_text: str | None = None,
) -> GatherNodeResult:
    """Build one structured tree result from the current node plus child results."""

    ordered_child_ids = _ordered_child_ids(child_results.keys(), child_agent_ids, ordering=ordering)
    children = [child_results[child_id] for child_id in ordered_child_ids if child_id in child_results]
    derived_errors = list(errors or [])
    for child in children:
        if child.status in {"timeout", "error", "failed"}:
            derived_errors.append(f"{child.agent_id}: {child.status}")
        derived_errors.extend(child.errors)
    status = "partial" if derived_errors else "ok"
    return GatherNodeResult(
        agent_id=agent_id,
        status=status,
        self_result=self_result,
        children=children,
        errors=derived_errors,
        summary_text=summary_text,
    )


async def run_recursive_gather(
    *,
    event_store: EventStore,
    gather_id: str,
    current_agent_id: str,
    root_agent_id: str,
    parent_agent_id: str | None,
    session_id: str | None,
    spec: GatherSpec,
    request: str,
    child_agent_ids: list[str],
    send_to_agent,
    synthesize_node,
    remember_for_model: bool = False,
) -> GatherNodeResult:
    """Execute one recursive gather step for the current subtree root."""

    emit_gather_requested(
        event_store=event_store,
        gather_id=gather_id,
        agent_id=current_agent_id,
        root_agent_id=root_agent_id,
        parent_agent_id=parent_agent_id,
        session_id=session_id,
        target_agent_ids=child_agent_ids,
        request=request,
        spec_name=spec.name,
    )
    for child_agent_id in child_agent_ids:
        await send_to_agent(
            child_agent_id,
            _build_recursive_gather_command(
                gather_id=gather_id,
                spec_name=spec.name,
                request=request,
                origin_agent_id=current_agent_id,
                remember_for_model=remember_for_model,
            ),
        )

    child_results = await wait_for_child_gather_results(
        event_store=event_store,
        gather_id=gather_id,
        child_agent_ids=child_agent_ids,
        timeout_seconds=spec.timeout_seconds,
    )
    try:
        synthesis = _coerce_synthesis_result(
            await synthesize_node(child_results=child_results)
        )
    except Exception as exc:
        emit_gather_failed(
            event_store=event_store,
            gather_id=gather_id,
            agent_id=current_agent_id,
            root_agent_id=root_agent_id,
            parent_agent_id=parent_agent_id,
            session_id=session_id,
            error=str(exc),
        )
        raise

    result = assemble_gather_result(
        agent_id=current_agent_id,
        self_result=synthesis.self_result,
        child_results=child_results,
        child_agent_ids=child_agent_ids,
        ordering=spec.ordering,
        summary_text=synthesis.summary_text,
    )
    emit_gather_result(
        event_store=event_store,
        gather_id=gather_id,
        agent_id=current_agent_id,
        root_agent_id=root_agent_id,
        parent_agent_id=parent_agent_id,
        session_id=session_id,
        result=result,
    )
    return result


def _update_seen_results(
    *,
    events: tuple[SwarmEvent, ...],
    gather_id: str,
    expected_child_ids: list[str],
    seen: dict[str, GatherNodeResult],
) -> None:
    allowed = set(expected_child_ids)
    for event in events:
        if event.correlation_id != gather_id or event.agent_id not in allowed:
            continue
        if event.event_type == "gather_result_reported":
            payload = event.payload.get("result")
            if isinstance(payload, dict):
                seen[event.agent_id] = GatherNodeResult.from_payload(payload)
        elif event.event_type == "gather_failed":
            seen[event.agent_id] = GatherNodeResult(
                agent_id=event.agent_id,
                status="error",
                self_result=None,
                children=[],
                errors=[str(event.payload.get("error", "unknown gather failure"))],
            )


def _ordered_child_ids(
    child_ids: Any,
    topology_order: list[str],
    *,
    ordering: str,
) -> list[str]:
    ids = [str(item) for item in child_ids]
    if ordering == "name":
        return sorted(ids)
    by_id = set(ids)
    ordered = [agent_id for agent_id in topology_order if agent_id in by_id]
    missing = sorted(agent_id for agent_id in ids if agent_id not in ordered)
    return ordered + missing


def _coerce_synthesis_result(raw: Any) -> GatherSynthesisResult:
    """Normalize callback output into a gather synthesis result."""

    if isinstance(raw, GatherSynthesisResult):
        return raw
    if isinstance(raw, dict) and ("self_result" in raw or "summary_text" in raw):
        return GatherSynthesisResult(
            self_result=raw.get("self_result"),
            summary_text=(
                str(raw.get("summary_text"))
                if raw.get("summary_text") not in {None, ""}
                else None
            ),
        )
    return GatherSynthesisResult(self_result=raw, summary_text=None)


def _build_recursive_gather_command(
    *,
    gather_id: str,
    spec_name: str,
    request: str,
    origin_agent_id: str,
    remember_for_model: bool = False,
) -> str:
    base = (
        "/gather "
        f"--gather-id {shlex.quote(gather_id)} "
        f"--spec {shlex.quote(spec_name)} "
        f"--origin-agent-id {shlex.quote(origin_agent_id)} "
        f"--request {shlex.quote(request)}"
    )
    if remember_for_model:
        return f"{base} !!"
    return base
