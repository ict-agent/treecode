import type {SwarmConsoleMessage} from './swarmConsoleState.js';

export type SwarmConsoleCommand =
	| {type: 'command'; command: 'run_scenario'; payload: {name: string}}
	| {type: 'command'; command: 'set_active_source'; payload: {source: 'live' | 'scenario'}}
	| {type: 'command'; command: 'set_topology_view'; payload: {view: 'live' | 'raw_events'}}
	| {type: 'command'; command: 'agent_action'; payload: {agent_id: string; action: string; params: Record<string, unknown>}}
	| {type: 'command'; command: 'resolve_approval'; payload: {correlation_id: string; status: string}}
	| {type: 'command'; command: 'send_message'; payload: {agent_id: string; message: string}}
	| {type: 'command'; command: 'pause_agent'; payload: {agent_id: string}}
	| {type: 'command'; command: 'resume_agent'; payload: {agent_id: string}}
	| {type: 'command'; command: 'stop_agent'; payload: {agent_id: string}}
	| {type: 'command'; command: 'compare_runs'; payload: {left_run_id: string; right_run_id: string}}
	| {type: 'command'; command: 'list_archives'; payload?: Record<string, never>}
	| {type: 'command'; command: 'archive_current_run'; payload: {label: string}}
	| {type: 'command'; command: 'spawn_agent'; payload: {agent_id: string; prompt: string; parent_agent_id?: string; mode?: string}}
	| {type: 'command'; command: 'reparent_agent'; payload: {agent_id: string; new_parent_agent_id?: string}}
	| {type: 'command'; command: 'remove_agent'; payload: {agent_id: string}}
	| {type: 'command'; command: 'apply_context_patch'; payload: {agent_id: string; base_version: number; patch: Record<string, unknown>}}
	| {type: 'command'; command: 'list_scenarios'; payload?: Record<string, never>}
	| {type: 'command'; command: 'get_snapshot'; payload?: Record<string, never>}
	| {type: 'command'; command: 'oh_submit_line'; payload: {line: string; client_id?: string}}
	| {type: 'command'; command: 'oh_permission_response'; payload: {request_id: string; allowed: boolean}}
	| {type: 'command'; command: 'oh_question_response'; payload: {request_id: string; answer: string}}
	| {type: 'command'; command: 'oh_set_selected_agent'; payload: {agent_id: string; client_id?: string}};

export type SwarmConsoleServerMessage = SwarmConsoleMessage;
