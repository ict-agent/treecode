// @vitest-environment jsdom

import React from 'react';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';

import {createInitialReplSessionState} from '../../shared/replSession.js';
import type {AgentConsoleSnapshot} from '../../shared/swarmConsoleState.js';
import {OhReplPanel} from '../OhReplPanel.js';

afterEach(() => cleanup());

function makeAgent(agentId: string): AgentConsoleSnapshot {
	return {
		agent_id: agentId,
		name: agentId,
		team: 'default',
		status: 'running',
		parent_agent_id: 'main@default',
		root_agent_id: 'main@default',
		session_id: `${agentId}-session`,
		lineage_path: ['main@default', agentId],
		children: [],
		backend_type: 'subprocess',
		spawn_mode: 'persistent',
		synthetic: false,
		scenario_name: null,
		prompt: 'Do work',
		system_prompt: null,
		context_version: 1,
		compacted_summary: null,
		messages: ['user: Do work'],
		messages_sent: 0,
		messages_received: 1,
		recent_events: ['message_delivered'],
		event_counts: {message_delivered: 1},
		feed: [
			{
				item_id: `${agentId}:incoming`,
				item_type: 'incoming',
				event_type: 'message_delivered',
				timestamp: 1710000100,
				actor: 'main@default',
				label: 'main@default',
				text: 'ping',
			},
			{
				item_id: `${agentId}:tool`,
				item_type: 'tool_call',
				event_type: 'tool_called',
				timestamp: 1710000200,
				actor: agentId,
				tool_name: 'brief',
				tool_input: {text: 'translate this'},
			},
		],
	};
}

describe('OhReplPanel', () => {
	it('routes main-session input through oh_submit_line', () => {
		const sendCommand = vi.fn();
		const onSendAgentMessage = vi.fn();
		const ohRepl = {
			...createInitialReplSessionState(),
			transcript: [{role: 'assistant' as const, text: 'main reply'}],
		};

		render(
			<OhReplPanel
				ohRepl={ohRepl}
				sendCommand={sendCommand}
				selectedAgent={null}
				onSendAgentMessage={onSendAgentMessage}
			/>
		);

		expect(screen.getByText('OpenHarness session')).toBeTruthy();
		fireEvent.change(screen.getByPlaceholderText('Message OpenHarness…'), {target: {value: 'hello main'}});
		fireEvent.click(screen.getByText('Send'));

		expect(sendCommand).toHaveBeenCalledWith({
			type: 'command',
			command: 'oh_submit_line',
			payload: {line: 'hello main', client_id: 'web'},
		});
		expect(onSendAgentMessage).not.toHaveBeenCalled();
	});

	it('routes selected subagent input through onSendAgentMessage', () => {
		const sendCommand = vi.fn();
		const onSendAgentMessage = vi.fn();
		const agent = makeAgent('sub1');

		render(
			<OhReplPanel
				ohRepl={createInitialReplSessionState()}
				sendCommand={sendCommand}
				selectedAgent={agent}
				onSendAgentMessage={onSendAgentMessage}
			/>
		);

		expect(screen.getByText('sub1 session')).toBeTruthy();
		expect(screen.getByText((content) => content.includes('ping'))).toBeTruthy();
		expect(screen.getByText('brief')).toBeTruthy();
		expect(screen.getByText(/translate this/)).toBeTruthy();
		fireEvent.change(screen.getByPlaceholderText('Message sub1…'), {target: {value: 'hello subagent'}});
		fireEvent.click(screen.getByText('Send'));

		expect(onSendAgentMessage).toHaveBeenCalledWith('sub1', 'hello subagent');
		expect(sendCommand).not.toHaveBeenCalled();
	});
});
