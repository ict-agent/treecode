import React from 'react';
import {Box, Text} from 'ink';

import {useTheme} from '../theme/ThemeContext.js';

const VERSION = '0.1.1';

/**
 * Figlet font `rounded`: parentheses / pipes like the legacy Unicode banner (not ASCII `#` figlet).
 * Rows are fixed width so monospace columns stay aligned; rendered as one multiline string so Ink does not
 * lay out each row in flex separately (which can shift glyphs).
 */
const LOGO_WIDTH = 70;

const LOGO_LINES: readonly string[] = [
	'________ ______  _______ _______    _______ _______ ______  ________',
	'____ ___| ____ \\(_______|_______)  ( _____)| _____ | ____ )( _______) ',
	'   | |  | _____)|_____  |_____     | |     | |   | | |   | |_____ ',
	'   | |  |  __  /|  ___) |  ___)    | |     | |   | | |   | |  ____) ',
	'   | |  | |  \\ \\| |_____| |_____   | |____ | |___| | |__/ /| |_____',
	'   |_|  |_|   |_|_______)_______)  \\______) \\_____/|_____/ |________)',
];

const LOGO_BLOCK = LOGO_LINES.map((line) => line.padEnd(LOGO_WIDTH, ' ')).join('\n');

export function WelcomeBanner(): React.JSX.Element {
	const {theme} = useTheme();

	return (
		<Box flexDirection="column" marginBottom={1} alignSelf="flex-start" flexShrink={0}>
			<Box flexDirection="column" paddingX={0}>
				<Text color={theme.colors.primary} bold>
					{LOGO_BLOCK}
				</Text>
				<Text> </Text>
				<Text>
					<Text dimColor> An AI-powered coding assistant</Text>
					<Text dimColor>{'  '}v{VERSION}</Text>
				</Text>
				<Text> </Text>
				<Text>
					<Text dimColor> </Text>
					<Text color={theme.colors.primary}>/help</Text>
					<Text dimColor> commands</Text>
					<Text dimColor>{'  '}|{'  '}</Text>
					<Text color={theme.colors.primary}>/model</Text>
					<Text dimColor> switch</Text>
					<Text dimColor>{'  '}|{'  '}</Text>
					<Text color={theme.colors.primary}>Ctrl+C</Text>
					<Text dimColor> exit</Text>
				</Text>
			</Box>
		</Box>
	);
}
