/**
 * WebSocket Manager Module
 * =========================
 * WebSocket connection management with exponential backoff reconnection.
 */

import { showToast } from './toast.js';
import { i18n } from './i18n.js';

/**
 * WebSocket connection states
 */
export const ConnectionState = {
    CONNECTING: 'connecting',
    CONNECTED: 'connected',
    DISCONNECTED: 'disconnected',
    RECONNECTING: 'reconnecting',
    ERROR: 'error'
};

/**
 * WebSocket Manager class
 * Handles WebSocket connections with automatic reconnection using exponential backoff
 */
export class WebSocketManager {
    /**
     * Create a WebSocket manager
     *
     * @param {Object} options - Configuration options
     * @param {string} [options.path='/ws/learning'] - WebSocket path
     * @param {number} [options.maxReconnectAttempts=5] - Maximum reconnection attempts
     * @param {number} [options.baseDelay=1000] - Base delay for reconnection in ms
     * @param {number} [options.maxDelay=30000] - Maximum delay between reconnection attempts
     * @param {Function} [options.onMessage] - Message handler callback
     * @param {Function} [options.onStateChange] - State change callback
     */
    constructor(options = {}) {
        this.path = options.path || '/ws/learning';
        this.maxReconnectAttempts = options.maxReconnectAttempts || 5;
        this.baseDelay = options.baseDelay || 1000;
        this.maxDelay = options.maxDelay || 30000;
        this.onMessage = options.onMessage || (() => {});
        this.onStateChange = options.onStateChange || (() => {});

        this.ws = null;
        this.reconnectAttempts = 0;
        this.reconnectTimeout = null;
        this.state = ConnectionState.DISCONNECTED;
        this.sessionId = null;
    }

    /**
     * Get WebSocket URL
     *
     * @param {string} [sessionId] - Session ID to include in path
     * @returns {string} - Full WebSocket URL
     */
    getUrl(sessionId) {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const path = sessionId ? `${this.path}/${sessionId}` : this.path;
        return `${protocol}//${window.location.host}${path}`;
    }

    /**
     * Update connection state
     *
     * @param {string} newState - New connection state
     */
    setState(newState) {
        if (this.state !== newState) {
            const oldState = this.state;
            this.state = newState;
            this.onStateChange(newState, oldState);
        }
    }

    /**
     * Connect to WebSocket server
     *
     * @param {string} [sessionId] - Session ID
     */
    connect(sessionId) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            console.log('[WebSocket] Already connected');
            return;
        }

        this.sessionId = sessionId;
        this.setState(ConnectionState.CONNECTING);

        try {
            const url = this.getUrl(sessionId);
            console.log('[WebSocket] Connecting to:', url);

            this.ws = new WebSocket(url);

            this.ws.onopen = () => this.handleOpen();
            this.ws.onmessage = (event) => this.handleMessage(event);
            this.ws.onclose = (event) => this.handleClose(event);
            this.ws.onerror = (error) => this.handleError(error);

        } catch (error) {
            console.error('[WebSocket] Connection error:', error);
            this.setState(ConnectionState.ERROR);
            this.scheduleReconnect();
        }
    }

    /**
     * Handle WebSocket open event
     */
    handleOpen() {
        console.log('[WebSocket] Connected');
        this.setState(ConnectionState.CONNECTED);
        this.reconnectAttempts = 0;

        // Show reconnected toast if this was a reconnection
        if (this.reconnectAttempts > 0) {
            showToast(i18n.t('toast.reconnected'), 'success');
        }
    }

    /**
     * Handle incoming WebSocket message
     *
     * @param {MessageEvent} event - WebSocket message event
     */
    handleMessage(event) {
        try {
            const data = JSON.parse(event.data);
            console.log('[WebSocket] Received:', data.type);
            this.onMessage(data);
        } catch (error) {
            console.error('[WebSocket] Failed to parse message:', error);
        }
    }

    /**
     * Handle WebSocket close event
     *
     * @param {CloseEvent} event - WebSocket close event
     */
    handleClose(event) {
        console.log('[WebSocket] Closed:', event.code, event.reason);
        this.ws = null;

        // Normal closure (1000) or going away (1001) - don't reconnect
        if (event.code === 1000 || event.code === 1001) {
            this.setState(ConnectionState.DISCONNECTED);
            return;
        }

        this.scheduleReconnect();
    }

    /**
     * Handle WebSocket error
     *
     * @param {Event} error - WebSocket error event
     */
    handleError(error) {
        console.error('[WebSocket] Error:', error);
        this.setState(ConnectionState.ERROR);
    }

    /**
     * Schedule reconnection with exponential backoff
     */
    scheduleReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.log('[WebSocket] Max reconnection attempts reached');
            this.setState(ConnectionState.DISCONNECTED);
            showToast(i18n.t('toast.connectionLost'), 'error');
            return;
        }

        this.reconnectAttempts++;
        this.setState(ConnectionState.RECONNECTING);

        // Calculate delay with exponential backoff
        const delay = Math.min(
            this.baseDelay * Math.pow(2, this.reconnectAttempts - 1),
            this.maxDelay
        );

        console.log(`[WebSocket] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
        showToast(i18n.t('toast.reconnecting'), 'warning');

        this.reconnectTimeout = setTimeout(() => {
            this.connect(this.sessionId);
        }, delay);
    }

    /**
     * Send data through WebSocket
     *
     * @param {Object|string} data - Data to send
     * @returns {boolean} - Whether send was successful
     */
    send(data) {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            console.warn('[WebSocket] Cannot send - not connected');
            return false;
        }

        try {
            const message = typeof data === 'string' ? data : JSON.stringify(data);
            this.ws.send(message);
            return true;
        } catch (error) {
            console.error('[WebSocket] Send error:', error);
            return false;
        }
    }

    /**
     * Close WebSocket connection
     *
     * @param {number} [code=1000] - Close code
     * @param {string} [reason=''] - Close reason
     */
    close(code = 1000, reason = '') {
        // Clear any pending reconnection
        if (this.reconnectTimeout) {
            clearTimeout(this.reconnectTimeout);
            this.reconnectTimeout = null;
        }

        if (this.ws) {
            this.ws.close(code, reason);
            this.ws = null;
        }

        this.setState(ConnectionState.DISCONNECTED);
    }

    /**
     * Check if WebSocket is connected
     *
     * @returns {boolean} - Whether connected
     */
    isConnected() {
        return this.ws && this.ws.readyState === WebSocket.OPEN;
    }

    /**
     * Get current connection state
     *
     * @returns {string} - Current state
     */
    getState() {
        return this.state;
    }
}

// Export a factory function for convenience
export function createWebSocketManager(options) {
    return new WebSocketManager(options);
}
