import React from 'react';

import type {AgentConsoleSnapshot} from '../shared/swarmConsoleState.js';
import {buttonStyle, cardStyle, colors, inputStyle, textareaStyle} from './swarmConsoleTheme.js';

type Props = {
	agent: AgentConsoleSnapshot;
	allAgentIds: string[];
	onSendMessage: (agentId: string, message: string) => void;
	onPauseAgent: (agentId: string) => void;
	onResumeAgent: (agentId: string) => void;
	onStopAgent: (agentId: string) => void;
	onSpawnAgent: (agentId: string, prompt: string, parentAgentId?: string, mode?: string) => void;
	onApplyContextPatch: (agentId: string, baseVersion: number, patch: Record<string, unknown>) => void;
	onAgentAction: (agentId: string, action: string, params: Record<string, unknown>) => void;
	onReparentAgent: (agentId: string, newParentAgentId?: string) => void;
	onRemoveAgent: (agentId: string) => void;
};

export function AgentControlsPanel({
	agent,
	allAgentIds,
	onSendMessage,
	onPauseAgent,
	onResumeAgent,
	onStopAgent,
	onSpawnAgent,
	onApplyContextPatch,
	onAgentAction,
	onReparentAgent,
	onRemoveAgent,
}: Props): React.JSX.Element {
	const [message, setMessage] = React.useState('');
	const [spawnAgentId, setSpawnAgentId] = React.useState('');
	const [spawnPrompt, setSpawnPrompt] = React.useState('');
	const [spawnMode, setSpawnMode] = React.useState<'synthetic' | 'live'>('live');
	const [contextVersion, setContextVersion] = React.useState(String(agent.context_version ?? 1));
	const [contextPrompt, setContextPrompt] = React.useState(agent.prompt ?? '');
	const [operationParams, setOperationParams] = React.useState(
		'{"tool_name":"brief","tool_input":{"text":"hello world","max_chars":80}}',
	);
	const [newParentId, setNewParentId] = React.useState('');
	const [operationError, setOperationError] = React.useState<string | null>(null);

	React.useEffect(() => {
		setMessage('');
		setSpawnAgentId('');
		setSpawnPrompt('');
		setContextVersion(String(agent.context_version ?? 1));
		setContextPrompt(agent.prompt ?? '');
		setNewParentId(agent.parent_agent_id ?? '');
		setOperationError(null);
	}, [agent.agent_id, agent.context_version, agent.parent_agent_id, agent.prompt]);

	return (
		<div
			style={{
				...cardStyle,
				padding: 18,
				display: 'grid',
				gap: 12,
			}}
		>
			<div>
				<h3 style={{margin: 0}}>Controls</h3>
				<div style={{marginTop: 6, color: colors.textMuted, fontSize: 12}}>
					所有操作都作用于当前选中的 agent：{agent.agent_id}
				</div>
			</div>

			<section style={sectionStyle}>
				<div style={sectionHeaderStyle}>Message Composer</div>
				<textarea
					value={message}
					onChange={(event) => setMessage(event.target.value)}
					placeholder="给这个 agent 的下一轮输入"
					style={textareaStyle}
				/>
				<div style={{display: 'flex', gap: 10, flexWrap: 'wrap'}}>
					<button type="button" style={buttonStyle} onClick={() => onSendMessage(agent.agent_id, message)}>
						Send Follow-up
					</button>
					<button type="button" style={buttonStyle} onClick={() => onPauseAgent(agent.agent_id)}>
						Pause
					</button>
					<button type="button" style={buttonStyle} onClick={() => onResumeAgent(agent.agent_id)}>
						Resume
					</button>
					<button type="button" style={{...buttonStyle, color: colors.danger}} onClick={() => onStopAgent(agent.agent_id)}>
						Stop
					</button>
				</div>
			</section>

			<details open style={sectionStyle}>
				<summary style={sectionHeaderStyle}>Spawn Child</summary>
				<div style={detailsBodyStyle}>
					<div style={{fontSize: 12, color: colors.textMuted, lineHeight: 1.45}}>
						Web Spawn Child creates a live persistent child so you can revisit it in the tree and send follow-up
						messages later. Oneshot agents created elsewhere run once and disappear after finishing.
					</div>
					<input
						value={spawnAgentId}
						onChange={(event) => setSpawnAgentId(event.target.value)}
						placeholder="new child agent id"
						style={inputStyle}
					/>
					<textarea
						value={spawnPrompt}
						onChange={(event) => setSpawnPrompt(event.target.value)}
						placeholder="child prompt"
						style={textareaStyle}
					/>
					<div style={{display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center'}}>
						<select
							value={spawnMode}
							onChange={(event) => setSpawnMode(event.target.value as 'synthetic' | 'live')}
							style={{...inputStyle, width: 160}}
						>
							<option value="live">live child</option>
							<option value="synthetic">synthetic child</option>
						</select>
						<button
							type="button"
							style={buttonStyle}
							disabled={!spawnAgentId.trim()}
							onClick={() => onSpawnAgent(spawnAgentId, spawnPrompt, agent.agent_id, spawnMode)}
						>
							Spawn Child
						</button>
					</div>
				</div>
			</details>

			<details style={sectionStyle}>
				<summary style={sectionHeaderStyle}>Context Patch</summary>
				<div style={detailsBodyStyle}>
					<input
						value={contextVersion}
						onChange={(event) => setContextVersion(event.target.value)}
						placeholder="base version"
						style={inputStyle}
					/>
					<textarea
						value={contextPrompt}
						onChange={(event) => setContextPrompt(event.target.value)}
						placeholder="patched prompt"
						style={textareaStyle}
					/>
					<button
						type="button"
						style={buttonStyle}
						onClick={() => onApplyContextPatch(agent.agent_id, Number(contextVersion), {prompt: contextPrompt})}
					>
						Apply Prompt Patch
					</button>
				</div>
			</details>

			<details style={sectionStyle}>
				<summary style={sectionHeaderStyle}>Run Tool</summary>
				<div style={detailsBodyStyle}>
					<textarea
						value={operationParams}
						onChange={(event) => setOperationParams(event.target.value)}
						placeholder='{"tool_name":"brief","tool_input":{"text":"hello"}}'
						style={textareaStyle}
					/>
					{operationError ? <div style={{fontSize: 12, color: colors.danger}}>{operationError}</div> : null}
					<button
						type="button"
						style={buttonStyle}
						onClick={() => {
							try {
								const parsed = JSON.parse(operationParams) as Record<string, unknown>;
								setOperationError(null);
								onAgentAction(agent.agent_id, 'run_tool', parsed);
							} catch {
								setOperationError('Tool params must be valid JSON before running.');
							}
						}}
					>
						Run Tool
					</button>
				</div>
			</details>

			<details style={sectionStyle}>
				<summary style={sectionHeaderStyle}>Topology</summary>
				<div style={detailsBodyStyle}>
					<select value={newParentId} onChange={(event) => setNewParentId(event.target.value)} style={inputStyle}>
						<option value="">make root</option>
						{allAgentIds
							.filter((candidate) => candidate !== agent.agent_id)
							.map((candidate) => (
								<option key={candidate} value={candidate}>
									{candidate}
								</option>
							))}
					</select>
					<div style={{display: 'flex', gap: 10, flexWrap: 'wrap'}}>
						<button type="button" style={buttonStyle} onClick={() => onReparentAgent(agent.agent_id, newParentId || undefined)}>
							Reparent
						</button>
						<button type="button" style={{...buttonStyle, color: colors.danger}} onClick={() => onRemoveAgent(agent.agent_id)}>
							Remove Agent
						</button>
					</div>
				</div>
			</details>
		</div>
	);
}

const sectionStyle: React.CSSProperties = {
	border: `1px solid ${colors.border}`,
	borderRadius: 14,
	padding: 12,
	background: colors.panelMuted,
};

const sectionHeaderStyle: React.CSSProperties = {
	cursor: 'pointer',
	fontWeight: 700,
};

const detailsBodyStyle: React.CSSProperties = {
	display: 'grid',
	gap: 10,
	marginTop: 12,
};
