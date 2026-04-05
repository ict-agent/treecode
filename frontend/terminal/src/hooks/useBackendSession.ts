import {useEffect, useMemo, useReducer, useRef, useState} from 'react';
import {spawn, type ChildProcessWithoutNullStreams} from 'node:child_process';
import readline from 'node:readline';

import type {
	BackendEvent,
	BridgeSessionSnapshot,
	FrontendConfig,
	McpServerSnapshot,
	SelectOptionPayload,
	TaskSnapshot,
	TranscriptItem,
} from '../types.js';
import {createInitialReplSessionState, reduceReplBackendEvent} from '../shared/replSession.js';

const PROTOCOL_PREFIX = 'OHJSON:';

export function useBackendSession(config: FrontendConfig, onExit: (code?: number | null) => void) {
	const [coreState, dispatch] = useReducer(reduceReplBackendEvent, undefined, createInitialReplSessionState);
	const [modal, setModal] = useState<Record<string, unknown> | null>(null);
	const [selectRequest, setSelectRequest] = useState<{title: string; submitPrefix: string; options: SelectOptionPayload[]} | null>(null);
	const [busy, setBusy] = useState(false);
	const childRef = useRef<ChildProcessWithoutNullStreams | null>(null);
	const sentInitialPrompt = useRef(false);

	const sendRequest = (payload: Record<string, unknown>): void => {
		const child = childRef.current;
		if (!child || child.stdin.destroyed) {
			return;
		}
		child.stdin.write(JSON.stringify(payload) + '\n');
	};

	useEffect(() => {
		const [command, ...args] = config.backend_command;
		const child = spawn(command, args, {
			stdio: ['pipe', 'pipe', 'inherit'],
			env: process.env,
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

		return () => {
			reader.close();
			if (!child.killed) {
				child.kill();
			}
		};
	}, []);

	const handleEvent = (event: BackendEvent): void => {
		dispatch(event);
		if (event.type === 'ready') {
			if (config.initial_prompt && !sentInitialPrompt.current) {
				sentInitialPrompt.current = true;
				sendRequest({type: 'submit_line', line: config.initial_prompt});
				setBusy(true);
			}
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
			commands: coreState.commands,
			mcpServers: coreState.mcpServers as McpServerSnapshot[],
			bridgeSessions: coreState.bridgeSessions as BridgeSessionSnapshot[],
			modal,
			selectRequest,
			busy,
			setModal,
			setSelectRequest,
			setBusy,
			sendRequest,
		}),
		[busy, coreState, modal, selectRequest]
	);
}
