"""In-process teammate execution backend.

Runs teammate agents as asyncio Tasks inside the current Python process,
using :mod:`contextvars` for per-teammate context isolation (the Python
equivalent of Node's AsyncLocalStorage).

Architecture summary
--------------------
* :class:`TeammateAbortController` – dual-signal abort controller providing
  both graceful-cancel and force-kill semantics.
* :class:`TeammateContext` – dataclass holding identity + abort controller +
  runtime stats (tool_use_count, total_tokens, status).
* :func:`get_teammate_context` / :func:`set_teammate_context` – ContextVar
  accessors so any code running inside a teammate task can discover its own
  identity without explicit argument threading.
* :func:`start_in_process_teammate` – the actual coroutine that sets up
  context, drives the query engine, and cleans up on exit.
* :class:`InProcessBackend` – implements
  :class:`~openharness.swarm.types.TeammateExecutor` and manages the dict of
  live asyncio Tasks.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal

from openharness.swarm.mailbox import (
    TeammateMailbox,
    create_idle_notification,
)
from openharness.swarm.event_store import get_event_store
from openharness.swarm.events import new_swarm_event
from openharness.swarm.context_registry import AgentContextSnapshot, get_context_registry
from openharness.swarm.types import (
    BackendType,
    SpawnResult,
    TeammateMessage,
    TeammateSpawnConfig,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Abort controller
# ---------------------------------------------------------------------------


class TeammateAbortController:
    """Dual-signal abort controller for in-process teammates.

    Provides both *graceful* cancellation (set ``cancel_event``; the agent
    finishes its current tool use and then exits) and *force* kill (set
    ``force_cancel``; the asyncio Task is immediately cancelled).

    Mirrors the TypeScript ``AbortController`` / linked-controller pattern used
    in ``spawnInProcess.ts`` and ``InProcessBackend.ts``.
    """

    def __init__(self) -> None:
        self.cancel_event: asyncio.Event = asyncio.Event()
        """Set to request graceful cancellation of the agent loop."""

        self.force_cancel: asyncio.Event = asyncio.Event()
        """Set to request immediate (forced) termination."""

        self._reason: str | None = None

    @property
    def is_cancelled(self) -> bool:
        """Return True if either cancellation signal has been set."""
        return self.cancel_event.is_set() or self.force_cancel.is_set()

    def request_cancel(self, reason: str | None = None, *, force: bool = False) -> None:
        """Request cancellation of the teammate.

        Args:
            reason: Human-readable reason for the cancellation (for logging).
            force: When True, set ``force_cancel`` for immediate termination.
                   When False, set ``cancel_event`` for graceful shutdown.
        """
        self._reason = reason
        if force:
            logger.debug(
                "[TeammateAbortController] Force-cancel requested: %s", reason or "(no reason)"
            )
            self.force_cancel.set()
            self.cancel_event.set()  # Also set graceful so both checks fire
        else:
            logger.debug(
                "[TeammateAbortController] Graceful cancel requested: %s",
                reason or "(no reason)",
            )
            self.cancel_event.set()

    @property
    def reason(self) -> str | None:
        """The reason provided to the most recent :meth:`request_cancel` call."""
        return self._reason


# ---------------------------------------------------------------------------
# Per-teammate context isolation via ContextVar
# ---------------------------------------------------------------------------


TeammateStatus = Literal["starting", "running", "idle", "stopping", "stopped"]


@dataclass
class TeammateContext:
    """All per-teammate state that must be isolated across concurrent agents.

    Stored in a :data:`ContextVar` so that each asyncio Task sees its own
    copy without any locking.
    """

    agent_id: str
    """Unique agent identifier (``agentName@teamName``)."""

    agent_name: str
    """Human-readable name, e.g. ``"researcher"``."""

    team_name: str
    """Team this teammate belongs to."""

    parent_session_id: str | None = None
    """Session ID of the spawning leader for transcript correlation."""

    parent_agent_id: str | None = None
    """Agent ID of the direct parent in the runtime tree."""

    root_agent_id: str | None = None
    """Agent ID of the root of this teammate tree."""

    session_id: str | None = None
    """Session ID for this teammate."""

    lineage_path: tuple[str, ...] = ()
    """Tree path from root to the current teammate."""

    color: str | None = None
    """Optional UI color string."""

    plan_mode_required: bool = False
    """Whether this agent must enter plan mode before making changes."""

    abort_controller: TeammateAbortController = field(
        default_factory=TeammateAbortController
    )
    """Dual-signal abort controller (graceful cancel + force kill)."""

    message_queue: asyncio.Queue[TeammateMessage] = field(
        default_factory=asyncio.Queue
    )
    """Queue of pending messages delivered between turns.

    The execution loop drains this between query iterations so messages from
    the leader are injected as new user turns rather than being lost.
    """

    status: TeammateStatus = "starting"
    """Lifecycle status of this teammate."""

    started_at: float = field(default_factory=time.time)
    """Unix timestamp when this teammate was spawned."""

    tool_use_count: int = 0
    """Number of tool invocations made during this teammate's lifetime."""

    total_tokens: int = 0
    """Cumulative token count (input + output) across all query turns."""

    # Backwards-compatible shim so existing code that reads ``cancel_event``
    # continues to work without modification.
    @property
    def cancel_event(self) -> asyncio.Event:
        """Graceful cancellation event (delegates to :attr:`abort_controller`)."""
        return self.abort_controller.cancel_event


_teammate_context_var: ContextVar[TeammateContext | None] = ContextVar(
    "_teammate_context_var", default=None
)


def get_teammate_context() -> TeammateContext | None:
    """Return the :class:`TeammateContext` for the currently-running teammate task.

    Returns ``None`` when called outside of an in-process teammate.
    """
    return _teammate_context_var.get()


def set_teammate_context(ctx: TeammateContext) -> None:
    """Bind *ctx* to the current async context (task-local)."""
    _teammate_context_var.set(ctx)


# ---------------------------------------------------------------------------
# Agent execution loop
# ---------------------------------------------------------------------------


async def start_in_process_teammate(
    *,
    config: TeammateSpawnConfig,
    agent_id: str,
    abort_controller: TeammateAbortController,
    query_context: Any | None = None,
    message_queue: asyncio.Queue[TeammateMessage] | None = None,
) -> None:
    """Run the agent query loop for an in-process teammate.

    This coroutine is launched as an :class:`asyncio.Task` by
    :class:`InProcessBackend`.  It:

    1. Binds a fresh :class:`TeammateContext` to the current async context.
    2. Drives the query engine loop (reusing
       :func:`~openharness.engine.query.run_query`).
    3. Polls the teammate's mailbox between turns for incoming messages /
       shutdown requests.  Any ``user_message`` items are pushed into the
       context's :attr:`~TeammateContext.message_queue` and injected as
       additional user turns.
    4. Writes an idle-notification to the leader when done.
    5. Cleans up on normal exit *or* cancellation.

    Parameters
    ----------
    config:
        Spawn configuration from the leader.
    agent_id:
        Fully-qualified agent identifier (``name@team``).
    abort_controller:
        Dual-signal abort controller for this teammate.
    query_context:
        Optional pre-built
        :class:`~openharness.engine.query.QueryContext`.  When *None* this
        function tries to build a full runtime (unless
        ``OPENHARNESS_TEAMMATE_USE_STUB=1``), then falls back to a stub.
    message_queue:
        Shared queue for :meth:`InProcessBackend.send_message` delivery;
        must match the queue stored on :class:`_TeammateEntry` when spawned.
    """
    ctx = TeammateContext(
        agent_id=agent_id,
        agent_name=config.name,
        team_name=config.team,
        parent_session_id=config.parent_session_id,
        parent_agent_id=config.parent_agent_id,
        root_agent_id=config.resolved_root_agent_id(),
        session_id=config.session_id or agent_id,
        lineage_path=config.resolved_lineage_path(),
        color=config.color,
        plan_mode_required=config.plan_mode_required,
        abort_controller=abort_controller,
        started_at=time.time(),
        status="starting",
        message_queue=message_queue or asyncio.Queue(),
    )
    set_teammate_context(ctx)

    mailbox = TeammateMailbox(team_name=config.team, agent_id=config.name)
    event_store = get_event_store()
    context_registry = get_context_registry()
    context_registry.register(
        AgentContextSnapshot(
            agent_id=agent_id,
            session_id=ctx.session_id or agent_id,
            parent_agent_id=ctx.parent_agent_id,
            root_agent_id=ctx.root_agent_id or agent_id,
            lineage_path=ctx.lineage_path,
            prompt=config.prompt,
            system_prompt=config.system_prompt,
            messages=(f"user: {config.prompt}",),
        )
    )
    event_store.append(
        new_swarm_event(
            "agent_spawned",
            agent_id=agent_id,
            parent_agent_id=config.parent_agent_id,
            root_agent_id=config.resolved_root_agent_id(),
            session_id=ctx.session_id or agent_id,
            payload={
                "name": config.name,
                "team": config.team,
                "lineage_path": list(ctx.lineage_path),
                "backend_type": "in_process",
            },
        )
    )

    logger.debug("[in_process] %s: starting", agent_id)

    try:
        ctx.status = "running"
        event_store.append(
            new_swarm_event(
                "agent_became_running",
                agent_id=agent_id,
                parent_agent_id=config.parent_agent_id,
                root_agent_id=config.resolved_root_agent_id(),
                session_id=ctx.session_id or agent_id,
                payload={"status": ctx.status},
            )
        )

        resolved_qc = query_context
        own_bundle = None
        if resolved_qc is None and os.environ.get("OPENHARNESS_TEAMMATE_USE_STUB") != "1":
            try:
                from openharness.swarm.teammate_runtime import build_teammate_runtime_bundle

                own_bundle = await build_teammate_runtime_bundle(config, agent_id, ctx)
                resolved_qc = own_bundle.engine.to_query_context()
            except Exception:
                logger.exception(
                    "[in_process] %s: failed to build teammate runtime; using stub",
                    agent_id,
                )
                resolved_qc = None

        if resolved_qc is not None:
            resolved_qc.tool_metadata = {
                **(resolved_qc.tool_metadata or {}),
                "session_id": ctx.session_id or agent_id,
                "swarm_agent_id": agent_id,
                "swarm_parent_agent_id": ctx.parent_agent_id,
                "swarm_root_agent_id": ctx.root_agent_id or agent_id,
                "swarm_lineage_path": ctx.lineage_path,
            }
            try:
                await _run_query_loop(resolved_qc, config, ctx, mailbox)
            finally:
                if own_bundle is not None:
                    from openharness.ui.runtime import close_runtime

                    await close_runtime(own_bundle)
        else:
            logger.info(
                "[in_process] %s: stub run for prompt: %.80s",
                agent_id,
                config.prompt,
            )
            ctx.status = "idle"
            for _ in range(10):
                if abort_controller.is_cancelled:
                    logger.debug("[in_process] %s: cancelled during stub run", agent_id)
                    return
                await asyncio.sleep(0.1)

    except asyncio.CancelledError:
        logger.debug("[in_process] %s: task cancelled", agent_id)
        raise
    except Exception:
        logger.exception("[in_process] %s: unhandled exception in agent loop", agent_id)
    finally:
        ctx.status = "stopped"
        event_store.append(
            new_swarm_event(
                "agent_finished",
                agent_id=agent_id,
                parent_agent_id=config.parent_agent_id,
                root_agent_id=config.resolved_root_agent_id(),
                session_id=ctx.session_id or agent_id,
                payload={
                    "status": ctx.status,
                    "tool_use_count": ctx.tool_use_count,
                    "total_tokens": ctx.total_tokens,
                },
            )
        )
        # Notify the leader that this teammate has gone idle / finished.
        with contextlib.suppress(Exception):
            idle_msg = create_idle_notification(
                sender=agent_id,
                recipient="leader",
                summary=f"{config.name} finished (tools={ctx.tool_use_count}, tokens={ctx.total_tokens})",
            )
            leader_mailbox = TeammateMailbox(team_name=config.team, agent_id="leader")
            await leader_mailbox.write(idle_msg)

        logger.debug(
            "[in_process] %s: exiting (tools=%d, tokens=%d)",
            agent_id,
            ctx.tool_use_count,
            ctx.total_tokens,
        )


async def _drain_mailbox(
    mailbox: TeammateMailbox,
    ctx: TeammateContext,
) -> bool:
    """Read pending mailbox messages and handle shutdown / user messages.

    Returns:
        True if a shutdown message was received (caller should stop the loop).
    """
    try:
        pending = await mailbox.read_all(unread_only=True)
    except Exception:
        pending = []

    for msg in pending:
        try:
            await mailbox.mark_read(msg.id)
        except Exception:
            pass

        if msg.type == "shutdown":
            logger.debug("[in_process] %s: received shutdown message", ctx.agent_id)
            ctx.abort_controller.request_cancel(reason="shutdown message received")
            return True

        elif msg.type == "user_message":
            # Enqueue the message so the query loop can inject it as a new turn.
            logger.debug("[in_process] %s: queuing user_message from mailbox", ctx.agent_id)
            content = msg.payload.get("content", "") if isinstance(msg.payload, dict) else str(msg.payload)
            teammate_msg = TeammateMessage(
                text=content,
                from_agent=msg.sender,
                color=msg.payload.get("color") if isinstance(msg.payload, dict) else None,
                timestamp=str(msg.timestamp),
            )
            await ctx.message_queue.put(teammate_msg)

    return False


async def _run_query_loop(
    query_context: Any,
    config: TeammateSpawnConfig,
    ctx: TeammateContext,
    mailbox: TeammateMailbox,
) -> None:
    """Drive :func:`~openharness.engine.query.run_query` until done or cancelled.

    For ``spawn_mode="persistent"``, after each completed model turn (no pending
    tools), waits for further :class:`TeammateMessage` deliveries (debugger or
    leader) and runs additional query rounds on the growing transcript.
    """
    # Deferred import to avoid circular dependencies at module load time.
    from openharness.engine.messages import ConversationMessage
    from openharness.engine.query import run_query
    from openharness.engine.stream_events import ToolExecutionStarted

    messages: list[ConversationMessage] = [
        ConversationMessage.from_user_text(config.prompt)
    ]
    context_registry = get_context_registry()
    persistent = config.spawn_mode == "persistent"

    while not ctx.abort_controller.is_cancelled:
        async for event, usage in run_query(query_context, messages):
            if usage is not None:
                with contextlib.suppress(AttributeError, TypeError):
                    ctx.total_tokens += getattr(usage, "input_tokens", 0)
                    ctx.total_tokens += getattr(usage, "output_tokens", 0)

            if isinstance(event, ToolExecutionStarted):
                ctx.tool_use_count += 1

            if ctx.abort_controller.is_cancelled:
                logger.debug(
                    "[in_process] %s: abort_controller cancelled, stopping query loop",
                    ctx.agent_id,
                )
                return

            should_stop = await _drain_mailbox(mailbox, ctx)
            if should_stop:
                return

            while not ctx.message_queue.empty():
                try:
                    queued = ctx.message_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                logger.debug(
                    "[in_process] %s: injecting queued message from %s",
                    ctx.agent_id,
                    queued.from_agent,
                )
                messages.append(ConversationMessage(role="user", content=queued.text))

            context_registry.register(
                AgentContextSnapshot(
                    agent_id=ctx.agent_id,
                    session_id=ctx.session_id or ctx.agent_id,
                    parent_agent_id=ctx.parent_agent_id,
                    root_agent_id=ctx.root_agent_id or ctx.agent_id,
                    lineage_path=ctx.lineage_path,
                    prompt=config.prompt,
                    system_prompt=config.system_prompt,
                    messages=tuple(f"{message.role}: {message.text}" for message in messages),
                )
            )

        if ctx.abort_controller.is_cancelled:
            return
        if not persistent:
            break

        while not ctx.abort_controller.is_cancelled:
            should_stop = await _drain_mailbox(mailbox, ctx)
            if should_stop:
                return
            got = False
            while not ctx.message_queue.empty():
                try:
                    queued = ctx.message_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                messages.append(ConversationMessage(role="user", content=queued.text))
                got = True
            if got:
                break
            await asyncio.sleep(0.12)

    ctx.status = "idle"


# ---------------------------------------------------------------------------
# InProcessBackend
# ---------------------------------------------------------------------------


@dataclass
class _TeammateEntry:
    """Internal registry entry for a running in-process teammate."""

    task: asyncio.Task[None]
    abort_controller: TeammateAbortController
    task_id: str
    hot_queue: asyncio.Queue[TeammateMessage]
    started_at: float = field(default_factory=time.time)


class InProcessBackend:
    """TeammateExecutor that runs agents as asyncio Tasks in the current process.

    Context isolation is provided by :mod:`contextvars`: each spawned
    :class:`asyncio.Task` runs with its own copy of the context, so
    :func:`get_teammate_context` returns the correct identity for every
    concurrent agent.
    """

    type: BackendType = "in_process"

    def __init__(self) -> None:
        # Maps agent_id -> _TeammateEntry
        self._active: dict[str, _TeammateEntry] = {}

    # ------------------------------------------------------------------
    # TeammateExecutor protocol
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """In-process backend is always available — no external dependencies."""
        return True

    async def spawn(self, config: TeammateSpawnConfig) -> SpawnResult:
        """Spawn an in-process teammate as an asyncio Task.

        Creates a :class:`TeammateAbortController`, binds it to a new Task via
        :mod:`contextvars` copy-on-create semantics, and registers the task in
        :attr:`_active`.
        """
        agent_id = f"{config.name}@{config.team}"
        task_id = f"in_process_{uuid.uuid4().hex[:12]}"

        if agent_id in self._active:
            entry = self._active[agent_id]
            if not entry.task.done():
                logger.warning(
                    "[InProcessBackend] spawn(): %s is already running", agent_id
                )
                return SpawnResult(
                    task_id=task_id,
                    agent_id=agent_id,
                    backend_type=self.type,
                    success=False,
                    error=f"Agent {agent_id!r} is already running",
                )

        abort_controller = TeammateAbortController()
        hot_queue: asyncio.Queue[TeammateMessage] = asyncio.Queue()

        # asyncio.create_task() copies the current Context automatically,
        # so each Task starts with an independent ContextVar state.
        task = asyncio.create_task(
            start_in_process_teammate(
                config=config,
                agent_id=agent_id,
                abort_controller=abort_controller,
                message_queue=hot_queue,
            ),
            name=f"teammate-{agent_id}",
        )

        entry = _TeammateEntry(
            task=task,
            abort_controller=abort_controller,
            task_id=task_id,
            hot_queue=hot_queue,
        )
        self._active[agent_id] = entry

        def _on_done(t: asyncio.Task[None]) -> None:
            self._active.pop(agent_id, None)
            if not t.cancelled() and t.exception() is not None:
                self._on_teammate_error(agent_id, t.exception())  # type: ignore[arg-type]

        task.add_done_callback(_on_done)

        logger.debug("[InProcessBackend] spawned %s (task_id=%s)", agent_id, task_id)
        return SpawnResult(
            task_id=task_id,
            agent_id=agent_id,
            backend_type=self.type,
        )

    async def send_message(self, agent_id: str, message: TeammateMessage) -> None:
        """Write *message* to the teammate's file-based mailbox.

        The agent name and team are inferred from *agent_id* (``name@team``
        format).  This mirrors how pane-based backends work so the rest of
        the swarm stack stays backend-agnostic.

        If the teammate is running in-process and its :class:`TeammateContext`
        is accessible, the message is also pushed directly into
        ``ctx.message_queue`` for low-latency delivery without a filesystem
        round-trip.

        Synthetic debugger agents (e.g. ``main``, ``sub1``) omit the team
        suffix; they are normalized to ``<name>@default`` for mailbox routing.
        """
        raw = agent_id.strip()
        if not raw:
            raise ValueError("agent_id must be non-empty")
        if "@" not in raw:
            raw = f"{raw}@default"
        agent_name, team_name = raw.split("@", 1)

        from openharness.swarm.mailbox import MailboxMessage

        msg = MailboxMessage(
            id=str(uuid.uuid4()),
            type="user_message",
            sender=message.from_agent,
            recipient=raw,
            payload={
                "content": message.text,
                **({"color": message.color} if message.color else {}),
            },
            timestamp=message.timestamp and float(message.timestamp) or time.time(),
        )
        entry = self._active.get(raw)
        if entry is not None:
            await entry.hot_queue.put(message)
            logger.debug("[InProcessBackend] queued user_message for %s (in-process)", raw)
            return
        mailbox = TeammateMailbox(team_name=team_name, agent_id=agent_name)
        await mailbox.write(msg)
        logger.debug("[InProcessBackend] sent message to %s", raw)

    async def shutdown(
        self, agent_id: str, *, force: bool = False, timeout: float = 10.0
    ) -> bool:
        """Terminate a running in-process teammate.

        Parameters
        ----------
        agent_id:
            The agent to terminate.
        force:
            If *True*, cancel the asyncio Task immediately without waiting for
            graceful shutdown.
        timeout:
            How long (seconds) to wait for the task to complete after setting
            the cancel event before falling back to :meth:`asyncio.Task.cancel`.

        Returns
        -------
        bool
            *True* if the agent was found and termination was initiated.
        """
        entry = self._active.get(agent_id)
        if entry is None:
            logger.debug(
                "[InProcessBackend] shutdown(): %s not found in active tasks", agent_id
            )
            return False

        if entry.task.done():
            self._active.pop(agent_id, None)
            return True

        if force:
            entry.abort_controller.request_cancel(reason="force shutdown", force=True)
            entry.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(entry.task), timeout=timeout)
        else:
            # Graceful: request cancel and wait for self-exit
            entry.abort_controller.request_cancel(reason="graceful shutdown")
            try:
                await asyncio.wait_for(asyncio.shield(entry.task), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    "[InProcessBackend] %s did not exit within %.1fs — forcing cancel",
                    agent_id,
                    timeout,
                )
                entry.abort_controller.request_cancel(reason="timeout — forcing", force=True)
                entry.task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await entry.task

        await self._cleanup_teammate(agent_id)
        logger.debug("[InProcessBackend] shut down %s", agent_id)
        return True

    # ------------------------------------------------------------------
    # Enhanced lifecycle management
    # ------------------------------------------------------------------

    async def _cleanup_teammate(self, agent_id: str) -> None:
        """Perform full cleanup for *agent_id* after its task finishes.

        - Removes the entry from :attr:`_active`.
        - Cancels the abort controller (in case it was not already).
        - Logs the cleanup.

        This is called automatically from the task's done-callback and from
        :meth:`shutdown`.
        """
        entry = self._active.pop(agent_id, None)
        if entry is None:
            return

        # Ensure the abort controller is signalled so any waiters unblock
        if not entry.abort_controller.is_cancelled:
            entry.abort_controller.request_cancel(reason="cleanup")

        logger.debug(
            "[InProcessBackend] _cleanup_teammate: %s removed from registry", agent_id
        )

    def _on_teammate_error(self, agent_id: str, error: Exception) -> None:
        """Handle an unhandled exception from a teammate Task.

        Logs a structured error report and removes the entry from the registry.
        In future this can emit a TaskNotification to the leader mailbox.
        """
        duration = 0.0
        entry = self._active.get(agent_id)
        if entry is not None:
            duration = time.time() - entry.started_at
            self._active.pop(agent_id, None)

        logger.error(
            "[InProcessBackend] Teammate %s raised an unhandled exception "
            "(duration=%.1fs): %s: %s",
            agent_id,
            duration,
            type(error).__name__,
            error,
        )

    def get_teammate_status(self, agent_id: str) -> dict[str, Any] | None:
        """Return a status dict for *agent_id* with usage stats.

        Returns *None* if the agent is not in the active registry.

        The returned dict includes::

            {
                "agent_id": str,
                "task_id": str,
                "is_done": bool,
                "duration_s": float,
            }
        """
        entry = self._active.get(agent_id)
        if entry is None:
            return None

        return {
            "agent_id": agent_id,
            "task_id": entry.task_id,
            "is_done": entry.task.done(),
            "duration_s": time.time() - entry.started_at,
        }

    def list_teammates(self) -> list[tuple[str, bool, float]]:
        """Return a list of ``(agent_id, is_running, duration_seconds)`` tuples.

        ``is_running`` is True if the task is alive and not done.
        ``duration_seconds`` is the wall-clock time since spawn.
        """
        now = time.time()
        result = []
        for agent_id, entry in self._active.items():
            is_running = not entry.task.done()
            duration = now - entry.started_at
            result.append((agent_id, is_running, duration))
        return result

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def is_active(self, agent_id: str) -> bool:
        """Return *True* if the teammate has a running (not-done) Task."""
        entry = self._active.get(agent_id)
        if entry is None:
            return False
        return not entry.task.done()

    def active_agents(self) -> list[str]:
        """Return a list of agent_ids with currently running Tasks."""
        return [aid for aid, entry in self._active.items() if not entry.task.done()]

    async def shutdown_all(self, *, force: bool = False, timeout: float = 10.0) -> None:
        """Gracefully (or forcefully) terminate all active teammates."""
        agent_ids = list(self._active.keys())
        await asyncio.gather(
            *(self.shutdown(aid, force=force, timeout=timeout) for aid in agent_ids),
            return_exceptions=True,
        )
