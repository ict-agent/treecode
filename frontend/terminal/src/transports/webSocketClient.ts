import type {SwarmConsoleCommand, SwarmConsoleServerMessage} from '../shared/swarmConsoleProtocol.js';

export class WebSocketClient {
	private socket: WebSocket | null = null;
	private queue: string[] = [];

	connect(url: string, onMessage: (message: SwarmConsoleServerMessage) => void): void {
		this.socket = new WebSocket(url);
		this.socket.addEventListener('open', () => {
			for (const item of this.queue) {
				this.socket?.send(item);
			}
			this.queue = [];
		});
		this.socket.addEventListener('message', (event) => {
			try {
				onMessage(JSON.parse(String(event.data)) as SwarmConsoleServerMessage);
			} catch {
				onMessage({
					type: 'error',
					payload: {},
					message: 'Failed to parse websocket message',
				});
			}
		});
	}

	send(message: SwarmConsoleCommand): void {
		const serialized = JSON.stringify(message);
		if (this.socket?.readyState === WebSocket.OPEN) {
			this.socket.send(serialized);
			return;
		}
		this.queue.push(serialized);
	}

	close(): void {
		this.socket?.close();
		this.socket = null;
	}
}
