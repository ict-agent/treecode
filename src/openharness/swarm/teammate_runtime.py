"""Build :class:`~openharness.ui.runtime.RuntimeBundle` for in-process teammates."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from openharness.swarm.types import TeammateSpawnConfig
from openharness.ui.runtime import RuntimeBundle, build_runtime

logger = logging.getLogger(__name__)


async def build_teammate_runtime_bundle(
    config: TeammateSpawnConfig,
    agent_id: str,
    ctx: Any,
) -> RuntimeBundle:
    """Full OpenHarness runtime for a running teammate (API, tools, hooks, MCP).

    Swarm topology is **not** injected here; teammates use the ``swarm_context`` tool at runtime.
    """
    extra: str | None = None
    if config.system_prompt:
        extra = f"## Additional instructions from spawn\n{config.system_prompt}"

    swarm_tool_metadata: dict[str, object] = {
        "session_id": ctx.session_id or agent_id,
        "swarm_agent_id": agent_id,
        "swarm_parent_agent_id": ctx.parent_agent_id,
        "swarm_root_agent_id": ctx.root_agent_id or agent_id,
        "swarm_lineage_path": ctx.lineage_path,
    }

    return await build_runtime(
        prompt=config.prompt,
        model=config.model,
        cwd=Path(config.cwd),
        extra_system_prompt_suffix=extra,
        swarm_tool_metadata=swarm_tool_metadata,
    )
