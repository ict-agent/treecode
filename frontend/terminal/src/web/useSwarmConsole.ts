import {useEffect, useReducer, useRef} from 'react';

import {createInitialSwarmConsoleState, reduceSwarmConsoleMessage} from '../shared/swarmConsoleState.js';
import type {SwarmConsoleCommand} from '../shared/swarmConsoleProtocol.js';
import {WebSocketClient} from '../transports/webSocketClient.js';

const DEFAULT_WS_URL = 'ws://127.0.0.1:8766';

export function useSwarmConsole() {
	const [state, dispatch] = useReducer(reduceSwarmConsoleMessage, undefined, createInitialSwarmConsoleState);
	const clientRef = useRef<WebSocketClient | null>(null);

	useEffect(() => {
		const client = new WebSocketClient();
		clientRef.current = client;
		client.connect(import.meta.env.VITE_SWARM_CONSOLE_WS_URL ?? DEFAULT_WS_URL, (message) => {
			dispatch(message);
		});
		return () => {
			client.close();
			clientRef.current = null;
		};
	}, []);

	const sendCommand = (message: SwarmConsoleCommand): void => {
		clientRef.current?.send(message);
	};

	return {state, sendCommand};
}
