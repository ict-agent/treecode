/** Shared ring-buffer logic for REPL input history (TUI file + web localStorage). */

export const REPL_INPUT_HISTORY_MAX = 1000;

export function mergeReplHistoryRing(prev: string[], line: string): string[] {
	return [...prev, line].slice(-REPL_INPUT_HISTORY_MAX);
}
