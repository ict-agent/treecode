import React from 'react';

import type {AgentConsoleSnapshot} from '../shared/swarmConsoleState.js';
import type {ReplSessionState} from '../shared/replSession.js';
import type {SwarmConsoleCommand} from '../shared/swarmConsoleProtocol.js';
import {AgentTranscriptEntries} from './AgentTranscriptView.js';
import {colors} from './swarmConsoleTheme.js';
import {WebReplHistoryNavButtons, useWebReplComposer} from './WebReplInputHistory.js';

type Props = {
	tcRepl: ReplSessionState;
	sendCommand: (message: SwarmConsoleCommand) => void;
	selectedAgent: AgentConsoleSnapshot | null;
	onSendAgentMessage: (agentId: string, message: string) => void;
};

export function TcReplPanel({tcRepl, sendCommand, selectedAgent, onSendAgentMessage}: Props): React.JSX.Element {
	const {
		draft,
		setDraftFromUser,
		commitLineToStorage,
		clear,
		goOlder,
		goNewer,
		resetNav,
		canOlder,
		canNewer,
		inputRef,
	} = useWebReplComposer();
	const scrollRef = React.useRef<HTMLDivElement>(null);
	const isMainSession =
		!selectedAgent ||
		selectedAgent.backend_type === 'treecode_repl' ||
		selectedAgent.spawn_mode === 'interactive';
	const sessionTitle = isMainSession ? 'TreeCode session' : `${selectedAgent.agent_id} session`;
	const sessionPlaceholder = isMainSession
		? 'Message TreeCode…'
		: `Message ${selectedAgent.agent_id}…`;
	const isAgentInputDisabled = !isMainSession && (!selectedAgent || selectedAgent.status === 'finished');

	React.useEffect(() => {
		const el = scrollRef.current;
		if (el) {
			el.scrollTop = el.scrollHeight;
		}
	}, [tcRepl.transcript, tcRepl.assistantBuffer, selectedAgent]);

	const submit = () => {
		const line = draft.trim();
		if (!line || (isMainSession ? tcRepl.busy : isAgentInputDisabled)) {
			return;
		}
		if (isMainSession) {
			sendCommand({
				type: 'command',
				command: 'tc_submit_line',
				payload: {line, client_id: 'web'},
			});
			// Shared disk ring with Ink TUI (``repl_input_history.jsonl``); server also appends + WS broadcast.
			commitLineToStorage(line);
		} else if (selectedAgent) {
			onSendAgentMessage(selectedAgent.agent_id, line);
		}
		clear();
	};

	const inputDisabled = isMainSession ? tcRepl.busy : isAgentInputDisabled;
	/** Busy main session: read-only (not disabled) so Prev/Next can still fill the field; finished subagent: truly disabled. */
	const inputReadOnly = isMainSession && tcRepl.busy;
	const inputTrulyDisabled = !isMainSession && isAgentInputDisabled;

	const modal = tcRepl.modal;
	const kind = modal && typeof modal.kind === 'string' ? modal.kind : null;

	return (
		<div
			style={{
				borderBottom: `1px solid ${colors.border}`,
				background: colors.panelMuted,
				padding: '10px 18px',
				maxHeight: 'min(36vh, 280px)',
				display: 'flex',
				flexDirection: 'column',
				gap: 8,
				minHeight: 0,
				overflow: 'hidden',
			}}
		>
			<div style={{fontSize: 12, fontWeight: 600, color: colors.textMuted, letterSpacing: '0.04em'}}>
				{sessionTitle}
			</div>
			<div
				ref={scrollRef}
				style={{
					flex: '1 1 0',
					minHeight: 72,
					overflow: 'auto',
					fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
					fontSize: 12,
					lineHeight: 1.45,
					color: colors.text,
					whiteSpace: 'pre-wrap',
					wordBreak: 'break-word',
				}}
			>
				{isMainSession ? (
					<>
						{tcRepl.transcript.map((row, i) => (
							<div key={i} style={{marginBottom: 4, opacity: row.role === 'system' ? 0.85 : 1}}>
								<span style={{color: colors.accent}}>{row.role}</span>
								{row.tool_name ? (
									<span style={{color: colors.textMuted}}>{` (${row.tool_name})`}</span>
								) : null}
								{`: ${row.text}`}
							</div>
						))}
						{tcRepl.assistantBuffer ? (
							<div>
								<span style={{color: colors.accent}}>assistant</span>
								{`: ${tcRepl.assistantBuffer}`}
							</div>
						) : null}
					</>
				) : selectedAgent ? (
					<AgentTranscriptEntries agent={selectedAgent} />
				) : (
					<div style={{opacity: 0.85}}>No activity for this agent yet.</div>
				)}
			</div>

			{isMainSession && kind === 'permission' && modal && 'request_id' in modal ? (
				<div
					style={{
						display: 'flex',
						flexWrap: 'wrap',
						gap: 8,
						alignItems: 'center',
						padding: 8,
						borderRadius: 8,
						background: colors.panelMuted ?? colors.background,
						border: `1px solid ${colors.borderStrong}`,
						flexShrink: 0,
					}}
				>
					<span style={{flex: '1 1 200px', fontSize: 12}}>
						Permission: <strong>{String(modal.tool_name ?? '')}</strong>
						{modal.reason ? ` — ${String(modal.reason)}` : ''}
					</span>
					<button
						type="button"
						onClick={() =>
							sendCommand({
								type: 'command',
								command: 'tc_permission_response',
								payload: {request_id: String(modal.request_id), allowed: false},
							})
						}
						style={buttonStyle()}
					>
						Deny
					</button>
					<button
						type="button"
						onClick={() =>
							sendCommand({
								type: 'command',
								command: 'tc_permission_response',
								payload: {request_id: String(modal.request_id), allowed: true},
							})
						}
						style={{...buttonStyle(), borderColor: colors.accent, color: colors.accent}}
					>
						Allow
					</button>
				</div>
			) : null}

			{isMainSession && kind === 'question' && modal && 'request_id' in modal ? (
				<QuestionBar modal={modal as Record<string, unknown>} sendCommand={sendCommand} />
			) : null}

			<div style={{display: 'flex', flexDirection: 'column', gap: 4, flexShrink: 0}}>
				<div style={{fontSize: 10, color: colors.textMuted, lineHeight: 1.35}}>
					<strong style={{color: colors.text}}>Prev line / Next line</strong> fill this field from saved input (same as Message
					Composer). Send once to build history. Works while Busy (draft only).
				</div>
				<div
					style={{
						display: 'flex',
						gap: 8,
						alignItems: 'center',
						flexWrap: 'wrap',
						flexShrink: 0,
						minHeight: 44,
					}}
				>
					<input
						ref={inputRef as React.RefObject<HTMLInputElement>}
						type="text"
						name="treecode-repl-input"
						autoComplete="off"
						autoCorrect="off"
						autoCapitalize="off"
						spellCheck={false}
						enterKeyHint="send"
						value={draft}
						onChange={(e) => {
							setDraftFromUser(e.target.value);
						}}
						onPaste={() => {
							resetNav();
						}}
						onKeyDownCapture={(e) => {
							if (e.key === 'Enter' && !e.shiftKey) {
								e.preventDefault();
								e.stopPropagation();
								submit();
								return;
							}
							const plainArrow = !e.ctrlKey && !e.metaKey && !e.altKey && !e.shiftKey;
							if (plainArrow && (e.key === 'ArrowUp' || e.code === 'ArrowUp')) {
								e.preventDefault();
								e.stopPropagation();
								goOlder();
								return;
							}
							if (plainArrow && (e.key === 'ArrowDown' || e.code === 'ArrowDown')) {
								e.preventDefault();
								e.stopPropagation();
								goNewer();
								return;
							}
							if (e.key === 'Tab') {
								resetNav();
							}
						}}
						disabled={inputTrulyDisabled}
						readOnly={inputReadOnly}
						placeholder={isMainSession && tcRepl.busy ? 'Busy…' : sessionPlaceholder}
						style={{
							flex: 1,
							minWidth: 0,
							padding: '8px 10px',
							borderRadius: 6,
							border: `1px solid ${colors.border}`,
							background: colors.background,
							color: colors.text,
							fontSize: 13,
						}}
					/>
					<WebReplHistoryNavButtons canOlder={canOlder} canNewer={canNewer} goOlder={goOlder} goNewer={goNewer} />
					<button
						type="button"
						onClick={submit}
						disabled={inputDisabled || !draft.trim()}
						style={{
							...buttonStyle(),
							opacity: inputDisabled || !draft.trim() ? 0.5 : 1,
							borderColor: colors.accent,
							color: colors.accent,
						}}
					>
						Send
					</button>
				</div>
			</div>
		</div>
	);
}

function QuestionBar({
	modal,
	sendCommand,
}: {
	modal: Record<string, unknown>;
	sendCommand: (message: SwarmConsoleCommand) => void;
}): React.JSX.Element {
	const [answer, setAnswer] = React.useState('');
	return (
		<div
			style={{
				display: 'flex',
				flexDirection: 'column',
				gap: 6,
				padding: 8,
				borderRadius: 8,
				background: colors.panelMuted ?? colors.background,
				border: `1px solid ${colors.borderStrong}`,
			}}
		>
			<div style={{fontSize: 12}}>{String(modal.question ?? '')}</div>
			<textarea
				value={answer}
				onChange={(e) => setAnswer(e.target.value)}
				rows={2}
				style={{
					width: '100%',
					resize: 'vertical',
					fontSize: 12,
					padding: 6,
					borderRadius: 4,
					border: `1px solid ${colors.border}`,
					background: colors.background,
					color: colors.text,
				}}
			/>
			<button
				type="button"
				onClick={() =>
					sendCommand({
						type: 'command',
						command: 'tc_question_response',
						payload: {request_id: String(modal.request_id), answer},
					})
				}
				style={{...buttonStyle(), alignSelf: 'flex-end', borderColor: colors.accent, color: colors.accent}}
			>
				Submit answer
			</button>
		</div>
	);
}

function buttonStyle(): React.CSSProperties {
	return {
		padding: '6px 12px',
		borderRadius: 6,
		border: `1px solid ${colors.border}`,
		background: colors.background,
		color: colors.text,
		cursor: 'pointer',
		fontSize: 12,
	};
}
