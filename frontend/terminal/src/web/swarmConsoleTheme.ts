import type React from 'react';

export const colors = {
	background: '#020617',
	panel: '#0f172a',
	panelRaised: '#111c34',
	panelMuted: '#0b1220',
	border: '#1e293b',
	borderStrong: '#334155',
	text: '#e2e8f0',
	textMuted: '#94a3b8',
	textSoft: '#64748b',
	accent: '#38bdf8',
	accentSoft: 'rgba(56, 189, 248, 0.16)',
	success: '#34d399',
	warning: '#fbbf24',
	danger: '#f87171',
	purple: '#c084fc',
};

export const cardStyle: React.CSSProperties = {
	background: `linear-gradient(180deg, ${colors.panelRaised} 0%, ${colors.panel} 100%)`,
	border: `1px solid ${colors.borderStrong}`,
	borderRadius: 18,
	boxShadow: '0 16px 40px rgba(2, 6, 23, 0.28)',
};

export const inputStyle: React.CSSProperties = {
	width: '100%',
	padding: '10px 12px',
	borderRadius: 12,
	border: `1px solid ${colors.borderStrong}`,
	background: colors.panelMuted,
	color: colors.text,
	outline: 'none',
	boxSizing: 'border-box',
};

export const textareaStyle: React.CSSProperties = {
	...inputStyle,
	minHeight: 92,
	resize: 'vertical',
	fontFamily: 'inherit',
};

export const buttonStyle: React.CSSProperties = {
	padding: '9px 14px',
	borderRadius: 12,
	border: `1px solid ${colors.borderStrong}`,
	background: colors.panelMuted,
	color: colors.text,
	cursor: 'pointer',
	fontWeight: 600,
};

export function statusColor(status?: string): string {
	switch (status) {
		case 'running':
			return colors.success;
		case 'paused':
			return colors.warning;
		case 'finished':
			return colors.textSoft;
		case 'starting':
			return colors.accent;
		default:
			return colors.textMuted;
	}
}

export function formatConsoleTime(timestamp: number | null | undefined): string {
	if (!timestamp) {
		return 'now';
	}
	try {
		return new Date(timestamp * 1000).toLocaleTimeString();
	} catch {
		return 'now';
	}
}
