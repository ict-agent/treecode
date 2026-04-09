import React from 'react';

import {WebReplInputHistoryProvider} from './WebReplInputHistory.js';
import {WebConsoleView} from './WebConsoleView.js';
import {useSwarmConsole} from './useSwarmConsole.js';

export function WebApp(): React.JSX.Element {
	const {state, sendCommand} = useSwarmConsole();

	return (
		<WebReplInputHistoryProvider serverRing={state.replInputHistoryLines}>
			<WebConsoleView
				state={state}
				sendCommand={sendCommand}
				onRunScenario={(name) => sendCommand({type: 'command', command: 'run_scenario', payload: {name}})}
				onSetActiveSource={(source) =>
					sendCommand({
						type: 'command',
						command: 'set_active_source',
						payload: {source},
					})
				}
				onSetTopologyView={(view) =>
					sendCommand({
						type: 'command',
						command: 'set_topology_view',
						payload: {view},
					})
				}
				onResolveApproval={(correlationId, status) =>
					sendCommand({
						type: 'command',
						command: 'resolve_approval',
						payload: {correlation_id: correlationId, status},
					})
				}
				onSendMessage={(agentId, message) =>
					sendCommand({
						type: 'command',
						command: 'send_message',
						payload: {agent_id: agentId, message},
					})
				}
				onCompareRuns={(leftRunId, rightRunId) =>
					sendCommand({
						type: 'command',
						command: 'compare_runs',
						payload: {left_run_id: leftRunId, right_run_id: rightRunId},
					})
				}
				onArchiveRun={(label) =>
					sendCommand({
						type: 'command',
						command: 'archive_current_run',
						payload: {label},
					})
				}
				onSpawnAgent={(agentId, prompt, parentAgentId, mode) =>
					sendCommand({
						type: 'command',
						command: 'spawn_agent',
						payload: {agent_id: agentId, prompt, parent_agent_id: parentAgentId, mode},
					})
				}
				onReparentAgent={(agentId, newParentAgentId) =>
					sendCommand({
						type: 'command',
						command: 'reparent_agent',
						payload: {agent_id: agentId, new_parent_agent_id: newParentAgentId},
					})
				}
				onRemoveAgent={(agentId) =>
					sendCommand({
						type: 'command',
						command: 'remove_agent',
						payload: {agent_id: agentId},
					})
				}
				onApplyContextPatch={(agentId, baseVersion, patch) =>
					sendCommand({
						type: 'command',
						command: 'apply_context_patch',
						payload: {agent_id: agentId, base_version: baseVersion, patch},
					})
				}
				onPauseAgent={(agentId) =>
					sendCommand({
						type: 'command',
						command: 'pause_agent',
						payload: {agent_id: agentId},
					})
				}
				onResumeAgent={(agentId) =>
					sendCommand({
						type: 'command',
						command: 'resume_agent',
						payload: {agent_id: agentId},
					})
				}
				onStopAgent={(agentId) =>
					sendCommand({
						type: 'command',
						command: 'stop_agent',
						payload: {agent_id: agentId},
					})
				}
				onAgentAction={(agentId, action, params) =>
					sendCommand({
						type: 'command',
						command: 'agent_action',
						payload: {agent_id: agentId, action, params},
					})
				}
			/>
		</WebReplInputHistoryProvider>
	);
}
