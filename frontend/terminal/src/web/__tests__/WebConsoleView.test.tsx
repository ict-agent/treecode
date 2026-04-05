// @vitest-environment jsdom

import React from 'react';
import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';

import type {SwarmConsoleState} from '../../shared/swarmConsoleState.js';
import {WebConsoleView} from '../WebConsoleView.js';

function makeState(): SwarmConsoleState {
	return {
		currentRunId: 'run-1',
		active_source: 'live',
		available_sources: ['live', 'scenario'],
		archives: [{run_id: 'run-0', label: 'previous'}],
		comparison: null,
		lastError: null,
		lastAck: null,
		snapshot: {
			run_id: 'run-1',
			tree: {
				roots: ['main'],
				nodes: {
					main: {children: ['sub1'], status: 'running', lineage_path: ['main']},
					sub1: {children: ['A', 'B'], status: 'running', lineage_path: ['main', 'sub1']},
					A: {children: [], status: 'running', lineage_path: ['main', 'sub1', 'A']},
					B: {children: [], status: 'running', lineage_path: ['main', 'sub1', 'B']},
				},
			},
			overview: {
				agent_count: 4,
				root_count: 1,
				message_count: 3,
				event_count: 12,
				pending_approvals: 1,
				max_depth: 3,
				leaf_agents: ['A', 'B'],
			},
			activity: {
				sub1: {
					children: ['A', 'B'],
					messages_sent: 2,
					messages_received: 1,
					recent_events: ['agent_spawned'],
					event_counts: {agent_spawned: 1},
					status: 'running',
					parent_agent_id: 'main',
				},
			},
			scenario_view: {
				scenario_name: 'two_level_fanout',
				levels: [
					{depth: 1, agents: ['main']},
					{depth: 2, agents: ['sub1']},
					{depth: 3, agents: ['A', 'B']},
				],
				route_summary: {sub1: ['A', 'B']},
			},
			message_graph: [],
			approval_queue: [
				{correlation_id: 'approval-on-leaf', agent_id: 'B', tool_name: 'bash', status: 'pending'},
			],
			timeline: [{event_type: 'agent_spawned', agent_id: 'main'}],
			contexts: {},
			archives: [],
		},
	};
}

describe('WebConsoleView', () => {
	it('renders aggregate sections and approval actions', () => {
		const onRunScenario = vi.fn();
		const onResolveApproval = vi.fn();
		render(
			<WebConsoleView
				state={makeState()}
				onRunScenario={onRunScenario}
				onResolveApproval={onResolveApproval}
				onSendMessage={vi.fn()}
				onCompareRuns={vi.fn()}
				onArchiveRun={vi.fn()}
				onSpawnAgent={vi.fn()}
				onReparentAgent={vi.fn()}
				onRemoveAgent={vi.fn()}
				onApplyContextPatch={vi.fn()}
				onPauseAgent={vi.fn()}
				onResumeAgent={vi.fn()}
				onStopAgent={vi.fn()}
				onAgentAction={vi.fn()}
				onSetActiveSource={vi.fn()}
			/>
		);

		expect(screen.getByText('Scenario View')).toBeTruthy();
		expect(screen.getByText('Live Source')).toBeTruthy();
		expect(screen.getByText('Scenario Source')).toBeTruthy();
		expect(screen.getAllByText('two_level_fanout')).toHaveLength(2);
		expect(screen.getByText(/Leaf agents: A, B/)).toBeTruthy();
		expect(screen.getByText('Approve')).toBeTruthy();
		expect(screen.getByText('Reject')).toBeTruthy();
		expect(screen.getByText('Spawn Agent')).toBeTruthy();
		expect(screen.getByText('Agent Control')).toBeTruthy();
		expect(screen.getByText('Agent Operations')).toBeTruthy();
		expect(screen.getByText('Run Operation')).toBeTruthy();
		expect(screen.getByText('run_tool')).toBeTruthy();
		expect(screen.getByText('Pause')).toBeTruthy();
		expect(screen.getByText('Resume')).toBeTruthy();
		expect(screen.getByText('Stop')).toBeTruthy();
		expect(screen.getByText('Topology Editor')).toBeTruthy();
		expect(screen.getByText('Run Archives')).toBeTruthy();

		fireEvent.click(screen.getAllByText('two_level_fanout')[0]!);
		expect(onRunScenario).toHaveBeenCalledWith('two_level_fanout');

		fireEvent.click(screen.getByText('Approve'));
		expect(onResolveApproval).toHaveBeenCalledWith('approval-on-leaf', 'approved');
	});
});
