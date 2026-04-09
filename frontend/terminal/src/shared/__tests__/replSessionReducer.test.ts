import {describe, expect, it} from 'vitest';

import type {SlashCommandEntry} from '../../types.js';
import {createInitialReplSessionState, reduceReplBackendEvent} from '../replSession.js';

describe('repl session reducer', () => {
	it('handles ready, assistant delta, assistant complete, and line completion', () => {
		let state = createInitialReplSessionState();

		const helpEntry: SlashCommandEntry = {
			name: 'help',
			prefix: '/help',
			description: 'Show available commands',
			usage: '/help [command]',
		};
		state = reduceReplBackendEvent(state, {
			type: 'ready',
			state: {permission_mode: 'default', model: 'localmodel'},
			tasks: [{id: 't1', type: 'local_agent', status: 'running', description: 'task', metadata: {}}],
			commands: [helpEntry],
			mcp_servers: [],
			bridge_sessions: [],
		});
		state = reduceReplBackendEvent(state, {
			type: 'assistant_delta',
			message: 'Hello',
		});
		state = reduceReplBackendEvent(state, {
			type: 'assistant_complete',
			message: 'Hello world',
		});
		state = reduceReplBackendEvent(state, {
			type: 'line_complete',
		});

		expect(state.status.model).toBe('localmodel');
		expect(state.tasks).toHaveLength(1);
		expect(state.commandCatalog).toEqual([helpEntry]);
		expect(state.transcript.at(-1)?.text).toBe('Hello world');
		expect(state.assistantBuffer).toBe('');
		expect(state.busy).toBe(false);
	});

	it('normalizes legacy string[] commands into commandCatalog', () => {
		const state = reduceReplBackendEvent(createInitialReplSessionState(), {
			type: 'ready',
			state: {},
			tasks: [],
			commands: ['/foo'],
			mcp_servers: [],
			bridge_sessions: [],
		});
		expect(state.commandCatalog).toEqual([
			{name: 'foo', prefix: '/foo', description: '', usage: '/foo'},
		]);
	});

	it('turns select_request and modal_request into UI state', () => {
		let state = createInitialReplSessionState();

		state = reduceReplBackendEvent(state, {
			type: 'select_request',
			modal: {title: 'Resume session', submit_prefix: '/resume '},
			select_options: [{value: 'abc', label: 'abc'}],
		});
		state = reduceReplBackendEvent(state, {
			type: 'modal_request',
			modal: {kind: 'permission', tool_name: 'bash'},
		});

		expect(state.selectRequest?.title).toBe('Resume session');
		expect(state.modal?.kind).toBe('permission');
	});
});
