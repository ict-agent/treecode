import React from 'react';

import type {AgentConsoleSnapshot, AgentFeedItem} from '../shared/swarmConsoleState.js';
import {cardStyle, colors, formatConsoleTime} from './swarmConsoleTheme.js';

type Props = {
	agent: AgentConsoleSnapshot;
};

export function AgentTranscriptView({agent}: Props): React.JSX.Element {
	const feed = Array.isArray(agent.feed) ? agent.feed : [];
	const fallbackMessages = Array.isArray(agent.messages) ? agent.messages : [];

	return (
		<div
			style={{
				...cardStyle,
				padding: 18,
				display: 'flex',
				flexDirection: 'column',
				minHeight: 0,
			}}
		>
			<div style={{display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline'}}>
				<div>
					<h3 style={{margin: 0}}>Conversation</h3>
					<div style={{marginTop: 6, color: colors.textMuted, fontSize: 12}}>
						当前只展示 {agent.agent_id} 的相关消息、工具与运行事件。
					</div>
				</div>
				<div style={{fontSize: 12, color: colors.textSoft}}>
					{feed.length > 0 ? `${feed.length} items` : `${fallbackMessages.length} context messages`}
				</div>
			</div>

			<AgentTranscriptEntries agent={agent} />
		</div>
	);
}

export function AgentTranscriptEntries({agent}: {agent: AgentConsoleSnapshot}): React.JSX.Element {
	const feed = Array.isArray(agent.feed) ? agent.feed : [];
	const fallbackMessages = Array.isArray(agent.messages) ? agent.messages : [];

	return (
		<div style={{marginTop: 18, display: 'grid', gap: 12, overflow: 'auto', minHeight: 0, paddingRight: 4}}>
			{feed.length === 0 && fallbackMessages.length === 0 ? (
				<div style={{color: colors.textMuted, fontSize: 13}}>No activity for this agent yet.</div>
			) : (
				<>
					{feed.map((item) => (
						<FeedCard key={item.item_id} item={item} />
					))}
					{feed.length === 0
						? fallbackMessages.map((message, index) => (
								<div
									key={`fallback-${agent.agent_id}-${index}`}
									style={{
										borderRadius: 16,
										border: `1px solid ${colors.borderStrong}`,
										background: colors.panelMuted,
										padding: 14,
										whiteSpace: 'pre-wrap',
										wordBreak: 'break-word',
										lineHeight: 1.5,
									}}
								>
									{message}
								</div>
							))
						: null}
				</>
			)}
		</div>
	);
}

function FeedCard({item}: {item: AgentFeedItem}): React.JSX.Element {
	const tone = feedTone(item);
	return (
		<div
			style={{
				borderRadius: 16,
				border: `1px solid ${tone.border}`,
				background: tone.background,
				padding: 14,
			}}
		>
			<div style={{display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center'}}>
				<div style={{display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap'}}>
					<span
						style={{
							padding: '4px 8px',
							borderRadius: 999,
							border: `1px solid ${tone.border}`,
							fontSize: 11,
							textTransform: 'uppercase',
							letterSpacing: 0.5,
						}}
					>
						{item.item_type.replace('_', ' ')}
					</span>
					{item.label ? <strong>{item.label}</strong> : null}
					{item.tool_name ? <span style={{color: colors.textMuted}}>{item.tool_name}</span> : null}
				</div>
				<div style={{fontSize: 11, color: colors.textSoft}}>{formatConsoleTime(item.timestamp)}</div>
			</div>

			{item.text ? (
				<div style={{marginTop: 10, whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.5}}>
					{item.text}
				</div>
			) : null}

			{item.tool_input && Object.keys(item.tool_input).length > 0 ? (
				<pre
					style={{
						marginTop: 10,
						padding: 10,
						borderRadius: 12,
						background: colors.panelMuted,
						border: `1px solid ${colors.border}`,
						overflow: 'auto',
						fontSize: 12,
					}}
				>
					{JSON.stringify(item.tool_input, null, 2)}
				</pre>
			) : null}

			<div style={{display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 10, fontSize: 12, color: colors.textMuted}}>
				{item.actor ? <span>actor: {item.actor}</span> : null}
				{item.status ? <span>status: {item.status}</span> : null}
				{item.correlation_id ? <span>id: {item.correlation_id}</span> : null}
				{item.message_count !== undefined ? <span>messages: {item.message_count}</span> : null}
				{item.is_error ? <span style={{color: colors.danger}}>error</span> : null}
			</div>
		</div>
	);
}

function feedTone(item: AgentFeedItem): {border: string; background: string} {
	switch (item.item_type) {
		case 'incoming':
		case 'prompt':
			return {border: colors.accent, background: 'rgba(14, 165, 233, 0.08)'};
		case 'outgoing':
			return {border: colors.warning, background: 'rgba(251, 191, 36, 0.08)'};
		case 'assistant':
			return {border: colors.success, background: 'rgba(52, 211, 153, 0.08)'};
		case 'tool_call':
		case 'tool_result':
			return {border: colors.purple, background: 'rgba(192, 132, 252, 0.08)'};
		case 'approval_request':
		case 'approval_result':
			return {border: colors.warning, background: 'rgba(251, 191, 36, 0.08)'};
		case 'lifecycle':
		case 'turn_marker':
		case 'context':
		default:
			return {border: colors.borderStrong, background: colors.panelMuted};
	}
}
