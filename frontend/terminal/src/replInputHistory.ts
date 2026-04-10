/**
 * Cross-session REPL input history (ring buffer) for the Ink TUI.
 * Matches Python `get_data_dir()` layout: ~/.treecode/data/ unless TREECODE_DATA_DIR is set.
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import {REPL_INPUT_HISTORY_MAX, mergeReplHistoryRing} from './shared/replHistoryRing.js';

export {REPL_INPUT_HISTORY_MAX, mergeReplHistoryRing} from './shared/replHistoryRing.js';

export function getReplInputHistoryPath(): string {
	const base = process.env.TREECODE_DATA_DIR ?? path.join(os.homedir(), '.treecode', 'data');
	return path.join(base, 'repl_input_history.jsonl');
}

/** Oldest first, newest last; at most REPL_INPUT_HISTORY_MAX entries. */
export function loadReplInputHistory(): string[] {
	const p = getReplInputHistoryPath();
	try {
		if (!fs.existsSync(p)) {
			return [];
		}
		const raw = fs.readFileSync(p, 'utf8');
		const lines: string[] = [];
		for (const row of raw.split('\n')) {
			if (!row.trim()) {
				continue;
			}
			try {
				const o = JSON.parse(row) as { line?: string };
				if (typeof o.line === 'string') {
					lines.push(o.line);
				}
			} catch {
				// skip corrupt row
			}
		}
		return lines.slice(-REPL_INPUT_HISTORY_MAX);
	} catch {
		return [];
	}
}

export function saveReplInputHistory(entries: string[]): void {
	const trimmed = entries.slice(-REPL_INPUT_HISTORY_MAX);
	const p = getReplInputHistoryPath();
	try {
		fs.mkdirSync(path.dirname(p), { recursive: true });
		const body = trimmed.map((line) => JSON.stringify({ line })).join('\n') + (trimmed.length ? '\n' : '');
		fs.writeFileSync(p, body, 'utf8');
	} catch {
		// ignore read-only home, etc.
	}
}

/** Append one submitted line, persist, return next state for React setState. */
export function appendReplInputHistory(prev: string[], line: string): string[] {
	const next = mergeReplHistoryRing(prev, line);
	saveReplInputHistory(next);
	return next;
}

/**
 * Reload when ``repl_input_history.jsonl`` changes on disk (e.g. Web Console / Python appended a line).
 * Watches the data directory and filters by filename so the Ink TUI stays aligned with the shared ring.
 */
export function watchReplInputHistory(onDiskChanged: () => void): () => void {
	const p = getReplInputHistoryPath();
	const dir = path.dirname(p);
	const base = path.basename(p);
	let debounce: ReturnType<typeof setTimeout> | undefined;
	const fire = (): void => {
		if (debounce !== undefined) {
			clearTimeout(debounce);
		}
		debounce = setTimeout(() => {
			debounce = undefined;
			onDiskChanged();
		}, 80);
	};
	try {
		fs.mkdirSync(dir, {recursive: true});
	} catch {
		// ignore
	}
	let watcher: fs.FSWatcher;
	try {
		watcher = fs.watch(dir, (event, filename) => {
			if (filename === null || filename === base) {
				fire();
			}
		});
	} catch {
		return () => {};
	}
	return () => {
		if (debounce !== undefined) {
			clearTimeout(debounce);
		}
		try {
			watcher.close();
		} catch {
			// ignore
		}
	};
}
