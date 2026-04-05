export type SwarmConsoleSnapshot = {
	run_id?: string;
	active_source?: 'live' | 'scenario';
	available_sources?: string[];
	tree: {
		roots: string[];
		nodes: Record<string, {children: string[]; status: string; lineage_path: string[]}>;
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
	message_graph: Array<Record<string, unknown>>;
	approval_queue: Array<Record<string, unknown>>;
	timeline: Array<Record<string, unknown>>;
	contexts: Record<string, unknown>;
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
