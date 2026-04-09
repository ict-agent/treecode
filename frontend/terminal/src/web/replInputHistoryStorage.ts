/**
 * Browser localStorage persistence for the swarm web console input history.
 * Same 1000-line ring as the Ink TUI (different storage: per-origin, not ~/.openharness).
 */

import {REPL_INPUT_HISTORY_MAX, mergeReplHistoryRing} from '../shared/replHistoryRing.js';

const STORAGE_KEY = 'openharness:repl_input_history_web_v1';

export function loadWebReplInputHistory(): string[] {
	if (typeof localStorage === 'undefined') {
		return [];
	}
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (!raw) {
			return [];
		}
		const parsed = JSON.parse(raw) as unknown;
		if (!Array.isArray(parsed)) {
			return [];
		}
		const lines = parsed.filter((x): x is string => typeof x === 'string');
		return lines.slice(-REPL_INPUT_HISTORY_MAX);
	} catch {
		return [];
	}
}

export function saveWebReplInputHistory(entries: string[]): void {
	if (typeof localStorage === 'undefined') {
		return;
	}
	try {
		const trimmed = entries.slice(-REPL_INPUT_HISTORY_MAX);
		localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
	} catch {
		// quota / private mode
	}
}

export function appendWebReplInputHistory(prev: string[], line: string): string[] {
	const next = mergeReplHistoryRing(prev, line);
	saveWebReplInputHistory(next);
	return next;
}
