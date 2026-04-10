"""Built-in tool registration."""

from treecode.tools.ask_user_question_tool import AskUserQuestionTool
from treecode.tools.agent_tool import AgentTool
from treecode.tools.bash_tool import BashTool
from treecode.tools.base import BaseTool, ToolExecutionContext, ToolRegistry, ToolResult
from treecode.tools.brief_tool import BriefTool
from treecode.tools.config_tool import ConfigTool
from treecode.tools.cron_create_tool import CronCreateTool
from treecode.tools.cron_delete_tool import CronDeleteTool
from treecode.tools.cron_list_tool import CronListTool
from treecode.tools.cron_toggle_tool import CronToggleTool
from treecode.tools.enter_plan_mode_tool import EnterPlanModeTool
from treecode.tools.enter_worktree_tool import EnterWorktreeTool
from treecode.tools.exit_plan_mode_tool import ExitPlanModeTool
from treecode.tools.exit_worktree_tool import ExitWorktreeTool
from treecode.tools.file_edit_tool import FileEditTool
from treecode.tools.file_read_tool import FileReadTool
from treecode.tools.file_write_tool import FileWriteTool
from treecode.tools.glob_tool import GlobTool
from treecode.tools.grep_tool import GrepTool
from treecode.tools.list_mcp_resources_tool import ListMcpResourcesTool
from treecode.tools.lsp_tool import LspTool
from treecode.tools.mcp_auth_tool import McpAuthTool
from treecode.tools.mcp_tool import McpToolAdapter
from treecode.tools.notebook_edit_tool import NotebookEditTool
from treecode.tools.read_mcp_resource_tool import ReadMcpResourceTool
from treecode.tools.remote_trigger_tool import RemoteTriggerTool
from treecode.tools.send_message_tool import SendMessageTool
from treecode.tools.skill_tool import SkillTool
from treecode.tools.sleep_tool import SleepTool
from treecode.tools.swarm_context_tool import SwarmContextTool
from treecode.tools.swarm_gather_tool import SwarmGatherTool
from treecode.tools.swarm_handshake_tool import SwarmHandshakeTool
from treecode.tools.swarm_topology_tool import SwarmTopologyTool
from treecode.tools.task_wait_tool import TaskWaitTool
from treecode.tools.task_create_tool import TaskCreateTool
from treecode.tools.task_get_tool import TaskGetTool
from treecode.tools.task_list_tool import TaskListTool
from treecode.tools.task_output_tool import TaskOutputTool
from treecode.tools.task_stop_tool import TaskStopTool
from treecode.tools.task_update_tool import TaskUpdateTool
from treecode.tools.team_create_tool import TeamCreateTool
from treecode.tools.team_delete_tool import TeamDeleteTool
from treecode.tools.todo_write_tool import TodoWriteTool
from treecode.tools.tool_search_tool import ToolSearchTool
from treecode.tools.web_fetch_tool import WebFetchTool
from treecode.tools.web_search_tool import WebSearchTool


def create_default_tool_registry(mcp_manager=None) -> ToolRegistry:
    """Return the default built-in tool registry."""
    registry = ToolRegistry()
    for tool in (
        BashTool(),
        AskUserQuestionTool(),
        FileReadTool(),
        FileWriteTool(),
        FileEditTool(),
        NotebookEditTool(),
        LspTool(),
        McpAuthTool(),
        GlobTool(),
        GrepTool(),
        SkillTool(),
        ToolSearchTool(),
        WebFetchTool(),
        WebSearchTool(),
        ConfigTool(),
        BriefTool(),
        SleepTool(),
        EnterWorktreeTool(),
        ExitWorktreeTool(),
        TodoWriteTool(),
        EnterPlanModeTool(),
        ExitPlanModeTool(),
        CronCreateTool(),
        CronListTool(),
        CronDeleteTool(),
        CronToggleTool(),
        RemoteTriggerTool(),
        TaskCreateTool(),
        TaskGetTool(),
        TaskListTool(),
        TaskStopTool(),
        TaskOutputTool(),
        TaskWaitTool(),
        TaskUpdateTool(),
        AgentTool(),
        SwarmContextTool(),
        SwarmGatherTool(),
        SwarmHandshakeTool(),
        SwarmTopologyTool(),
        SendMessageTool(),
        TeamCreateTool(),
        TeamDeleteTool(),
    ):
        registry.register(tool)
    if mcp_manager is not None:
        registry.register(ListMcpResourcesTool(mcp_manager))
        registry.register(ReadMcpResourceTool(mcp_manager))
        for tool_info in mcp_manager.list_tools():
            registry.register(McpToolAdapter(mcp_manager, tool_info))
    return registry


__all__ = [
    "BaseTool",
    "ToolExecutionContext",
    "ToolRegistry",
    "ToolResult",
    "create_default_tool_registry",
]
