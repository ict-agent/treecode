import {describe, expect, it} from 'vitest';

import {createInitialSwarmConsoleState, reduceSwarmConsoleMessage} from '../swarmConsoleState.js';

describe('swarm console state', () => {
	it('hydrates snapshot and derives selected run', () => {
		let state = createInitialSwarmConsoleState();

		state = reduceSwarmConsoleMessage(state, {
			type: 'snapshot',
			payload: {
				run_id: 'run-1',
				tree: {roots: ['main'], nodes: {main: {children: ['sub1'], status: 'running', lineage_path: ['main']}}},
				overview: {agent_count: 2, root_count: 1, message_count: 1, event_count: 4, pending_approvals: 0, max_depth: 2, leaf_agents: ['sub1']},
				activity: {main: {children: ['sub1'], messages_sent: 1, messages_received: 0, recent_events: ['agent_spawned'], event_counts: {agent_spawned: 1}, status: 'running', parent_agent_id: null}},
				scenario_view: {scenario_name: 'single_child', levels: [{depth: 1, agents: ['main']}, {depth: 2, agents: ['sub1']}], route_summary: {main: ['sub1']}},
				message_graph: [],
				tool_recent: [],
				approval_queue: [],
				timeline: [],
				contexts: {},
				agents: {
					main: {
						agent_id: 'main',
						name: 'main',
						team: 'default',
						status: 'running',
						parent_agent_id: null,
						root_agent_id: 'main',
						session_id: 'run-1',
						lineage_path: ['main'],
						children: ['sub1'],
						backend_type: 'synthetic',
						spawn_mode: 'persistent',
						synthetic: true,
						scenario_name: 'single_child',
						prompt: 'Coordinate',
						system_prompt: null,
						context_version: 1,
						compacted_summary: null,
						messages: ['user: Coordinate'],
						messages_sent: 1,
						messages_received: 0,
						recent_events: ['agent_spawned'],
						event_counts: {agent_spawned: 1},
						feed: [],
					},
				},
				archives: [],
			},
		});

		expect(state.currentRunId).toBe('run-1');
		expect(state.snapshot?.scenario_view.scenario_name).toBe('single_child');
		expect(state.snapshot?.overview.max_depth).toBe(2);
	});

	it('tracks archives and comparisons separately from the live snapshot', () => {
		let state = createInitialSwarmConsoleState();

		state = reduceSwarmConsoleMessage(state, {
			type: 'archives',
			payload: {archives: [{run_id: 'run-1', label: 'first'}, {run_id: 'run-2', label: 'second'}]},
		});
		state = reduceSwarmConsoleMessage(state, {
			type: 'compare_result',
			payload: {left_run_id: 'run-1', right_run_id: 'run-2', differences: ['different depth']},
		});

		expect(state.archives).toHaveLength(2);
		expect(state.comparison?.differences).toEqual(['different depth']);
	});

	it('records top-level error messages from the websocket protocol', () => {
		let state = createInitialSwarmConsoleState();
		state = reduceSwarmConsoleMessage(state, {
			type: 'error',
			payload: {},
			message: 'boom',
		});

		expect(state.lastError).toBe('boom');
	});

	it('stores the last ack payload for operation feedback', () => {
		let state = createInitialSwarmConsoleState();
		state = reduceSwarmConsoleMessage(state, {
			type: 'ack',
			payload: {agent_id: 'sub1', action: 'inspect'},
		});

		expect(state.lastAck).toEqual({agent_id: 'sub1', action: 'inspect'});
	});
});
