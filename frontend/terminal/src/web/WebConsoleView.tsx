import React from 'react';

import type {SwarmConsoleCommand} from '../shared/swarmConsoleProtocol.js';
import type {SwarmConsoleState} from '../shared/swarmConsoleState.js';
import {AgentDetailPanel} from './AgentDetailPanel.js';
import {AgentTreePanel} from './AgentTreePanel.js';
import {OhReplPanel} from './OhReplPanel.js';
import {SwarmOverviewBar} from './SwarmOverviewBar.js';
import {colors} from './swarmConsoleTheme.js';
import {useResizablePanel} from './useResizablePanel.js';

type Props = {
	state: SwarmConsoleState;
	/** When set, OpenHarness REPL panel is shown after the first ``repl_event`` from ``oh``. */
	sendCommand?: (message: SwarmConsoleCommand) => void;
	onRunScenario: (name: string) => void;
	onSetActiveSource: (source: 'live' | 'scenario') => void;
	onSetTopologyView: (view: 'live' | 'raw_events') => void;
	onResolveApproval: (correlationId: string, status: string) => void;
	onSendMessage: (agentId: string, message: string) => void;
	onCompareRuns: (leftRunId: string, rightRunId: string) => void;
	onArchiveRun: (label: string) => void;
	onSpawnAgent: (agentId: string, prompt: string, parentAgentId?: string, mode?: string) => void;
	onReparentAgent: (agentId: string, newParentAgentId?: string) => void;
	onRemoveAgent: (agentId: string) => void;
	onApplyContextPatch: (agentId: string, baseVersion: number, patch: Record<string, unknown>) => void;
	onPauseAgent: (agentId: string) => void;
	onResumeAgent: (agentId: string) => void;
	onStopAgent: (agentId: string) => void;
	onAgentAction: (agentId: string, action: string, params: Record<string, unknown>) => void;
};

export function WebConsoleView({
	state,
	sendCommand,
	onRunScenario,
	onSetActiveSource,
	onSetTopologyView,
	onResolveApproval,
	onSendMessage,
	onCompareRuns,
	onArchiveRun,
	onSpawnAgent,
	onReparentAgent,
	onRemoveAgent,
	onApplyContextPatch,
	onPauseAgent,
	onResumeAgent,
	onStopAgent,
	onAgentAction,
}: Props): React.JSX.Element {
	const snapshot = state.snapshot;
	const showOhPanel = Boolean(sendCommand && state.ohSessionAttached);
	const {containerRef, ratio, beginResize, panelWidthPx} = useResizablePanel({
		storageKey: 'openharness:swarm-console:left-panel-ratio',
		initialRatio: 0.38,
		minRatio: 0.24,
		maxRatio: 0.62,
	});
	const [selectedAgentId, setSelectedAgentId] = React.useState('');
	const [expandedAgentIds, setExpandedAgentIds] = React.useState<Set<string>>(new Set());
	const [pendingSelectedAgentId, setPendingSelectedAgentId] = React.useState<string | null>(null);
	const initializedRootExpansionRef = React.useRef(false);

	const knownAgentIds = React.useMemo(() => {
		if (!snapshot) {
			return [];
		}
		return Object.keys(snapshot.tree.nodes).sort((a, b) => a.localeCompare(b));
	}, [snapshot]);

	React.useEffect(() => {
		if (!snapshot) {
			return;
		}
		if (!selectedAgentId || !snapshot.agents[selectedAgentId]) {
			setPendingSelectedAgentId(null);
			setSelectedAgentId(state.ohRepl.selectedAgentId ?? snapshot.tree.roots[0] ?? knownAgentIds[0] ?? '');
		}
		setExpandedAgentIds((previous) => {
			if (initializedRootExpansionRef.current) {
				return previous;
			}
			const next = new Set(previous);
			for (const root of snapshot.tree.roots) {
				next.add(root);
			}
			initializedRootExpansionRef.current = true;
			return next;
		});
	}, [knownAgentIds, selectedAgentId, snapshot, state.ohRepl.selectedAgentId]);

	React.useEffect(() => {
		const sharedSelected = state.ohRepl.selectedAgentId;
		if (!snapshot || !sharedSelected || !snapshot.agents[sharedSelected]) {
			return;
		}
		if (pendingSelectedAgentId) {
			if (sharedSelected === pendingSelectedAgentId) {
				setPendingSelectedAgentId(null);
			} else {
				return;
			}
		}
		if (sharedSelected !== selectedAgentId) {
			setSelectedAgentId(sharedSelected);
		}
	}, [pendingSelectedAgentId, selectedAgentId, snapshot, state.ohRepl.selectedAgentId]);

	React.useEffect(() => {
		if (!snapshot || !selectedAgentId || !snapshot.tree.nodes[selectedAgentId]) {
			return;
		}
		setExpandedAgentIds((previous) => {
			const next = new Set(previous);
			let changed = false;
			for (const item of snapshot.tree.nodes[selectedAgentId].lineage_path.slice(0, -1)) {
				if (!next.has(item)) {
					next.add(item);
					changed = true;
				}
			}
			return changed ? next : previous;
		});
	}, [selectedAgentId, snapshot]);

	const handleSelectAgent = React.useCallback(
		(agentId: string) => {
			setSelectedAgentId(agentId);
			if (sendCommand && state.ohSessionAttached) {
				setPendingSelectedAgentId(agentId);
				sendCommand({
					type: 'command',
					command: 'oh_set_selected_agent',
					payload: {agent_id: agentId, client_id: 'web'},
				});
			}
		},
		[sendCommand, state.ohSessionAttached],
	);

	if (!snapshot) {
		return (
			<div
				style={{
					minHeight: '100vh',
					display: 'grid',
					placeItems: 'center',
					background: colors.background,
					color: colors.text,
				}}
			>
				<div style={{textAlign: 'center'}}>
					<h1 style={{marginBottom: 8}}>OpenHarness Multi-Agent Console</h1>
					<p style={{margin: 0, color: colors.textMuted}}>Waiting for swarm snapshot...</p>
				</div>
			</div>
		);
	}

	const selectedAgent = snapshot.agents[selectedAgentId] ?? null;

	return (
		<div style={{minHeight: '100vh', background: colors.background, color: colors.text}}>
			<SwarmOverviewBar
				state={state}
				onRunScenario={onRunScenario}
				onSetActiveSource={onSetActiveSource}
				onSetTopologyView={onSetTopologyView}
				onResolveApproval={onResolveApproval}
				onCompareRuns={onCompareRuns}
				onArchiveRun={onArchiveRun}
			/>

			{showOhPanel && sendCommand ? (
				<OhReplPanel
					ohRepl={state.ohRepl}
					sendCommand={sendCommand}
					selectedAgent={selectedAgent}
					onSendAgentMessage={onSendMessage}
				/>
			) : null}

			<div
				ref={containerRef}
				style={{
					display: 'flex',
					minHeight: showOhPanel ? 'calc(100vh - 170px - 200px)' : 'calc(100vh - 170px)',
					padding: 18,
					gap: 0,
					overflow: 'hidden',
				}}
			>
				<div
					style={{
						width: panelWidthPx ? `${panelWidthPx}px` : `${ratio * 100}%`,
						minWidth: 0,
						minHeight: 0,
						flexShrink: 0,
					}}
				>
					<AgentTreePanel
						snapshot={snapshot}
						selectedAgentId={selectedAgentId}
						expandedAgentIds={expandedAgentIds}
						onSelectAgent={handleSelectAgent}
						onToggleAgent={(agentId) =>
							setExpandedAgentIds((previous) => {
								const next = new Set(previous);
								if (next.has(agentId)) {
									next.delete(agentId);
								} else {
									next.add(agentId);
								}
								return next;
							})
						}
					/>
				</div>

				<div
					onMouseDown={beginResize}
					role="separator"
					aria-orientation="vertical"
					title="Drag to resize panels"
					style={{
						width: 16,
						display: 'flex',
						alignItems: 'stretch',
						justifyContent: 'center',
						cursor: 'col-resize',
						padding: '0 4px',
					}}
				>
					<div
						style={{
							width: 6,
							borderRadius: 999,
							background: `linear-gradient(180deg, ${colors.borderStrong} 0%, ${colors.accent} 50%, ${colors.borderStrong} 100%)`,
							opacity: 0.9,
						}}
					/>
				</div>

				<div style={{flex: 1, minWidth: 280, minHeight: 0, overflow: 'hidden'}}>
					<AgentDetailPanel
						agent={selectedAgent}
						allAgentIds={knownAgentIds}
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
			</div>
		</div>
	);
}
