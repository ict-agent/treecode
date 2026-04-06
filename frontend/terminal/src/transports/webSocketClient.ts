import type {SwarmConsoleCommand, SwarmConsoleServerMessage} from '../shared/swarmConsoleProtocol.js';

/** Exponential backoff for reconnect after unexpected close; max delay 10s; unbounded attempts. */
const RECONNECT_BASE_MS = 500;
const RECONNECT_MAX_MS = 10_000;

export class WebSocketClient {
	private socket: WebSocket | null = null;
	private queue: string[] = [];
	private _manualClose = false;
	private _url: string | null = null;
	private _onMessage: ((message: SwarmConsoleServerMessage) => void) | null = null;
	private _reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	private _reconnectAttempt = 0;

	connect(url: string, onMessage: (message: SwarmConsoleServerMessage) => void): void {
		if (this._reconnectTimer !== null) {
			clearTimeout(this._reconnectTimer);
			this._reconnectTimer = null;
		}
		this._manualClose = false;
		this._url = url;
		this._onMessage = onMessage;
		this._openSocket();
	}

	private _openSocket(): void {
		if (this._manualClose || this._url === null || this._onMessage === null) {
			return;
		}
		this.socket = new WebSocket(this._url);
		this.socket.addEventListener('open', () => {
			this._reconnectAttempt = 0;
			for (const item of this.queue) {
				this.socket?.send(item);
			}
			this.queue = [];
		});
		this.socket.addEventListener('message', (event) => {
			try {
				this._onMessage?.(JSON.parse(String(event.data)) as SwarmConsoleServerMessage);
			} catch {
				this._onMessage?.({
					type: 'error',
					payload: {},
					message: 'Failed to parse websocket message',
				});
			}
		});
		this.socket.addEventListener('close', () => {
			this.socket = null;
			if (this._manualClose || this._url === null || this._onMessage === null) {
				return;
			}
			const exp = Math.min(RECONNECT_BASE_MS * 2 ** this._reconnectAttempt, RECONNECT_MAX_MS);
			this._reconnectAttempt += 1;
			this._reconnectTimer = setTimeout(() => {
				this._reconnectTimer = null;
				this._openSocket();
			}, exp);
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
		this._manualClose = true;
		if (this._reconnectTimer !== null) {
			clearTimeout(this._reconnectTimer);
			this._reconnectTimer = null;
		}
		this.socket?.close();
		this.socket = null;
	}
}
