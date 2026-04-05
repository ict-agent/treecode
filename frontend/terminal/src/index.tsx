import React from 'react';
import {render} from 'ink';

import {TerminalApp} from './terminal/TerminalApp.js';
import type {FrontendConfig} from './types.js';

const config = JSON.parse(process.env.OPENHARNESS_FRONTEND_CONFIG ?? '{}') as FrontendConfig;

render(<TerminalApp config={config} />);
