import type {
	BackendEvent,
	BridgeSessionSnapshot,
	McpServerSnapshot,
	SelectOptionPayload,
	TaskSnapshot,
	TranscriptItem,
} from '../types.js';

export type ReplSessionState = {
	transcript: TranscriptItem[];
	assistantBuffer: string;
	status: Record<string, unknown>;
	tasks: TaskSnapshot[];
	commands: string[];
	mcpServers: McpServerSnapshot[];
	bridgeSessions: BridgeSessionSnapshot[];
	modal: Record<string, unknown> | null;
	selectRequest: {title: string; submitPrefix: string; options: SelectOptionPayload[]} | null;
	busy: boolean;
	topology: Record<string, unknown> | null;
	selectedAgentId: string | null;
	/** When set, status bar uses this for agent count (list may be capped). */
	agentTasksTotal: number | undefined;
};

export function createInitialReplSessionState(): ReplSessionState {
	return {
		transcript: [],
		assistantBuffer: '',
		status: {},
		tasks: [],
		commands: [],
		mcpServers: [],
		bridgeSessions: [],
		modal: null,
		selectRequest: null,
		busy: false,
		topology: null,
		selectedAgentId: null,
		agentTasksTotal: undefined,
	};
}

export function reduceReplBackendEvent(state: ReplSessionState, event: BackendEvent): ReplSessionState {
	if (event.type === 'session_resync') {
		const raw = event.transcript ?? [];
		const transcript = raw.map((row) => ({
			role: row.role as TranscriptItem['role'],
			text: String(row.text ?? ''),
			tool_name: row.tool_name as string | undefined,
			tool_input: row.tool_input as Record<string, unknown> | undefined,
			is_error: row.is_error as boolean | undefined,
		}));
		return {
			...state,
			transcript,
			assistantBuffer: '',
			status: (event.state as Record<string, unknown>) ?? state.status,
			tasks: (event.tasks as ReplSessionState['tasks']) ?? state.tasks,
			commands: (event.commands as string[]) ?? state.commands,
			mcpServers: (event.mcp_servers as ReplSessionState['mcpServers']) ?? state.mcpServers,
			bridgeSessions: (event.bridge_sessions as ReplSessionState['bridgeSessions']) ?? state.bridgeSessions,
			busy: false,
			topology: (event.topology as Record<string, unknown> | undefined) ?? state.topology,
			selectedAgentId: (event.selected_agent_id as string | undefined) ?? state.selectedAgentId,
			agentTasksTotal:
				(event.agent_tasks_total as number | undefined | null) ?? state.agentTasksTotal,
		};
	}
	if (event.type === 'ready') {
		return {
			...state,
			status: event.state ?? {},
			tasks: event.tasks ?? [],
			commands: event.commands ?? [],
			mcpServers: event.mcp_servers ?? [],
			bridgeSessions: event.bridge_sessions ?? [],
			agentTasksTotal: (event.agent_tasks_total as number | undefined | null) ?? undefined,
		};
	}
	if (event.type === 'state_snapshot') {
		return {
			...state,
			status: event.state ?? {},
			mcpServers: event.mcp_servers ?? [],
			bridgeSessions: event.bridge_sessions ?? [],
		};
	}
	if (event.type === 'tasks_snapshot') {
		return {
			...state,
			tasks: event.tasks ?? [],
			agentTasksTotal: (event.agent_tasks_total as number | undefined | null) ?? state.agentTasksTotal,
		};
	}
	if (event.type === 'transcript_item' && event.item) {
		return {
			...state,
			transcript: [...state.transcript, event.item],
		};
	}
	if (event.type === 'assistant_delta') {
		return {
			...state,
			assistantBuffer: state.assistantBuffer + (event.message ?? ''),
		};
	}
	if (event.type === 'assistant_complete') {
		const text = event.message ?? state.assistantBuffer;
		return {
			...state,
			transcript: [...state.transcript, {role: 'assistant', text}],
			assistantBuffer: '',
			busy: false,
		};
	}
	if (event.type === 'line_complete') {
		return {
			...state,
			assistantBuffer: '',
			busy: false,
		};
	}
	if (event.type === 'busy_changed') {
		return {
			...state,
			busy: Boolean(event.busy),
		};
	}
	if (event.type === 'topology_snapshot') {
		return {
			...state,
			topology: (event.topology as Record<string, unknown> | undefined) ?? null,
			selectedAgentId: (event.selected_agent_id as string | undefined) ?? state.selectedAgentId,
		};
	}
	if (event.type === 'selected_agent_changed') {
		return {
			...state,
			selectedAgentId: (event.selected_agent_id as string | undefined) ?? null,
		};
	}
	if ((event.type === 'tool_started' || event.type === 'tool_completed') && event.item) {
		const enrichedItem: TranscriptItem = {
			...event.item,
			tool_name: event.item.tool_name ?? event.tool_name ?? undefined,
			tool_input: event.item.tool_input ?? undefined,
			is_error: event.item.is_error ?? event.is_error ?? undefined,
		};
		return {
			...state,
			transcript: [...state.transcript, enrichedItem],
			modal: event.type === 'tool_started' ? null : state.modal,
		};
	}
	if (event.type === 'clear_transcript') {
		return {
			...state,
			transcript: [],
			assistantBuffer: '',
		};
	}
	if (event.type === 'select_request') {
		const modal = event.modal ?? {};
		return {
			...state,
			selectRequest: {
				title: String(modal.title ?? 'Select'),
				submitPrefix: String(modal.submit_prefix ?? ''),
				options: event.select_options ?? [],
			},
		};
	}
	if (event.type === 'modal_request') {
		return {
			...state,
			modal: event.modal ?? null,
		};
	}
	if (event.type === 'error') {
		return {
			...state,
			transcript: [...state.transcript, {role: 'system', text: `error: ${event.message ?? 'unknown error'}`}],
			busy: false,
		};
	}
	if (event.type === 'plan_mode_change' && event.plan_mode != null) {
		return {
			...state,
			status: {...state.status, permission_mode: event.plan_mode},
		};
	}
	return state;
}
