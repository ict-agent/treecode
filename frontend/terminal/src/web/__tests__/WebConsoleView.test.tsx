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
			topology_view: 'live',
			available_topology_views: ['live', 'raw_events'],
			tree: {
				roots: ['main'],
				nodes: {
					main: {
						agent_id: 'main',
						name: 'main',
						team: 'default',
						parent_agent_id: null,
						root_agent_id: 'main',
						session_id: 'run-1',
						children: ['sub1'],
						status: 'running',
						lineage_path: ['main'],
						backend_type: null,
						spawn_mode: 'persistent',
						synthetic: true,
					},
					sub1: {
						agent_id: 'sub1',
						name: 'sub1',
						team: 'default',
						parent_agent_id: 'main',
						root_agent_id: 'main',
						session_id: 'run-1',
						children: ['A', 'B'],
						status: 'running',
						lineage_path: ['main', 'sub1'],
						backend_type: null,
						spawn_mode: 'persistent',
						synthetic: true,
					},
					A: {
						agent_id: 'A',
						name: 'A',
						team: 'default',
						parent_agent_id: 'sub1',
						root_agent_id: 'main',
						session_id: 'run-1',
						children: [],
						status: 'running',
						lineage_path: ['main', 'sub1', 'A'],
						backend_type: null,
						spawn_mode: 'persistent',
						synthetic: true,
					},
					B: {
						agent_id: 'B',
						name: 'B',
						team: 'default',
						parent_agent_id: 'sub1',
						root_agent_id: 'main',
						session_id: 'run-1',
						children: [],
						status: 'running',
						lineage_path: ['main', 'sub1', 'B'],
						backend_type: null,
						spawn_mode: 'persistent',
						synthetic: true,
					},
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
			message_graph: [
				{
					from_agent: 'main',
					to_agent: 'sub1',
					text: 'ping',
					event_type: 'message_delivered',
					correlation_id: 'c-demo',
				},
			],
			tool_recent: [
				{
					phase: 'completed',
					agent_id: 'worker@demo',
					tool_name: 'brief',
					source: 'console',
					is_error: false,
					output_preview: 'hello',
				},
			],
			approval_queue: [
				{correlation_id: 'approval-on-leaf', agent_id: 'B', tool_name: 'bash', status: 'pending'},
			],
			timeline: [{event_type: 'agent_spawned', agent_id: 'main'}],
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
					backend_type: null,
					spawn_mode: 'persistent',
					synthetic: true,
					scenario_name: 'two_level_fanout',
					prompt: 'Coordinate the run',
					system_prompt: null,
					context_version: 1,
					compacted_summary: null,
					messages: ['user: Coordinate the run'],
					messages_sent: 1,
					messages_received: 0,
					recent_events: ['agent_spawned'],
					event_counts: {agent_spawned: 1},
					feed: [
						{
							item_id: 'main:prompt',
							item_type: 'prompt',
							event_type: 'prompt',
							timestamp: null,
							actor: 'task',
							label: 'Task prompt',
							text: 'Coordinate the run',
						},
						{
							item_id: 'main:assistant',
							item_type: 'assistant',
							event_type: 'assistant_message',
							timestamp: 1710000000,
							actor: 'main',
							label: 'assistant',
							text: 'Spawning child agents now.',
						},
					],
				},
				sub1: {
					agent_id: 'sub1',
					name: 'sub1',
					team: 'default',
					status: 'running',
					parent_agent_id: 'main',
					root_agent_id: 'main',
					session_id: 'run-1',
					lineage_path: ['main', 'sub1'],
					children: ['A', 'B'],
					backend_type: null,
					spawn_mode: 'persistent',
					synthetic: true,
					scenario_name: 'two_level_fanout',
					prompt: 'Delegate work',
					system_prompt: null,
					context_version: 1,
					compacted_summary: null,
					messages: ['user: Delegate work'],
					messages_sent: 2,
					messages_received: 1,
					recent_events: ['agent_spawned'],
					event_counts: {agent_spawned: 1},
					feed: [
						{
							item_id: 'sub1:prompt',
							item_type: 'prompt',
							event_type: 'prompt',
							timestamp: null,
							actor: 'task',
							label: 'Task prompt',
							text: 'Delegate work',
						},
						{
							item_id: 'sub1:incoming',
							item_type: 'incoming',
							event_type: 'message_delivered',
							timestamp: 1710000100,
							actor: 'main',
							label: 'main',
							text: 'ping',
						},
					],
				},
				A: {
					agent_id: 'A',
					name: 'A',
					team: 'default',
					status: 'running',
					parent_agent_id: 'sub1',
					root_agent_id: 'main',
					session_id: 'run-1',
					lineage_path: ['main', 'sub1', 'A'],
					children: [],
					backend_type: null,
					spawn_mode: 'persistent',
					synthetic: true,
					scenario_name: 'two_level_fanout',
					prompt: 'Handle branch A',
					system_prompt: null,
					context_version: 1,
					compacted_summary: null,
					messages: ['user: Handle branch A'],
					messages_sent: 0,
					messages_received: 0,
					recent_events: ['agent_spawned'],
					event_counts: {agent_spawned: 1},
					feed: [],
				},
				B: {
					agent_id: 'B',
					name: 'B',
					team: 'default',
					status: 'running',
					parent_agent_id: 'sub1',
					root_agent_id: 'main',
					session_id: 'run-1',
					lineage_path: ['main', 'sub1', 'B'],
					children: [],
					backend_type: null,
					spawn_mode: 'persistent',
					synthetic: true,
					scenario_name: 'two_level_fanout',
					prompt: 'Handle branch B',
					system_prompt: null,
					context_version: 1,
					compacted_summary: null,
					messages: ['user: Handle branch B'],
					messages_sent: 0,
					messages_received: 0,
					recent_events: ['agent_spawned'],
					event_counts: {agent_spawned: 1},
					feed: [],
				},
			},
			archives: [],
		},
	};
}

describe('WebConsoleView', () => {
	it('renders the redesigned tree-and-detail layout', () => {
		const onRunScenario = vi.fn();
		const onResolveApproval = vi.fn();
		const onSetTopologyView = vi.fn();
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
				onSetTopologyView={onSetTopologyView}
			/>
		);

		expect(screen.getByText('OpenHarness Multi-Agent Console')).toBeTruthy();
		expect(screen.getByText('Agent Tree')).toBeTruthy();
		expect(screen.getByText('Conversation')).toBeTruthy();
		expect(screen.getByText('Controls')).toBeTruthy();
		expect(screen.getAllByText('Coordinate the run').length).toBeGreaterThanOrEqual(2);
		expect(screen.getByText('Spawning child agents now.')).toBeTruthy();
		expect(screen.getByText('Approve')).toBeTruthy();
		expect(screen.getByText('Reject')).toBeTruthy();
		expect(screen.getByText('Live topology')).toBeTruthy();
		expect(screen.getByText('Raw event topology')).toBeTruthy();
		expect(screen.getAllByText('Spawn Child').length).toBeGreaterThanOrEqual(1);
		expect(screen.getAllByText('Run Tool').length).toBeGreaterThanOrEqual(1);
		expect(screen.getByText('Archives & Compare')).toBeTruthy();

		fireEvent.click(screen.getAllByText('two_level_fanout')[0]!);
		expect(onRunScenario).toHaveBeenCalledWith('two_level_fanout');

		fireEvent.click(screen.getByText('Approve'));
		expect(onResolveApproval).toHaveBeenCalledWith('approval-on-leaf', 'approved');

		fireEvent.click(screen.getByText('Raw event topology'));
		expect(onSetTopologyView).toHaveBeenCalledWith('raw_events');

		fireEvent.click(screen.getAllByText('sub1')[0]!);
		expect(screen.getAllByText('Delegate work').length).toBeGreaterThanOrEqual(2);
		expect(screen.getByText('ping')).toBeTruthy();
	});
});
