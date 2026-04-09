import {describe, expect, it} from 'vitest';

import {mergeReplHistoryRing, REPL_INPUT_HISTORY_MAX} from './shared/replHistoryRing.js';

describe('mergeReplHistoryRing', () => {
	it('keeps order and caps at REPL_INPUT_HISTORY_MAX', () => {
		const base = Array.from({ length: REPL_INPUT_HISTORY_MAX }, (_, i) => `line${i}`);
		const next = mergeReplHistoryRing(base, 'new');
		expect(next).toHaveLength(REPL_INPUT_HISTORY_MAX);
		expect(next[REPL_INPUT_HISTORY_MAX - 1]).toBe('new');
		expect(next[0]).toBe('line1');
	});

	it('appends when under cap', () => {
		expect(mergeReplHistoryRing(['a'], 'b')).toEqual(['a', 'b']);
	});
});
