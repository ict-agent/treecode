import React, {useEffect, useMemo, useRef, useState} from 'react';
import {Box, Text, useApp, useInput} from 'ink';

import {CommandPicker} from './components/CommandPicker.js';
import {ConversationView} from './components/ConversationView.js';
import {ModalHost} from './components/ModalHost.js';
import {PromptInput} from './components/PromptInput.js';
import {SelectModal, type SelectOption} from './components/SelectModal.js';
import {StatusBar} from './components/StatusBar.js';
import {SwarmPanel} from './components/SwarmPanel.js';
import {TodoPanel} from './components/TodoPanel.js';
import {useBackendSession} from './hooks/useBackendSession.js';
import {appendReplInputHistory, loadReplInputHistory, watchReplInputHistory} from './replInputHistory.js';
import {ThemeProvider, useTheme} from './theme/ThemeContext.js';
import type {FrontendConfig, SlashCommandEntry} from './types.js';

const rawReturnSubmit = process.env.OPENHARNESS_FRONTEND_RAW_RETURN === '1';
const scriptedSteps = (() => {
	const raw = process.env.OPENHARNESS_FRONTEND_SCRIPT;
	if (!raw) {
		return [] as string[];
	}
	try {
		const parsed = JSON.parse(raw);
		return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : [];
	} catch {
		return [];
	}
})();

const PERMISSION_MODES: SelectOption[] = [
	{value: 'default', label: 'Default', description: 'Ask before write/execute operations'},
	{value: 'full_auto', label: 'Auto', description: 'Allow all tools automatically'},
	{value: 'plan', label: 'Plan Mode', description: 'Block all write operations'},
];

type SelectModalState = {
	title: string;
	options: SelectOption[];
	onSelect: (value: string) => void;
} | null;

export function App({config}: {config: FrontendConfig}): React.JSX.Element {
	const initialTheme = String((config as Record<string, unknown>).theme ?? 'default');
	return (
		<ThemeProvider initialTheme={initialTheme}>
			<AppInner config={config} />
		</ThemeProvider>
	);
}

function AppInner({config}: {config: FrontendConfig}): React.JSX.Element {
	const {exit} = useApp();
	const {theme, setThemeName} = useTheme();
	const [input, setInput] = useState('');
	const [modalInput, setModalInput] = useState('');
	const [history, setHistory] = useState<string[]>(() => loadReplInputHistory());
	const [historyIndex, setHistoryIndex] = useState(-1);
	const [scriptIndex, setScriptIndex] = useState(0);
	const [pickerIndex, setPickerIndex] = useState(0);
	const [selectModal, setSelectModal] = useState<SelectModalState>(null);
	const [selectIndex, setSelectIndex] = useState(0);
	const historyTabCycle = useRef(0);
	const sentInitialPromptRef = useRef(false);
	const session = useBackendSession(config, () => exit());

	const commitLineToHistory = (line: string): void => {
		setHistory((items) => appendReplInputHistory(items, line));
		setHistoryIndex(-1);
	};

	/** Main OpenHarness REPL only: keep in sync when Web Console (or another process) appends the same jsonl file. */
	useEffect(() => {
		return watchReplInputHistory(() => {
			setHistory(loadReplInputHistory());
			setHistoryIndex(-1);
		});
	}, []);

	/** User typed/pasted in the prompt — exit history-browse mode so ↑↓ and slash menu behave normally. */
	const handleInputChange = (value: string): void => {
		setHistoryIndex(-1);
		setInput(value);
	};

	// CLI `-p` / launcher `initial_prompt`: same as typed input — persist to REPL history file.
	useEffect(() => {
		if (!session.ready || config.initial_prompt == null || config.initial_prompt === '') {
			return;
		}
		if (sentInitialPromptRef.current) {
			return;
		}
		sentInitialPromptRef.current = true;
		const line = String(config.initial_prompt).trim();
		if (!line) {
			return;
		}
		session.sendRequest({type: 'submit_line', line});
		commitLineToHistory(line);
		session.setBusy(true);
	}, [session.ready, config.initial_prompt]);

	useEffect(() => {
		historyTabCycle.current = 0;
	}, [input]);

	// Current tool name for spinner
	const currentToolName = useMemo(() => {
		for (let i = session.transcript.length - 1; i >= 0; i--) {
			const item = session.transcript[i];
			if (item.role === 'tool') {
				return item.tool_name ?? 'tool';
			}
			if (item.role === 'tool_result' || item.role === 'assistant') {
				break;
			}
		}
		return undefined;
	}, [session.transcript]);

	// Slash command completion (prefix match on /command).
	// Require at least two characters (e.g. `/h`) so a lone `/` does not match every command;
	// otherwise showPicker steals ↑↓ and input history navigation never runs.
	const commandHints = useMemo((): SlashCommandEntry[] => {
		const value = input.trim();
		if (!value.startsWith('/') || value.length < 2) {
			return [];
		}
		return session.commandCatalog.filter((c) => c.prefix.startsWith(value)).slice(0, 12);
	}, [session.commandCatalog, input]);

	// While recalling prior lines (↑↓, historyIndex >= 0), never treat input as a fresh slash
	// completion — otherwise `/foo…` from history steals arrows and you cannot scroll past it.
	const showPicker =
		historyIndex < 0 &&
		commandHints.length > 0 &&
		!session.busy &&
		!session.modal &&
		!selectModal;

	useEffect(() => {
		setPickerIndex(0);
	}, [commandHints.length, input]);

	// Handle backend-initiated select requests (e.g. /resume session list)
	useEffect(() => {
		if (!session.selectRequest) {
			return;
		}
		const req = session.selectRequest;
		if (req.options.length === 0) {
			session.setSelectRequest(null);
			return;
		}
		setSelectIndex(0);
		setSelectModal({
			title: req.title,
			options: req.options.map((o) => ({value: o.value, label: o.label, description: o.description})),
			onSelect: (value) => {
				const line = `${req.submitPrefix}${value}`;
				session.sendRequest({type: 'submit_line', line});
				commitLineToHistory(line);
				session.setBusy(true);
				setSelectModal(null);
			},
		});
		session.setSelectRequest(null);
	}, [session.selectRequest]);

	// Intercept special commands that need interactive UI
	const handleCommand = (cmd: string): boolean => {
		const trimmed = cmd.trim();

		// /theme set <name> → switch theme locally
		const themeMatch = /^\/theme\s+set\s+(\S+)$/.exec(trimmed);
		if (themeMatch) {
			setThemeName(themeMatch[1]);
			return true;
		}

		// /permissions → show mode picker
		if (trimmed === '/permissions' || trimmed === '/permissions show') {
			const currentMode = String(session.status.permission_mode ?? 'default');
			const options = PERMISSION_MODES.map((opt) => ({
				...opt,
				active: opt.value === currentMode,
			}));
			const initialIndex = options.findIndex((o) => o.active);
			setSelectIndex(initialIndex >= 0 ? initialIndex : 0);
			setSelectModal({
				title: 'Permission Mode',
				options,
				onSelect: (value) => {
					const line = `/permissions set ${value}`;
					session.sendRequest({type: 'submit_line', line});
					commitLineToHistory(line);
					session.setBusy(true);
					setSelectModal(null);
				},
			});
			return true;
		}

		// /plan → toggle plan mode
		if (trimmed === '/plan') {
			const currentMode = String(session.status.permission_mode ?? 'default');
			const line = currentMode === 'plan' ? '/plan off' : '/plan on';
			session.sendRequest({type: 'submit_line', line});
			commitLineToHistory(line);
			session.setBusy(true);
			return true;
		}

		// /resume → request session list from backend (will trigger select_request)
		if (trimmed === '/resume') {
			session.sendRequest({type: 'list_sessions'});
			return true;
		}

		return false;
	};

	useInput((chunk, key) => {
		const isPaste = chunk.length > 1 && !key.ctrl && !key.meta;

		// Ctrl+C → exit
		if (key.ctrl && chunk === 'c') {
			session.sendRequest({type: 'shutdown'});
			exit();
			return;
		}

		// Let ink-text-input handle pasted text directly.
		if (isPaste) {
			return;
		}

		// Ctrl+A → toggle auto
		if (key.ctrl && chunk === 'a') {
			const currentMode = String(session.status.permission_mode ?? 'default');
			const nextMode = currentMode === 'full_auto' ? 'default' : 'full_auto';
			const line = `/permissions set ${nextMode}`;
			session.sendRequest({type: 'submit_line', line});
			commitLineToHistory(line);
			session.setBusy(true);
			return;
		}

		// --- Select modal (permissions picker etc.) ---
		if (selectModal) {
			if (key.upArrow) {
				setSelectIndex((i) => Math.max(0, i - 1));
				return;
			}
			if (key.downArrow) {
				setSelectIndex((i) => Math.min(selectModal.options.length - 1, i + 1));
				return;
			}
			if (key.return) {
				const selected = selectModal.options[selectIndex];
				if (selected) {
					selectModal.onSelect(selected.value);
				}
				return;
			}
			if (key.escape) {
				setSelectModal(null);
				return;
			}
			// Number keys for quick selection
			const num = parseInt(chunk, 10);
			if (num >= 1 && num <= selectModal.options.length) {
				const selected = selectModal.options[num - 1];
				if (selected) {
					selectModal.onSelect(selected.value);
				}
				return;
			}
			return;
		}

		// --- Scripted raw return ---
		if (rawReturnSubmit && key.return) {
			if (session.modal?.kind === 'question') {
				session.sendRequest({
					type: 'question_response',
					request_id: session.modal.request_id,
					answer: modalInput,
				});
				session.setModal(null);
				setModalInput('');
				return;
			}
			if (!session.modal && !session.busy && input.trim()) {
				onSubmit(input);
				return;
			}
		}

		// --- Permission modal (MUST be before busy check — modal appears while busy) ---
		if (session.modal?.kind === 'permission') {
			if (chunk.toLowerCase() === 'y') {
				session.sendRequest({
					type: 'permission_response',
					request_id: session.modal.request_id,
					allowed: true,
				});
				session.setModal(null);
				return;
			}
			if (chunk.toLowerCase() === 'n' || key.escape) {
				session.sendRequest({
					type: 'permission_response',
					request_id: session.modal.request_id,
					allowed: false,
				});
				session.setModal(null);
				return;
			}
			return;
		}

		// --- Question modal (also appears while busy) ---
		if (session.modal?.kind === 'question') {
			return; // Let TextInput in ModalHost handle input
		}

		// --- Ignore input while busy ---
		if (session.busy) {
			return;
		}

		// --- Command picker ---
		// Ink delivers keys to every useInput subscriber; returning here does not block
		// ink-text-input from appending typed characters while the picker is open.
		if (showPicker) {
			if (key.upArrow) {
				setPickerIndex((i) => Math.max(0, i - 1));
				return;
			}
			if (key.downArrow) {
				setPickerIndex((i) => Math.min(commandHints.length - 1, i + 1));
				return;
			}
			if (key.return) {
				const selected = commandHints[pickerIndex];
				if (selected) {
					setInput('');
					const line = selected.prefix;
					if (!handleCommand(line)) {
						onSubmit(line);
					}
				}
				return;
			}
			if (key.tab) {
				const selected = commandHints[pickerIndex];
				if (selected) {
					setInput(`${selected.prefix} `);
				}
				return;
			}
			if (key.escape) {
				setInput('');
				return;
			}
			return;
		}

		// --- Tab: cycle through input-history lines matching the current prefix ---
		if (key.tab) {
			const matches = [...history].reverse().filter((h) => h.startsWith(input));
			if (matches.length > 0) {
				const idx = historyTabCycle.current % matches.length;
				setInput(matches[idx]!);
				historyTabCycle.current += 1;
				setHistoryIndex(-1);
			}
			return;
		}

		// --- History navigation ---
		if (!showPicker && key.upArrow) {
			historyTabCycle.current = 0;
			const nextIndex = Math.min(history.length - 1, historyIndex + 1);
			if (nextIndex >= 0) {
				setHistoryIndex(nextIndex);
				setInput(history[history.length - 1 - nextIndex] ?? '');
			}
			return;
		}
		if (!showPicker && key.downArrow) {
			historyTabCycle.current = 0;
			const nextIndex = Math.max(-1, historyIndex - 1);
			setHistoryIndex(nextIndex);
			setInput(nextIndex === -1 ? '' : (history[history.length - 1 - nextIndex] ?? ''));
			return;
		}

		// Note: normal Enter submission is handled by TextInput's onSubmit in
		// PromptInput.  Do NOT duplicate it here — that causes double requests.
	});

	const onSubmit = (value: string): void => {
		if (session.modal?.kind === 'question') {
			session.sendRequest({
				type: 'question_response',
				request_id: session.modal.request_id,
				answer: value,
			});
			session.setModal(null);
			setModalInput('');
			return;
		}
		if (!value.trim() || session.busy || !session.ready) {
			return;
		}
		// Check if it's an interactive command
		if (handleCommand(value)) {
			commitLineToHistory(value);
			setInput('');
			return;
		}
		session.sendRequest({type: 'submit_line', line: value});
		commitLineToHistory(value);
		setInput('');
		session.setBusy(true);
	};

	// Scripted automation
	useEffect(() => {
		if (scriptIndex >= scriptedSteps.length) {
			return;
		}
		if (session.busy || session.modal || selectModal) {
			return;
		}
		const step = scriptedSteps[scriptIndex];
		const timer = setTimeout(() => {
			onSubmit(step);
			setScriptIndex((index) => index + 1);
		}, 200);
		return () => clearTimeout(timer);
	}, [scriptIndex, session.busy, session.modal, selectModal]);

	return (
		<Box flexDirection="column" paddingX={1} height="100%">
			{/* Conversation area */}
			<Box flexDirection="column" flexGrow={1}>
				<ConversationView
					items={session.transcript}
					assistantBuffer={session.assistantBuffer}
					showWelcome={session.ready}
				/>
			</Box>

			{/* Backend modal (permission confirm, question, mcp auth) */}
			{session.modal ? (
				<ModalHost
					modal={session.modal}
					modalInput={modalInput}
					setModalInput={setModalInput}
					onSubmit={onSubmit}
				/>
			) : null}

			{/* Frontend select modal (permissions picker, etc.) */}
			{selectModal ? (
				<SelectModal
					title={selectModal.title}
					options={selectModal.options}
					selectedIndex={selectIndex}
				/>
			) : null}

			{/* Command picker */}
			{showPicker ? (
				<CommandPicker hints={commandHints} selectedIndex={pickerIndex} />
			) : null}

			{/* Todo panel */}
			{session.ready && session.todoMarkdown ? (
				<TodoPanel markdown={session.todoMarkdown} />
			) : null}

			{/* Swarm panel */}
			{session.ready && (session.swarmTeammates.length > 0 || session.swarmNotifications.length > 0) ? (
				<SwarmPanel teammates={session.swarmTeammates} notifications={session.swarmNotifications} />
			) : null}

			{/* Status bar (only after backend is ready) */}
			{session.ready ? (
				<StatusBar
					status={session.status}
					tasks={session.tasks}
					agentTasksTotal={session.agentTasksTotal}
					activeToolName={session.busy ? currentToolName : undefined}
				/>
			) : null}

			{/* Input — show loading indicator until backend is ready */}
			{!session.ready ? (
				<Box>
					<Text color={theme.colors.warning}>Connecting to backend...</Text>
				</Box>
			) : session.modal || selectModal ? null : (
				<PromptInput
					busy={session.busy}
					input={input}
					setInput={handleInputChange}
					onSubmit={onSubmit}
					toolName={session.busy ? currentToolName : undefined}
					suppressSubmit={showPicker}
				/>
			)}

			{/* Keyboard hints (only after backend is ready) */}
			{session.ready && !session.modal && !session.busy && !selectModal ? (
				<Box>
					<Text dimColor>
						<Text color={theme.colors.primary}>enter</Text> send{'  '}
						<Text color={theme.colors.primary}>/</Text>+<Text color={theme.colors.primary}>letters</Text> slash
						menu{'  '}
						<Text color={theme.colors.primary}>{'\u2191\u2193'}</Text> history (persisted){'  '}
						<Text color={theme.colors.primary}>tab</Text> complete{'  '}
						<Text color={theme.colors.primary}>ctrl+a</Text> auto{'  '}
						<Text color={theme.colors.primary}>ctrl+c</Text> exit
					</Text>
				</Box>
			) : null}
		</Box>
	);
}
