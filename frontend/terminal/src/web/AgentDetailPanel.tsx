import React from 'react';

import type {AgentConsoleSnapshot} from '../shared/swarmConsoleState.js';
import {AgentControlsPanel} from './AgentControlsPanel.js';
import {AgentTranscriptView} from './AgentTranscriptView.js';
import {cardStyle, colors, statusColor} from './swarmConsoleTheme.js';

type Props = {
	agent: AgentConsoleSnapshot | null;
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

export function AgentDetailPanel({
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
	if (!agent) {
		return (
			<div
				style={{
					...cardStyle,
					height: '100%',
					padding: 24,
					display: 'grid',
					placeItems: 'center',
					color: colors.textMuted,
				}}
			>
				Select an agent from the tree to inspect its transcript and controls.
			</div>
		);
	}

	return (
		<div style={{display: 'grid', gridTemplateRows: 'auto minmax(0, 1fr) auto', gap: 16, height: '100%'}}>
			<AgentSummaryCard agent={agent} />
			<AgentTranscriptView agent={agent} />
			<AgentControlsPanel
				agent={agent}
				allAgentIds={allAgentIds}
				onSendMessage={onSendMessage}
				onPauseAgent={onPauseAgent}
				onResumeAgent={onResumeAgent}
				onStopAgent={onStopAgent}
				onSpawnAgent={onSpawnAgent}
				onApplyContextPatch={onApplyContextPatch}
				onAgentAction={onAgentAction}
				onReparentAgent={onReparentAgent}
				onRemoveAgent={onRemoveAgent}
			/>
		</div>
	);
}

function AgentSummaryCard({agent}: {agent: AgentConsoleSnapshot}): React.JSX.Element {
	const summaryItem = (label: string, value: string | number | null | undefined) => (
		<div
			style={{
				padding: 12,
				borderRadius: 14,
				border: `1px solid ${colors.border}`,
				background: colors.panelMuted,
			}}
		>
			<div style={{fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.6, color: colors.textSoft}}>{label}</div>
			<div style={{marginTop: 8, lineHeight: 1.4}}>{value || '—'}</div>
		</div>
	);

	return (
		<div style={{...cardStyle, padding: 18}}>
			<div style={{display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'center'}}>
				<div>
					<div style={{display: 'flex', alignItems: 'center', gap: 10}}>
						<h2 style={{margin: 0}}>{agent.agent_id}</h2>
						<span style={{fontSize: 12, color: statusColor(agent.status)}}>{agent.status}</span>
					</div>
					<div style={{marginTop: 6, color: colors.textMuted, fontSize: 13}}>
						{agent.name}@{agent.team} · {agent.backend_type ?? (agent.synthetic ? 'synthetic' : 'unknown')} ·{' '}
						{agent.spawn_mode ?? '—'}
					</div>
				</div>
				<div style={{fontSize: 12, color: colors.textSoft}}>
					{agent.messages_received} incoming / {agent.messages_sent} outgoing
				</div>
			</div>

			<div
				style={{
					display: 'grid',
					gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
					gap: 12,
					marginTop: 16,
				}}
			>
				{summaryItem('Parent', agent.parent_agent_id)}
				{summaryItem('Children', agent.children.join(', '))}
				{summaryItem('Context Version', agent.context_version)}
				{summaryItem('Scenario', agent.scenario_name)}
			</div>

			{agent.prompt ? (
				<div
					style={{
						marginTop: 14,
						padding: 14,
						borderRadius: 14,
						border: `1px solid ${colors.border}`,
						background: colors.panelMuted,
					}}
				>
					<div style={{fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.6, color: colors.textSoft}}>
						Task Prompt
					</div>
					<div style={{marginTop: 8, whiteSpace: 'pre-wrap', lineHeight: 1.45}}>{agent.prompt}</div>
				</div>
			) : null}

			{agent.spawn_mode === 'oneshot' ? (
				<div
					style={{
						marginTop: 14,
						padding: 14,
						borderRadius: 14,
						border: `1px solid ${colors.warning}`,
						background: 'rgba(251, 191, 36, 0.08)',
						color: colors.text,
					}}
				>
					<div style={{fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.6, color: colors.warning}}>
						Oneshot agent
					</div>
					<div style={{marginTop: 8, lineHeight: 1.45}}>
						Runs once and disappears from the live tree after finishing. Use a persistent agent when you want to
						switch back later or send follow-up messages.
					</div>
				</div>
			) : null}
		</div>
	);
}
