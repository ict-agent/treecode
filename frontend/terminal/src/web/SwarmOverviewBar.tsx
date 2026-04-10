import React from 'react';

import type {SwarmConsoleState} from '../shared/swarmConsoleState.js';
import {buttonStyle, cardStyle, colors, inputStyle, statusColor} from './swarmConsoleTheme.js';

type Props = {
	state: SwarmConsoleState;
	onRunScenario: (name: string) => void;
	onSetActiveSource: (source: 'live' | 'scenario') => void;
	onSetTopologyView: (view: 'live' | 'raw_events') => void;
	onResolveApproval: (correlationId: string, status: string) => void;
	onCompareRuns: (leftRunId: string, rightRunId: string) => void;
	onArchiveRun: (label: string) => void;
};

export function SwarmOverviewBar({
	state,
	onRunScenario,
	onSetActiveSource,
	onSetTopologyView,
	onResolveApproval,
	onCompareRuns,
	onArchiveRun,
}: Props): React.JSX.Element {
	const snapshot = state.snapshot;
	const [leftRun, setLeftRun] = React.useState('');
	const [rightRun, setRightRun] = React.useState('');
	const [archiveLabel, setArchiveLabel] = React.useState('');

	if (!snapshot) {
		return <></>;
	}
	const topologyView = state.topology_view ?? snapshot.topology_view ?? 'live';
	const availableTopologyViews = state.available_topology_views ?? snapshot.available_topology_views ?? [];

	const badgeStyle = (accent?: string): React.CSSProperties => ({
		display: 'inline-flex',
		alignItems: 'center',
		gap: 6,
		padding: '6px 10px',
		borderRadius: 999,
		border: `1px solid ${accent ?? colors.borderStrong}`,
		background: accent ? 'rgba(15, 23, 42, 0.55)' : colors.panelMuted,
		color: colors.text,
		fontSize: 12,
	});

	return (
		<div
			style={{
				...cardStyle,
				margin: 18,
				marginBottom: 0,
				padding: 18,
				display: 'grid',
				gridTemplateColumns: 'minmax(0, 1.5fr) minmax(0, 1fr)',
				gap: 16,
			}}
		>
			<div>
				<div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12}}>
					<div>
						<h1 style={{margin: 0, fontSize: 24}}>TreeCode Multi-Agent Console</h1>
						<div style={{marginTop: 6, color: colors.textMuted, fontSize: 13}}>
							以树导航 agent，以右侧时间线浏览当前 agent 的完整交互。
						</div>
					</div>
					<div style={{display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end'}}>
						<span style={badgeStyle()}>
							source
							<strong>{state.active_source ?? 'live'}</strong>
						</span>
						<span style={badgeStyle()}>
							topology
							<strong>{topologyView}</strong>
						</span>
						<span style={badgeStyle(statusColor(snapshot.overview.pending_approvals ? 'paused' : 'running'))}>
							approvals
							<strong>{snapshot.overview.pending_approvals}</strong>
						</span>
						<span style={badgeStyle()}>
							revision
							<strong>{snapshot.snapshot_revision ?? '—'}</strong>
						</span>
					</div>
				</div>

				<div style={{display: 'flex', gap: 10, marginTop: 16, flexWrap: 'wrap'}}>
					{state.available_sources?.includes('live') ? (
						<button
							type="button"
							style={{
								...buttonStyle,
								background: state.active_source === 'live' ? colors.accentSoft : colors.panelMuted,
								borderColor: state.active_source === 'live' ? colors.accent : colors.borderStrong,
							}}
							onClick={() => onSetActiveSource('live')}
						>
							Live
						</button>
					) : null}
					{state.available_sources?.includes('scenario') ? (
						<button
							type="button"
							style={{
								...buttonStyle,
								background: state.active_source === 'scenario' ? colors.accentSoft : colors.panelMuted,
								borderColor: state.active_source === 'scenario' ? colors.accent : colors.borderStrong,
							}}
							onClick={() => onSetActiveSource('scenario')}
						>
							Scenario
						</button>
					) : null}
					{availableTopologyViews.includes('live') ? (
						<button
							type="button"
							style={{
								...buttonStyle,
								background: topologyView === 'live' ? colors.accentSoft : colors.panelMuted,
								borderColor: topologyView === 'live' ? colors.accent : colors.borderStrong,
							}}
							onClick={() => onSetTopologyView('live')}
						>
							Live topology
						</button>
					) : null}
					{availableTopologyViews.includes('raw_events') ? (
						<button
							type="button"
							style={{
								...buttonStyle,
								background: topologyView === 'raw_events' ? colors.accentSoft : colors.panelMuted,
								borderColor: topologyView === 'raw_events' ? colors.accent : colors.borderStrong,
							}}
							onClick={() => onSetTopologyView('raw_events')}
						>
							Raw event topology
						</button>
					) : null}
					{['single_child', 'two_level_fanout', 'approval_on_leaf'].map((scenario) => (
						<button key={scenario} type="button" style={buttonStyle} onClick={() => onRunScenario(scenario)}>
							{scenario}
						</button>
					))}
				</div>

				<div
					style={{
						display: 'grid',
						gridTemplateColumns: 'repeat(5, minmax(0, 1fr))',
						gap: 12,
						marginTop: 16,
					}}
				>
					<MetricCard label="Agents" value={String(snapshot.overview.agent_count)} />
					<MetricCard label="Roots" value={String(snapshot.overview.root_count)} />
					<MetricCard label="Depth" value={String(snapshot.overview.max_depth)} />
					<MetricCard label="Messages" value={String(snapshot.overview.message_count)} />
					<MetricCard label="Leaves" value={snapshot.overview.leaf_agents.join(', ') || '—'} />
				</div>
			</div>

			<div style={{display: 'grid', gap: 12}}>
				<details
					open={snapshot.approval_queue.length > 0 || Boolean(state.lastError)}
					style={{
						border: `1px solid ${colors.borderStrong}`,
						borderRadius: 14,
						padding: 12,
						background: colors.panelMuted,
					}}
				>
					<summary style={{cursor: 'pointer', fontWeight: 700}}>Approvals & Global Feedback</summary>
					<div style={{display: 'grid', gap: 10, marginTop: 12}}>
						{snapshot.approval_queue.length === 0 ? (
							<div style={{color: colors.textMuted, fontSize: 13}}>No pending approvals.</div>
						) : (
							snapshot.approval_queue.map((item) => (
								<div
									key={String(item.correlation_id)}
									style={{
										border: `1px solid ${colors.border}`,
										borderRadius: 12,
										padding: 10,
										background: colors.panel,
									}}
								>
									<div style={{fontWeight: 700}}>{String(item.tool_name ?? 'approval')}</div>
									<div style={{fontSize: 12, color: colors.textMuted}}>
										{String(item.agent_id)} / {String(item.status)}
									</div>
									{item.status === 'pending' ? (
										<div style={{display: 'flex', gap: 8, marginTop: 8}}>
											<button
												type="button"
												style={{...buttonStyle, color: colors.success}}
												onClick={() => onResolveApproval(String(item.correlation_id), 'approved')}
											>
												Approve
											</button>
											<button
												type="button"
												style={{...buttonStyle, color: colors.danger}}
												onClick={() => onResolveApproval(String(item.correlation_id), 'rejected')}
											>
												Reject
											</button>
										</div>
									) : null}
								</div>
							))
						)}
						{state.lastAck ? <div style={feedbackBlockStyle}>Latest action: {summarizeAck(state.lastAck)}</div> : null}
						{state.lastError ? <div style={{...feedbackBlockStyle, color: colors.danger}}>{state.lastError}</div> : null}
					</div>
				</details>

				<details
					style={{
						border: `1px solid ${colors.borderStrong}`,
						borderRadius: 14,
						padding: 12,
						background: colors.panelMuted,
					}}
				>
					<summary style={{cursor: 'pointer', fontWeight: 700}}>Archives & Compare</summary>
					<div style={{display: 'grid', gap: 10, marginTop: 12}}>
						<input
							value={archiveLabel}
							onChange={(event) => setArchiveLabel(event.target.value)}
							placeholder="archive label"
							style={inputStyle}
						/>
						<button type="button" style={buttonStyle} onClick={() => onArchiveRun(archiveLabel)}>
							Archive Current Run
						</button>
						<div style={{display: 'grid', gap: 8}}>
							<input
								value={leftRun}
								onChange={(event) => setLeftRun(event.target.value)}
								placeholder="left run id"
								style={inputStyle}
							/>
							<input
								value={rightRun}
								onChange={(event) => setRightRun(event.target.value)}
								placeholder="right run id"
								style={inputStyle}
							/>
							<button type="button" style={buttonStyle} onClick={() => onCompareRuns(leftRun, rightRun)}>
								Compare Runs
							</button>
						</div>
						{snapshot.archives.length > 0 ? (
							<div style={{display: 'grid', gap: 6}}>
								{snapshot.archives.map((archive) => (
									<div key={String(archive.run_id)} style={{fontSize: 12, color: colors.textMuted}}>
										{String(archive.label)} ({String(archive.run_id)})
									</div>
								))}
							</div>
						) : null}
						{state.comparison ? <pre style={feedbackBlockStyle}>{JSON.stringify(state.comparison, null, 2)}</pre> : null}
					</div>
				</details>
			</div>
		</div>
	);
}

function MetricCard({label, value}: {label: string; value: string}): React.JSX.Element {
	return (
		<div
			style={{
				border: `1px solid ${colors.border}`,
				borderRadius: 14,
				padding: 12,
				background: colors.panelMuted,
			}}
		>
			<div style={{fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.7, color: colors.textSoft}}>{label}</div>
			<div style={{marginTop: 8, fontSize: 16, fontWeight: 700}}>{value || '—'}</div>
		</div>
	);
}

const feedbackBlockStyle: React.CSSProperties = {
	margin: 0,
	padding: 10,
	borderRadius: 12,
	border: `1px solid ${colors.border}`,
	background: colors.panel,
	fontSize: 12,
};

function summarizeAck(payload: Record<string, unknown>): string {
	const preferredKeys = ['scenario', 'agent_id', 'mode', 'status', 'tool_name', 'active_source', 'topology_view', 'removed'];
	const summary = preferredKeys
		.filter((key) => payload[key] !== undefined)
		.map((key) => `${key}=${String(payload[key])}`);
	if (summary.length > 0) {
		return summary.join(' · ');
	}
	const firstEntries = Object.entries(payload)
		.slice(0, 3)
		.map(([key, value]) => `${key}=${String(value)}`);
	return firstEntries.join(' · ') || 'ok';
}
