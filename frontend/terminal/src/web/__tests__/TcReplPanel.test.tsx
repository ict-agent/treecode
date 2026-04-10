// @vitest-environment jsdom

import React from 'react';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';

import {createInitialReplSessionState} from '../../shared/replSession.js';
import type {AgentConsoleSnapshot} from '../../shared/swarmConsoleState.js';
import {TcReplPanel} from '../TcReplPanel.js';
import {WebReplInputHistoryProvider} from '../WebReplInputHistory.js';

afterEach(() => {
	localStorage.clear();
	cleanup();
});

function withHistory(ui: React.ReactElement): React.ReactElement {
	return <WebReplInputHistoryProvider serverRing={null}>{ui}</WebReplInputHistoryProvider>;
}

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

describe('TcReplPanel', () => {
	it('routes main-session input through tc_submit_line', () => {
		const sendCommand = vi.fn();
		const onSendAgentMessage = vi.fn();
		const tcRepl = {
			...createInitialReplSessionState(),
			transcript: [{role: 'assistant' as const, text: 'main reply'}],
		};

		render(
			withHistory(
				<TcReplPanel
					tcRepl={tcRepl}
					sendCommand={sendCommand}
					selectedAgent={null}
					onSendAgentMessage={onSendAgentMessage}
				/>,
			),
		);

		expect(screen.getByText('TreeCode session')).toBeTruthy();
		fireEvent.change(screen.getByPlaceholderText('Message TreeCode…'), {target: {value: 'hello main'}});
		fireEvent.click(screen.getByText('Send'));

		expect(sendCommand).toHaveBeenCalledWith({
			type: 'command',
			command: 'tc_submit_line',
			payload: {line: 'hello main', client_id: 'web'},
		});
		expect(onSendAgentMessage).not.toHaveBeenCalled();
	});

	it('routes selected subagent input through onSendAgentMessage', () => {
		const sendCommand = vi.fn();
		const onSendAgentMessage = vi.fn();
		const agent = makeAgent('sub1');

		render(
			withHistory(
				<TcReplPanel
					tcRepl={createInitialReplSessionState()}
					sendCommand={sendCommand}
					selectedAgent={agent}
					onSendAgentMessage={onSendAgentMessage}
				/>,
			),
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

	it('stores submitted lines and recalls the latest with ArrowUp', async () => {
		localStorage.clear();
		const sendCommand = vi.fn();
		const tcRepl = {
			...createInitialReplSessionState(),
			transcript: [],
		};

		render(
			withHistory(
				<TcReplPanel
					tcRepl={tcRepl}
					sendCommand={sendCommand}
					selectedAgent={null}
					onSendAgentMessage={vi.fn()}
				/>,
			),
		);

		const input = screen.getByPlaceholderText('Message TreeCode…') as HTMLInputElement;
		fireEvent.change(input, { target: { value: 'hello web history' } });
		fireEvent.click(screen.getByText('Send'));
		expect(sendCommand).toHaveBeenCalled();
		await waitFor(() => {
			const raw = localStorage.getItem('treecode:repl_input_history_web_v1');
			expect(raw && JSON.parse(raw).length).toBeGreaterThan(0);
		});

		fireEvent.keyDown(input, { key: 'ArrowUp', code: 'ArrowUp' });
		expect(input.value).toBe('hello web history');
	});

	it('fills the input when clicking Prev line while Busy (readOnly, not disabled)', async () => {
		localStorage.clear();
		localStorage.setItem('treecode:repl_input_history_web_v1', JSON.stringify(['saved line from ring']));
		const sendCommand = vi.fn();
		const tcRepl = {
			...createInitialReplSessionState(),
			transcript: [],
			busy: true,
		};

		render(
			withHistory(
				<TcReplPanel
					tcRepl={tcRepl}
					sendCommand={sendCommand}
					selectedAgent={null}
					onSendAgentMessage={vi.fn()}
				/>,
			),
		);

		const input = screen.getByPlaceholderText('Busy…') as HTMLInputElement;
		expect(input.readOnly).toBe(true);
		expect(input.disabled).toBe(false);

		fireEvent.click(screen.getByText('Prev line'));
		await waitFor(() => {
			expect(input.value).toBe('saved line from ring');
		});
	});
});
