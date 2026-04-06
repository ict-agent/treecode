import React from 'react';

type Options = {
	storageKey: string;
	initialRatio: number;
	minRatio: number;
	maxRatio: number;
};

function clamp(value: number, min: number, max: number): number {
	return Math.max(min, Math.min(max, value));
}

export function useResizablePanel({
	storageKey,
	initialRatio,
	minRatio,
	maxRatio,
}: Options) {
	const containerRef = React.useRef<HTMLDivElement | null>(null);
	const [containerWidth, setContainerWidth] = React.useState(0);
	const [ratio, setRatio] = React.useState(() => {
		if (typeof window === 'undefined') {
			return initialRatio;
		}
		const stored = window.localStorage.getItem(storageKey);
		const parsed = stored ? Number(stored) : Number.NaN;
		return Number.isFinite(parsed) ? clamp(parsed, minRatio, maxRatio) : initialRatio;
	});

	React.useEffect(() => {
		if (typeof window === 'undefined') {
			return;
		}
		window.localStorage.setItem(storageKey, String(ratio));
	}, [ratio, storageKey]);

	React.useEffect(() => {
		const updateWidth = () => {
			const rect = containerRef.current?.getBoundingClientRect();
			setContainerWidth(rect?.width ?? 0);
		};
		updateWidth();
		if (typeof ResizeObserver === 'undefined' || !containerRef.current) {
			window.addEventListener('resize', updateWidth);
			return () => window.removeEventListener('resize', updateWidth);
		}
		const observer = new ResizeObserver(() => updateWidth());
		observer.observe(containerRef.current);
		return () => observer.disconnect();
	}, []);

	const beginResize = React.useCallback(
		(event: React.MouseEvent<HTMLDivElement>) => {
			event.preventDefault();
			const handlePointerMove = (nextEvent: MouseEvent) => {
				const rect = containerRef.current?.getBoundingClientRect();
				if (!rect || rect.width <= 0) {
					return;
				}
				const nextRatio = clamp((nextEvent.clientX - rect.left) / rect.width, minRatio, maxRatio);
				setRatio(nextRatio);
			};
			const handlePointerUp = () => {
				window.removeEventListener('mousemove', handlePointerMove);
				window.removeEventListener('mouseup', handlePointerUp);
			};

			window.addEventListener('mousemove', handlePointerMove);
			window.addEventListener('mouseup', handlePointerUp);
		},
		[maxRatio, minRatio],
	);

	const minimumLeftPx = containerWidth > 0 ? Math.min(320, containerWidth * 0.45) : 320;
	const maximumLeftPx = containerWidth > 0 ? Math.max(minimumLeftPx, containerWidth - 420) : undefined;
	const panelWidthPx =
		containerWidth > 0
			? clamp(containerWidth * ratio, minimumLeftPx, maximumLeftPx ?? containerWidth)
			: undefined;

	return {containerRef, ratio, beginResize, setRatio, panelWidthPx};
}
