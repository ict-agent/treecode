import {useEffect, useMemo, useReducer, useRef, useState} from 'react';
import {spawn, type ChildProcessWithoutNullStreams} from 'node:child_process';
import readline from 'node:readline';

import type {
	BackendEvent,
	BridgeSessionSnapshot,
	FrontendConfig,
	McpServerSnapshot,
	SelectOptionPayload,
	SwarmNotificationSnapshot,
	SwarmTeammateSnapshot,
	TaskSnapshot,
	TranscriptItem,
} from '../types.js';
import {createInitialReplSessionState, reduceReplBackendEvent} from '../shared/replSession.js';

const PROTOCOL_PREFIX = 'OHJSON:';
const ASSISTANT_DELTA_FLUSH_MS = 33;
const ASSISTANT_DELTA_FLUSH_CHARS = 256;

export function useBackendSession(config: FrontendConfig, onExit: (code?: number | null) => void) {
	const [coreState, dispatch] = useReducer(reduceReplBackendEvent, undefined, createInitialReplSessionState);
	const [modal, setModal] = useState<Record<string, unknown> | null>(null);
	const [selectRequest, setSelectRequest] = useState<{title: string; submitPrefix: string; options: SelectOptionPayload[]} | null>(null);
	const [busy, setBusy] = useState(false);
	const [ready, setReady] = useState(false);
	const [todoMarkdown, setTodoMarkdown] = useState('');
	const [swarmTeammates, setSwarmTeammates] = useState<SwarmTeammateSnapshot[]>([]);
	const [swarmNotifications, setSwarmNotifications] = useState<SwarmNotificationSnapshot[]>([]);
	const childRef = useRef<ChildProcessWithoutNullStreams | null>(null);

	const pendingAssistantDeltaRef = useRef('');
	const assistantFlushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

	const flushPendingAssistantDeltas = (): void => {
		if (assistantFlushTimerRef.current) {
			clearTimeout(assistantFlushTimerRef.current);
			assistantFlushTimerRef.current = null;
		}
		const pending = pendingAssistantDeltaRef.current;
		if (!pending) {
			return;
		}
		pendingAssistantDeltaRef.current = '';
		dispatch({type: 'assistant_delta', message: pending});
	};

	const sendRequest = (payload: Record<string, unknown>): void => {
		const child = childRef.current;
		if (!child || child.stdin.destroyed) {
			return;
		}
		child.stdin.write(JSON.stringify(payload) + '\n');
	};

	useEffect(() => {
		const [command, ...args] = config.backend_command;
		const useDetachedGroup = process.platform !== 'win32';
		const child = spawn(command, args, {
			stdio: ['pipe', 'pipe', 'inherit'],
			env: process.env,
			// On Windows, a detached child gets its own console window and can
			// flash open/closed. Keep detached groups for POSIX only.
			detached: useDetachedGroup,
			windowsHide: true,
		});
		childRef.current = child;

		const reader = readline.createInterface({input: child.stdout});
		reader.on('line', (line) => {
			if (!line.startsWith(PROTOCOL_PREFIX)) {
				dispatch({type: 'transcript_item', item: {role: 'log', text: line}});
				return;
			}
			const event = JSON.parse(line.slice(PROTOCOL_PREFIX.length)) as BackendEvent;
			handleEvent(event);
		});

		child.on('exit', (code) => {
			dispatch({type: 'transcript_item', item: {role: 'system', text: `backend exited with code ${code ?? 0}`}});
			process.exitCode = code ?? 0;
			onExit(code);
		});

		const killChild = (): void => {
			if (!child.killed) {
				// Kill the whole process group on POSIX. On Windows, terminate the
				// direct child to avoid relying on negative PIDs.
				try {
					if (useDetachedGroup && child.pid) {
						process.kill(-child.pid, 'SIGTERM');
					} else {
						child.kill('SIGTERM');
					}
				} catch {
					child.kill('SIGTERM');
				}
			}
			if (assistantFlushTimerRef.current) {
				clearTimeout(assistantFlushTimerRef.current);
				assistantFlushTimerRef.current = null;
			}
		};
		process.on('exit', killChild);
		process.on('SIGINT', killChild);
		process.on('SIGTERM', killChild);

		return () => {
			reader.close();
			killChild();
			process.removeListener('exit', killChild);
			process.removeListener('SIGINT', killChild);
			process.removeListener('SIGTERM', killChild);
		};
	}, []);

	const handleEvent = (event: BackendEvent): void => {
		if (event.type === 'session_resync') {
			flushPendingAssistantDeltas();
			dispatch(event);
			return;
		}
		if (event.type === 'assistant_delta') {
			const delta = event.message ?? '';
			if (!delta) {
				return;
			}
			pendingAssistantDeltaRef.current += delta;
			if (pendingAssistantDeltaRef.current.length >= ASSISTANT_DELTA_FLUSH_CHARS) {
				flushPendingAssistantDeltas();
				return;
			}
			if (!assistantFlushTimerRef.current) {
				assistantFlushTimerRef.current = setTimeout(() => {
					assistantFlushTimerRef.current = null;
					flushPendingAssistantDeltas();
				}, ASSISTANT_DELTA_FLUSH_MS);
			}
			return;
		}

		if (event.type === 'assistant_complete') {
			flushPendingAssistantDeltas();
			dispatch(event);
			return;
		}

		if (event.type === 'line_complete' || event.type === 'error' || event.type === 'clear_transcript') {
			flushPendingAssistantDeltas();
		}

		dispatch(event);

		if (event.type === 'ready') {
			setReady(true);
			return;
		}
		if (event.type === 'line_complete') {
			setBusy(false);
			return;
		}
		if (event.type === 'select_request') {
			const m = event.modal ?? {};
			setSelectRequest({
				title: String(m.title ?? 'Select'),
				submitPrefix: String(m.submit_prefix ?? ''),
				options: event.select_options ?? [],
			});
			return;
		}
		if (event.type === 'modal_request') {
			setModal(event.modal ?? null);
			return;
		}
		if (event.type === 'error') {
			flushPendingAssistantDeltas();
			dispatch(event);
			setBusy(false);
			return;
		}
		if (event.type === 'todo_update') {
			if (event.todo_markdown != null) {
				setTodoMarkdown(event.todo_markdown);
			}
			return;
		}
		if (event.type === 'swarm_status') {
			if (event.swarm_teammates != null) {
				setSwarmTeammates(event.swarm_teammates);
			}
			if (event.swarm_notifications != null) {
				setSwarmNotifications((prev) => [...prev, ...event.swarm_notifications!].slice(-20));
			}
			return;
		}
		if (event.type === 'plan_mode_change') {
			if (event.plan_mode != null) {
				dispatch({type: 'plan_mode_change', plan_mode: event.plan_mode} as BackendEvent);
			}
			return;
		}
		if (event.type === 'shutdown') {
			onExit(0);
		}
	};

	return useMemo(
		() => ({
			transcript: coreState.transcript as TranscriptItem[],
			assistantBuffer: coreState.assistantBuffer,
			status: coreState.status as Record<string, unknown>,
			tasks: coreState.tasks as TaskSnapshot[],
			agentTasksTotal: coreState.agentTasksTotal,
			commandCatalog: coreState.commandCatalog,
			mcpServers: coreState.mcpServers as McpServerSnapshot[],
			bridgeSessions: coreState.bridgeSessions as BridgeSessionSnapshot[],
			modal,
			selectRequest,
			busy,
			ready,
			todoMarkdown,
			swarmTeammates,
			swarmNotifications,
			setModal,
			setSelectRequest,
			setBusy,
			sendRequest,
		}),
		[busy, coreState, modal, selectRequest, ready, todoMarkdown, swarmTeammates, swarmNotifications]
	);
}
