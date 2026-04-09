import React, {createContext, useCallback, useContext, useEffect, useMemo, useRef, useState} from 'react';

import {mergeReplHistoryRing} from '../shared/replHistoryRing.js';
import {appendWebReplInputHistory, loadWebReplInputHistory, saveWebReplInputHistory} from './replInputHistoryStorage.js';
import {buttonStyle as themeButtonStyle} from './swarmConsoleTheme.js';

type LinesContextValue = {
	lines: string[];
	commitLine: (line: string) => void;
};

const LinesContext = createContext<LinesContextValue | null>(null);

type ProviderProps = {
	children: React.ReactNode;
	/**
	 * Host disk ring from WebSocket (``repl_input_history.jsonl``, same as Ink TUI).
	 * Until non-null, commits persist to localStorage only (offline / tests).
	 */
	serverRing: string[] | null;
};

export function WebReplInputHistoryProvider({children, serverRing}: ProviderProps): React.JSX.Element {
	const [lines, setLines] = useState(() => loadWebReplInputHistory());
	const hostSynced = serverRing !== null;

	useEffect(() => {
		if (serverRing === null) {
			return;
		}
		setLines(serverRing);
		saveWebReplInputHistory(serverRing);
	}, [serverRing]);

	const commitLine = useCallback(
		(line: string) => {
			const t = line.trim();
			if (!t) {
				return;
			}
			setLines((prev) => {
				const next = mergeReplHistoryRing(prev, t);
				if (!hostSynced) {
					saveWebReplInputHistory(next);
				}
				return next;
			});
		},
		[hostSynced],
	);

	const value = useMemo(() => ({lines, commitLine}), [lines, commitLine]);
	return <LinesContext.Provider value={value}>{children}</LinesContext.Provider>;
}

type ComposerSnapshot = {draft: string; nav: number};

/**
 * Shared line ring (context) + per-field draft and history cursor (local state).
 * History navigation always updates draft + nav in one setState — same idea as typing into the field.
 */
export function useWebReplComposer(): {
	draft: string;
	lines: string[];
	commitLineToStorage: (line: string) => void;
	setDraftFromUser: (value: string) => void;
	goOlder: () => void;
	goNewer: () => void;
	clear: () => void;
	resetNav: () => void;
	canOlder: boolean;
	canNewer: boolean;
	inputRef: React.RefObject<HTMLInputElement | HTMLTextAreaElement | null>;
} {
	const ctx = useContext(LinesContext);
	if (!ctx) {
		throw new Error('useWebReplComposer must be used inside WebReplInputHistoryProvider');
	}
	const {lines, commitLine} = ctx;
	const linesRef = useRef(lines);
	linesRef.current = lines;

	const [st, setSt] = useState<ComposerSnapshot>({draft: '', nav: -1});
	const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null);

	const setDraftFromUser = useCallback((value: string) => {
		setSt({draft: value, nav: -1});
	}, []);

	function resolveRing(): string[] {
		const mem = linesRef.current;
		if (mem.length > 0) {
			return mem;
		}
		return loadWebReplInputHistory();
	}

	const goOlder = useCallback(() => {
		setSt((s) => {
			const h = resolveRing();
			if (h.length === 0) {
				return s;
			}
			const next = s.nav < 0 ? 0 : Math.min(h.length - 1, s.nav + 1);
			return {draft: h[h.length - 1 - next] ?? '', nav: next};
		});
		queueMicrotask(() => inputRef.current?.focus());
	}, []);

	const goNewer = useCallback(() => {
		setSt((s) => {
			const h = resolveRing();
			const next = Math.max(-1, s.nav - 1);
			return {draft: next < 0 ? '' : (h[h.length - 1 - next] ?? ''), nav: next};
		});
		queueMicrotask(() => inputRef.current?.focus());
	}, []);

	const clear = useCallback(() => {
		setSt({draft: '', nav: -1});
	}, []);

	const resetNav = useCallback(() => {
		setSt((s) => ({...s, nav: -1}));
	}, []);

	const commitLineToStorage = useCallback(
		(line: string) => {
			commitLine(line);
		},
		[commitLine],
	);

	const navRing = resolveRing();
	const canOlder = navRing.length > 0 && st.nav < navRing.length - 1;
	const canNewer = st.nav >= 0;

	return {
		draft: st.draft,
		lines: navRing,
		commitLineToStorage,
		setDraftFromUser,
		goOlder,
		goNewer,
		clear,
		resetNav,
		canOlder,
		canNewer,
		inputRef,
	};
}

/** Same interaction model as Send / Send Follow-up: click → fills the composer with a full saved line. */
export function WebReplHistoryFillButtons({
	canOlder,
	canNewer,
	goOlder,
	goNewer,
}: {
	canOlder: boolean;
	canNewer: boolean;
	goOlder: () => void;
	goNewer: () => void;
}): React.JSX.Element {
	const compactBtn: React.CSSProperties = {
		...themeButtonStyle,
		fontSize: 12,
		padding: '6px 12px',
		fontWeight: 600,
		whiteSpace: 'nowrap',
		flexShrink: 0,
	};
	return (
		<div
			style={{
				display: 'flex',
				gap: 8,
				alignItems: 'center',
				flexShrink: 0,
			}}
		>
			<button type="button" style={{...compactBtn, opacity: canOlder ? 1 : 0.45}} onClick={goOlder}>
				Prev line
			</button>
			<button type="button" style={{...compactBtn, opacity: canNewer ? 1 : 0.45}} onClick={goNewer}>
				Next line
			</button>
		</div>
	);
}

/** @deprecated use WebReplHistoryFillButtons */
export const WebReplHistoryNavButtons = WebReplHistoryFillButtons;
