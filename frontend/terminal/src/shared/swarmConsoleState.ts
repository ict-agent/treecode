/** Summarized tool_called / tool_completed row from SwarmProjection (bounded list). */
export type ToolRecentEntry = {
	phase: 'called' | 'completed';
	agent_id: string;
	tool_name: string;
	source?: string;
	event_id?: string;
	correlation_id?: string | null;
	is_error?: boolean;
	output_preview?: string;
	tool_input_preview?: Record<string, string>;
};

/** One directed edge in the swarm message graph (from projection timeline). */
export type MessageGraphEdge = {
	from_agent?: string | null;
	to_agent?: string | null;
	correlation_id?: string | null;
	event_type?: string | null;
	text?: string | null;
};

export type SwarmTreeNode = {
	agent_id?: string;
	name?: string;
	team?: string;
	parent_agent_id?: string | null;
	root_agent_id?: string | null;
	session_id?: string | null;
	lineage_path: string[];
	status: string;
	children: string[];
	cwd?: string | null;
	worktree_path?: string | null;
	backend_type?: string | null;
	spawn_mode?: string | null;
	synthetic?: boolean;
};

export type AgentFeedItem = {
	item_id: string;
	item_type:
		| 'prompt'
		| 'turn_marker'
		| 'incoming'
		| 'outgoing'
		| 'assistant'
		| 'tool_call'
		| 'tool_result'
		| 'approval_request'
		| 'approval_result'
		| 'lifecycle'
		| 'context';
	event_type: string;
	timestamp: number | null;
	correlation_id?: string | null;
	actor?: string;
	label?: string;
	text?: string;
	message_count?: number;
	tool_name?: string;
	tool_input?: Record<string, unknown>;
	source?: unknown;
	status?: string | null;
	is_error?: boolean;
	has_tool_uses?: boolean;
	route_kind?: unknown;
};

export type AgentConsoleSnapshot = {
	agent_id: string;
	name: string;
	team: string;
	status: string;
	parent_agent_id?: string | null;
	root_agent_id?: string | null;
	session_id?: string | null;
	lineage_path: string[];
	children: string[];
	cwd?: string | null;
	worktree_path?: string | null;
	backend_type?: string | null;
	spawn_mode?: string | null;
	synthetic?: boolean;
	scenario_name?: string | null;
	prompt?: string | null;
	system_prompt?: string | null;
	context_version?: number;
	compacted_summary?: string | null;
	messages: string[];
	messages_sent: number;
	messages_received: number;
	recent_events: string[];
	event_counts: Record<string, number>;
	feed: AgentFeedItem[];
};

export type SwarmConsoleSnapshot = {
	run_id?: string;
	snapshot_revision?: number;
	active_source?: 'live' | 'scenario';
	available_sources?: string[];
	topology_view?: 'live' | 'raw_events';
	available_topology_views?: Array<'live' | 'raw_events'>;
	tree: {
		roots: string[];
		nodes: Record<string, SwarmTreeNode>;
	};
	overview: {
		agent_count: number;
		root_count: number;
		message_count: number;
		event_count: number;
		pending_approvals: number;
		max_depth: number;
		leaf_agents: string[];
	};
	activity: Record<
		string,
		{
			children: string[];
			messages_sent: number;
			messages_received: number;
			recent_events: string[];
			event_counts: Record<string, number>;
			status: string;
			parent_agent_id: string | null;
		}
	>;
	scenario_view: {
		scenario_name: string | null;
		levels: Array<{depth: number; agents: string[]}>;
		route_summary: Record<string, string[]>;
	};
	message_graph: MessageGraphEdge[];
	tool_recent: ToolRecentEntry[];
	approval_queue: Array<Record<string, unknown>>;
	timeline: Array<Record<string, unknown>>;
	contexts: Record<string, unknown>;
	agents: Record<string, AgentConsoleSnapshot>;
	archives: Array<Record<string, unknown>>;
};

export type SwarmConsoleMessage =
	| {type: 'snapshot'; payload: SwarmConsoleSnapshot}
	| {type: 'ack'; payload: Record<string, unknown>}
	| {type: 'archives'; payload: {archives: Array<Record<string, unknown>>} | Array<Record<string, unknown>>}
	| {type: 'compare_result'; payload: Record<string, unknown>}
	| {type: 'error'; payload: Record<string, unknown>; message?: string};

export type SwarmConsoleState = {
	currentRunId: string | null;
	snapshot: SwarmConsoleSnapshot | null;
	active_source?: 'live' | 'scenario';
	available_sources?: string[];
	topology_view?: 'live' | 'raw_events';
	available_topology_views?: Array<'live' | 'raw_events'>;
	archives: Array<Record<string, unknown>>;
	comparison: Record<string, unknown> | null;
	lastError: string | null;
	lastAck: Record<string, unknown> | null;
};

export function createInitialSwarmConsoleState(): SwarmConsoleState {
	return {
		currentRunId: null,
		snapshot: null,
		archives: [],
		comparison: null,
		lastError: null,
		lastAck: null,
	};
}

export function reduceSwarmConsoleMessage(
	state: SwarmConsoleState,
	message: SwarmConsoleMessage,
): SwarmConsoleState {
	if (message.type === 'snapshot') {
		return {
			...state,
			currentRunId: message.payload.run_id ?? state.currentRunId,
			snapshot: message.payload,
			active_source: message.payload.active_source,
			available_sources: message.payload.available_sources,
			topology_view: message.payload.topology_view,
			available_topology_views: message.payload.available_topology_views,
			lastError: null,
		};
	}
	if (message.type === 'archives') {
		return {
			...state,
			archives: Array.isArray(message.payload) ? message.payload : message.payload.archives,
		};
	}
	if (message.type === 'ack') {
		return {
			...state,
			lastAck: message.payload,
			lastError: null,
		};
	}
	if (message.type === 'compare_result') {
		return {
			...state,
			comparison: message.payload,
		};
	}
	if (message.type === 'error') {
		return {
			...state,
			lastError: message.message ?? String(message.payload.message ?? 'unknown error'),
		};
	}
	return state;
}
