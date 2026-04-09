import React from 'react';
import {Box, Text} from 'ink';

import type {SlashCommandEntry} from '../types.js';

export function CommandPicker({
	hints,
	selectedIndex,
}: {
	hints: SlashCommandEntry[];
	selectedIndex: number;
}): React.JSX.Element | null {
	if (hints.length === 0) {
		return null;
	}

	return (
		<Box flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={1} marginBottom={0}>
			<Text dimColor bold> Commands</Text>
			{hints.map((hint, i) => {
				const isSelected = i === selectedIndex;
				return (
					<Box key={hint.prefix} flexDirection="column">
						<Box>
							<Text color={isSelected ? 'cyan' : undefined} bold={isSelected}>
								{isSelected ? '\u276F ' : '  '}
								{hint.prefix}
							</Text>
							{hint.description ? (
								<Text dimColor>
									{' '}
									— {hint.description}
								</Text>
							) : null}
							{isSelected ? <Text dimColor> [enter]</Text> : null}
						</Box>
						{isSelected && hint.usage ? (
							<Box marginLeft={2}>
								<Text dimColor>{hint.usage}</Text>
							</Box>
						) : null}
					</Box>
				);
			})}
			<Text dimColor>
				{' '}
				{'\u2191\u2193'} navigate{'  '}
				{'\u23CE'} select{'  '}tab insert{'  '}esc dismiss
			</Text>
		</Box>
	);
}
