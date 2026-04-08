import React from 'react';

import type {SwarmConsoleSnapshot} from '../shared/swarmConsoleState.js';
import {cardStyle, colors, statusColor} from './swarmConsoleTheme.js';

type Props = {
	snapshot: SwarmConsoleSnapshot;
	selectedAgentId: string;
	expandedAgentIds: Set<string>;
	onSelectAgent: (agentId: string) => void;
	onToggleAgent: (agentId: string) => void;
};

export function AgentTreePanel({
	snapshot,
	selectedAgentId,
	expandedAgentIds,
	onSelectAgent,
	onToggleAgent,
}: Props): React.JSX.Element {
	return (
		<div
			style={{
				...cardStyle,
				height: '100%',
				padding: 18,
				display: 'flex',
				flexDirection: 'column',
				minHeight: 0,
			}}
		>
			<div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12}}>
				<div>
					<h2 style={{margin: 0, fontSize: 18}}>Agent Tree</h2>
					<div style={{marginTop: 6, color: colors.textMuted, fontSize: 12}}>
						点击圆形节点切换当前 agent，展开后查看其子树。
					</div>
				</div>
				<div
					style={{
						padding: '6px 10px',
						borderRadius: 999,
						border: `1px solid ${colors.borderStrong}`,
						fontSize: 12,
						color: colors.textMuted,
					}}
				>
					{snapshot.overview.agent_count} agents
				</div>
			</div>

			<div style={{marginTop: 18, overflow: 'auto', minHeight: 0, paddingRight: 4}}>
				{snapshot.tree.roots.map((root) => (
					<TreeBranch
						key={root}
						agentId={root}
						depth={0}
						snapshot={snapshot}
						selectedAgentId={selectedAgentId}
						expandedAgentIds={expandedAgentIds}
						onSelectAgent={onSelectAgent}
						onToggleAgent={onToggleAgent}
					/>
				))}
			</div>
		</div>
	);
}

function TreeBranch({
	agentId,
	depth,
	snapshot,
	selectedAgentId,
	expandedAgentIds,
	onSelectAgent,
	onToggleAgent,
}: {
	agentId: string;
	depth: number;
	snapshot: SwarmConsoleSnapshot;
	selectedAgentId: string;
	expandedAgentIds: Set<string>;
	onSelectAgent: (agentId: string) => void;
	onToggleAgent: (agentId: string) => void;
}): React.JSX.Element {
	const node = snapshot.tree.nodes[agentId];
	const agent = snapshot.agents[agentId];

	if (!node || !agent) {
		return <></>;
	}

	const isSelected = selectedAgentId === agentId;
	const isExpanded = expandedAgentIds.has(agentId);
	const hasChildren = node.children.length > 0;
	// Derive initials from canonical agent_id (name@team), not AgentTool's subagent_type default "agent",
	// so we do not show a misleading "A" when the id is actually agent@default.
	const idBase = (agent.agent_id.split('@')[0] || agent.name || '').trim();
	const compact = idBase.replace(/[^a-zA-Z0-9]/g, '');
	const circleLabel =
		compact.length >= 2
			? compact.slice(0, 2).toUpperCase()
			: compact.length === 1
				? `${compact[0]!.toUpperCase()}${(agent.agent_id.split('@')[1] || '')[0]?.toUpperCase() || ''}`.slice(
						0,
						2,
					) || compact[0]!.toUpperCase()
				: (idBase.slice(0, 2) || agent.name.slice(0, 2)).toUpperCase();

	return (
		<div style={{marginLeft: depth === 0 ? 0 : 18, position: 'relative'}}>
			<div style={{display: 'flex', alignItems: 'center', gap: 10, marginTop: depth === 0 ? 0 : 14}}>
				<button
					type="button"
					onClick={() => onToggleAgent(agentId)}
					disabled={!hasChildren}
					aria-label={hasChildren ? `${isExpanded ? 'Collapse' : 'Expand'} ${agentId}` : `No children for ${agentId}`}
					style={{
						width: 22,
						height: 22,
						borderRadius: 999,
						border: `1px solid ${hasChildren ? colors.borderStrong : colors.border}`,
						background: colors.panelMuted,
						color: hasChildren ? colors.text : colors.textSoft,
						cursor: hasChildren ? 'pointer' : 'default',
						fontSize: 12,
					}}
				>
					{hasChildren ? (isExpanded ? '−' : '+') : '·'}
				</button>

				<div
					onClick={() => onSelectAgent(agentId)}
					role="button"
					tabIndex={0}
					onKeyDown={(event) => {
						if (event.key === 'Enter' || event.key === ' ') {
							event.preventDefault();
							onSelectAgent(agentId);
						}
					}}
					style={{
						display: 'flex',
						alignItems: 'center',
						gap: 12,
						padding: '10px 12px',
						borderRadius: 16,
						border: `1px solid ${isSelected ? colors.accent : colors.border}`,
						background: isSelected ? colors.accentSoft : colors.panelMuted,
						cursor: 'pointer',
						flex: 1,
						minWidth: 0,
					}}
				>
					<div
						title={agent.status}
						style={{
							width: 54,
							height: 54,
							borderRadius: '50%',
							display: 'grid',
							placeItems: 'center',
							border: `2px solid ${statusColor(agent.status)}`,
							background: 'rgba(15, 23, 42, 0.9)',
							boxShadow: isSelected ? `0 0 0 5px ${colors.accentSoft}` : 'none',
							flexShrink: 0,
						}}
					>
							<div style={{fontWeight: 800, fontSize: 14, textAlign: 'center', lineHeight: 1.15}}>{circleLabel}</div>
					</div>
					<div style={{minWidth: 0}}>
						<div style={{display: 'flex', alignItems: 'center', gap: 8, minWidth: 0}}>
							<strong style={{whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>
								{agent.agent_id}
							</strong>
							<span style={{fontSize: 11, color: statusColor(agent.status)}}>{agent.status}</span>
						</div>
						<div style={{fontSize: 12, color: colors.textMuted, marginTop: 4}}>
							{agent.backend_type ?? (agent.synthetic ? 'synthetic' : 'unknown')} / {agent.spawn_mode ?? '—'}
						</div>
						<div style={{fontSize: 12, color: colors.textSoft, marginTop: 4}}>
							{agent.messages_received} in · {agent.messages_sent} out · {node.children.length} children
						</div>
					</div>
				</div>
			</div>

			{hasChildren && isExpanded ? (
				<div
					style={{
						marginLeft: 10,
						paddingLeft: 22,
						borderLeft: `1px solid ${colors.borderStrong}`,
					}}
				>
					{node.children.map((child) => (
						<TreeBranch
							key={child}
							agentId={child}
							depth={depth + 1}
							snapshot={snapshot}
							selectedAgentId={selectedAgentId}
							expandedAgentIds={expandedAgentIds}
							onSelectAgent={onSelectAgent}
							onToggleAgent={onToggleAgent}
						/>
					))}
				</div>
			) : null}
		</div>
	);
}
