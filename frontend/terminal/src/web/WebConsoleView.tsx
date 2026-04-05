import React from 'react';

import type {SwarmConsoleState} from '../shared/swarmConsoleState.js';

type Props = {
	state: SwarmConsoleState;
	onRunScenario: (name: string) => void;
	onSetActiveSource: (source: 'live' | 'scenario') => void;
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
	onRunScenario,
	onSetActiveSource,
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
	const [targetAgent, setTargetAgent] = React.useState('');
	const [message, setMessage] = React.useState('');
	const [leftRun, setLeftRun] = React.useState('');
	const [rightRun, setRightRun] = React.useState('');
	const [archiveLabel, setArchiveLabel] = React.useState('');
	const [spawnAgentId, setSpawnAgentId] = React.useState('');
	const [spawnParentId, setSpawnParentId] = React.useState('');
	const [spawnPrompt, setSpawnPrompt] = React.useState('');
	const [topologyAgentId, setTopologyAgentId] = React.useState('');
	const [newParentId, setNewParentId] = React.useState('');
	const [contextAgentId, setContextAgentId] = React.useState('');
	const [contextVersion, setContextVersion] = React.useState('1');
	const [contextPrompt, setContextPrompt] = React.useState('');
	const [operationAgentId, setOperationAgentId] = React.useState('');
	const [operationName, setOperationName] = React.useState('inspect');
	const [operationParams, setOperationParams] = React.useState('{}');

	if (!snapshot) {
		return (
			<div style={{padding: 16}}>
				<h1>OpenHarness Multi-Agent Console</h1>
				<p>Waiting for swarm snapshot...</p>
			</div>
		);
	}

	return (
		<div style={{display: 'grid', gridTemplateColumns: '280px 1fr 360px', minHeight: '100vh', background: '#0f172a', color: '#e2e8f0'}}>
			<section style={{padding: 16, borderRight: '1px solid #334155'}}>
				<h2>Overview</h2>
				<div style={{display: 'flex', gap: 8, marginBottom: 12}}>
					{state.available_sources?.includes('live') ? (
						<button onClick={() => onSetActiveSource('live')}>Live Source</button>
					) : null}
					{state.available_sources?.includes('scenario') ? (
						<button onClick={() => onSetActiveSource('scenario')}>Scenario Source</button>
					) : null}
				</div>
				<div>Agents: {snapshot.overview.agent_count}</div>
				<div>Roots: {snapshot.overview.root_count}</div>
				<div>Depth: {snapshot.overview.max_depth}</div>
				<div>Messages: {snapshot.overview.message_count}</div>
				<div>Leaf agents: {snapshot.overview.leaf_agents.join(', ')}</div>

				<h2 style={{marginTop: 24}}>Scenarios</h2>
				<div style={{display: 'flex', gap: 8, flexWrap: 'wrap'}}>
					<button onClick={() => onRunScenario('single_child')}>single_child</button>
					<button onClick={() => onRunScenario('two_level_fanout')}>two_level_fanout</button>
					<button onClick={() => onRunScenario('approval_on_leaf')}>approval_on_leaf</button>
				</div>

				<h2 style={{marginTop: 24}}>Scenario View</h2>
				<div>Active source: {state.active_source ?? 'live'}</div>
				<div>{snapshot.scenario_view.scenario_name ?? 'live runtime'}</div>
				{snapshot.scenario_view.levels.map((level) => (
					<div key={level.depth} style={{marginTop: 8}}>
						<strong>Level {level.depth}</strong>: {level.agents.join(', ')}
					</div>
				))}
			</section>

			<section style={{padding: 16, borderRight: '1px solid #334155'}}>
				<h2>Tree</h2>
				{snapshot.tree.roots.map((root) => (
					<TreeNode key={root} agentId={root} nodes={snapshot.tree.nodes} />
				))}

				<h2 style={{marginTop: 24}}>Agent Activity</h2>
				{Object.entries(snapshot.activity).map(([agentId, item]) => (
					<div key={agentId} style={{border: '1px solid #334155', borderRadius: 8, padding: 12, marginTop: 8}}>
						<div><strong>{agentId}</strong></div>
						<div>status: {item.status}</div>
						<div>children: {item.children.join(', ') || 'none'}</div>
						<div>messages: sent {item.messages_sent}, received {item.messages_received}</div>
						<div>recent: {item.recent_events.join(', ') || 'none'}</div>
					</div>
				))}
			</section>

			<section style={{padding: 16}}>
				<h2>Approvals</h2>
				{snapshot.approval_queue.map((item) => (
					<div key={String(item.correlation_id)} style={{border: '1px solid #334155', borderRadius: 8, padding: 12, marginTop: 8}}>
						<div><strong>{String(item.tool_name ?? 'approval')}</strong></div>
						<div>{String(item.agent_id)} / {String(item.status)}</div>
						{item.status === 'pending' ? (
							<div style={{display: 'flex', gap: 8, marginTop: 8}}>
								<button onClick={() => onResolveApproval(String(item.correlation_id), 'approved')}>Approve</button>
								<button onClick={() => onResolveApproval(String(item.correlation_id), 'rejected')}>Reject</button>
							</div>
						) : null}
					</div>
				))}

				<h2 style={{marginTop: 24}}>Inject Message</h2>
				<input value={targetAgent} onChange={(event) => setTargetAgent(event.target.value)} placeholder="agent_id" />
				<textarea value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Message" />
				<div>
					<button onClick={() => onSendMessage(targetAgent, message)}>Send</button>
				</div>

				<h2 style={{marginTop: 24}}>Agent Control</h2>
				<div style={{display: 'flex', gap: 8}}>
					<button onClick={() => onPauseAgent(targetAgent)}>Pause</button>
					<button onClick={() => onResumeAgent(targetAgent)}>Resume</button>
					<button onClick={() => onStopAgent(targetAgent)}>Stop</button>
				</div>

				<h2 style={{marginTop: 24}}>Spawn Agent</h2>
				<input value={spawnAgentId} onChange={(event) => setSpawnAgentId(event.target.value)} placeholder="agent id" />
				<input value={spawnParentId} onChange={(event) => setSpawnParentId(event.target.value)} placeholder="parent agent id" />
				<textarea value={spawnPrompt} onChange={(event) => setSpawnPrompt(event.target.value)} placeholder="spawn prompt" />
				<div style={{display: 'flex', gap: 8}}>
					<button onClick={() => onSpawnAgent(spawnAgentId, spawnPrompt, spawnParentId || undefined, 'synthetic')}>Spawn synthetic</button>
					<button onClick={() => onSpawnAgent(spawnAgentId, spawnPrompt, spawnParentId || undefined, 'live')}>Spawn live</button>
				</div>

				<h2 style={{marginTop: 24}}>Topology Editor</h2>
				<input value={topologyAgentId} onChange={(event) => setTopologyAgentId(event.target.value)} placeholder="agent id" />
				<input value={newParentId} onChange={(event) => setNewParentId(event.target.value)} placeholder="new parent id" />
				<div style={{display: 'flex', gap: 8}}>
					<button onClick={() => onReparentAgent(topologyAgentId, newParentId || undefined)}>Reparent</button>
					<button onClick={() => onRemoveAgent(topologyAgentId)}>Remove</button>
				</div>

				<h2 style={{marginTop: 24}}>Context Editor</h2>
				<input value={contextAgentId} onChange={(event) => setContextAgentId(event.target.value)} placeholder="agent id" />
				<input value={contextVersion} onChange={(event) => setContextVersion(event.target.value)} placeholder="base version" />
				<textarea value={contextPrompt} onChange={(event) => setContextPrompt(event.target.value)} placeholder="patched prompt" />
				<div>
					<button onClick={() => onApplyContextPatch(contextAgentId, Number(contextVersion), {prompt: contextPrompt})}>Apply Patch</button>
				</div>

				<h2 style={{marginTop: 24}}>Agent Operations</h2>
				<input value={operationAgentId} onChange={(event) => setOperationAgentId(event.target.value)} placeholder="target agent id" />
				<select value={operationName} onChange={(event) => setOperationName(event.target.value)}>
					<option value="inspect">inspect</option>
					<option value="send_message">send_message</option>
					<option value="spawn_child">spawn_child</option>
					<option value="pause">pause</option>
					<option value="resume">resume</option>
					<option value="stop">stop</option>
					<option value="reparent">reparent</option>
					<option value="remove">remove</option>
					<option value="patch_context">patch_context</option>
					<option value="run_tool">run_tool</option>
				</select>
				<textarea value={operationParams} onChange={(event) => setOperationParams(event.target.value)} placeholder='{"message":"..."}' />
				<div>
					<button
						onClick={() => {
							let parsed: Record<string, unknown> = {};
							try {
								parsed = JSON.parse(operationParams);
							} catch {
								parsed = {};
							}
							onAgentAction(operationAgentId, operationName, parsed);
						}}
					>
						Run Operation
					</button>
				</div>

				<h2 style={{marginTop: 24}}>Compare Runs</h2>
				<input value={leftRun} onChange={(event) => setLeftRun(event.target.value)} placeholder="left run id" />
				<input value={rightRun} onChange={(event) => setRightRun(event.target.value)} placeholder="right run id" />
				<div>
					<button onClick={() => onCompareRuns(leftRun, rightRun)}>Compare</button>
				</div>
				<h2 style={{marginTop: 24}}>Run Archives</h2>
				<input value={archiveLabel} onChange={(event) => setArchiveLabel(event.target.value)} placeholder="archive label" />
				<div>
					<button onClick={() => onArchiveRun(archiveLabel)}>Archive Current Run</button>
				</div>
				{snapshot.archives.map((archive) => (
					<div key={String(archive.run_id)}>{String(archive.label)} ({String(archive.run_id)})</div>
				))}
				{state.comparison ? <pre>{JSON.stringify(state.comparison, null, 2)}</pre> : null}
				{state.lastAck ? (
					<>
						<h2 style={{marginTop: 24}}>Last Action Result</h2>
						<pre>{JSON.stringify(state.lastAck, null, 2)}</pre>
					</>
				) : null}
				{state.lastError ? (
					<>
						<h2 style={{marginTop: 24}}>Last Error</h2>
						<div>{state.lastError}</div>
					</>
				) : null}
			</section>
		</div>
	);
}

function TreeNode({
	agentId,
	nodes,
}: {
	agentId: string;
	nodes: Record<string, {children: string[]; status: string}>;
}): React.JSX.Element {
	const node = nodes[agentId];
	if (!node) {
		return <div style={{marginLeft: 12, marginTop: 8}}>{agentId} (missing)</div>;
	}
	return (
		<div style={{marginLeft: 12, marginTop: 8}}>
			<div><strong>{agentId}</strong> ({node.status})</div>
			{node.children.map((child) => (
				<TreeNode key={child} agentId={child} nodes={nodes} />
			))}
		</div>
	);
}
