import React from 'react';

import type {AgentConsoleSnapshot} from '../shared/swarmConsoleState.js';
import type {ReplSessionState} from '../shared/replSession.js';
import type {SwarmConsoleCommand} from '../shared/swarmConsoleProtocol.js';
import {AgentTranscriptEntries} from './AgentTranscriptView.js';
import {colors} from './swarmConsoleTheme.js';

type Props = {
	ohRepl: ReplSessionState;
	sendCommand: (message: SwarmConsoleCommand) => void;
	selectedAgent: AgentConsoleSnapshot | null;
	onSendAgentMessage: (agentId: string, message: string) => void;
};

export function OhReplPanel({ohRepl, sendCommand, selectedAgent, onSendAgentMessage}: Props): React.JSX.Element {
	const [draft, setDraft] = React.useState('');
	const scrollRef = React.useRef<HTMLDivElement>(null);
	const isMainSession =
		!selectedAgent ||
		selectedAgent.backend_type === 'openharness_repl' ||
		selectedAgent.spawn_mode === 'interactive';
	const sessionTitle = isMainSession ? 'OpenHarness session' : `${selectedAgent.agent_id} session`;
	const sessionPlaceholder = isMainSession
		? 'Message OpenHarness…'
		: `Message ${selectedAgent.agent_id}…`;
	const isAgentInputDisabled = !isMainSession && (!selectedAgent || selectedAgent.status === 'finished');

	React.useEffect(() => {
		const el = scrollRef.current;
		if (el) {
			el.scrollTop = el.scrollHeight;
		}
	}, [ohRepl.transcript, ohRepl.assistantBuffer, selectedAgent]);

	const submit = () => {
		const line = draft.trim();
		if (!line || (isMainSession ? ohRepl.busy : isAgentInputDisabled)) {
			return;
		}
		if (isMainSession) {
			sendCommand({
				type: 'command',
				command: 'oh_submit_line',
				payload: {line, client_id: 'web'},
			});
		} else if (selectedAgent) {
			onSendAgentMessage(selectedAgent.agent_id, line);
		}
		setDraft('');
	};

	const modal = ohRepl.modal;
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
			}}
		>
			<div style={{fontSize: 12, fontWeight: 600, color: colors.textMuted, letterSpacing: '0.04em'}}>
				{sessionTitle}
			</div>
			<div
				ref={scrollRef}
				style={{
					flex: 1,
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
						{ohRepl.transcript.map((row, i) => (
							<div key={i} style={{marginBottom: 4, opacity: row.role === 'system' ? 0.85 : 1}}>
								<span style={{color: colors.accent}}>{row.role}</span>
								{row.tool_name ? (
									<span style={{color: colors.textMuted}}>{` (${row.tool_name})`}</span>
								) : null}
								{`: ${row.text}`}
							</div>
						))}
						{ohRepl.assistantBuffer ? (
							<div>
								<span style={{color: colors.accent}}>assistant</span>
								{`: ${ohRepl.assistantBuffer}`}
							</div>
						) : null}
					</>
				) : (
					selectedAgent ? <AgentTranscriptEntries agent={selectedAgent} /> : <div style={{opacity: 0.85}}>No activity for this agent yet.</div>
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
								command: 'oh_permission_response',
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
								command: 'oh_permission_response',
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

			<div style={{display: 'flex', gap: 8, alignItems: 'center'}}>
				<input
					value={draft}
					onChange={(e) => setDraft(e.target.value)}
					onKeyDown={(e) => {
						if (e.key === 'Enter' && !e.shiftKey) {
							e.preventDefault();
							submit();
						}
					}}
					disabled={isMainSession ? ohRepl.busy : isAgentInputDisabled}
					placeholder={isMainSession && ohRepl.busy ? 'Busy…' : sessionPlaceholder}
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
				<button
					type="button"
					onClick={submit}
					disabled={(isMainSession ? ohRepl.busy : isAgentInputDisabled) || !draft.trim()}
					style={{
						...buttonStyle(),
						opacity: (isMainSession ? ohRepl.busy : isAgentInputDisabled) || !draft.trim() ? 0.5 : 1,
						borderColor: colors.accent,
						color: colors.accent,
					}}
				>
					Send
				</button>
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
						command: 'oh_question_response',
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
