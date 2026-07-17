/**
 * Toast Notification Module
 * ==========================
 * Toast notification system with multiple types and animations.
 */

/**
 * Escape HTML special characters to prevent XSS
 * (Local copy to avoid circular dependency)
 */
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Toast types
 */
export const ToastType = {
    SUCCESS: 'success',
    ERROR: 'error',
    WARNING: 'warning',
    INFO: 'info'
};

/**
 * Toast icon SVGs
 */
const toastIcons = {
    success: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
    error: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    warning: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    info: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>'
};

/**
 * Toast container element ID
 */
const CONTAINER_ID = 'toast-container';

/**
 * Default toast duration in ms
 */
const DEFAULT_DURATION = 3000;

/**
 * Get or create toast container element
 *
 * @returns {HTMLElement} - Toast container element
 */
function getContainer() {
    let container = document.getElementById(CONTAINER_ID);

    if (!container) {
        container = document.createElement('div');
        container.id = CONTAINER_ID;
        container.className = 'toast-container';
        document.body.appendChild(container);
    }

    return container;
}

/**
 * Show a toast notification
 *
 * @param {string} message - Message to display
 * @param {string} [type='info'] - Toast type (success, error, warning, info)
 * @param {number} [duration=3000] - Duration in ms before auto-dismiss
 * @param {Object} [options={}] - Additional options
 * @param {boolean} [options.dismissible=true] - Whether toast can be clicked to dismiss
 * @param {Function} [options.onClick] - Click callback
 * @returns {HTMLElement} - Toast element
 */
export function showToast(message, type = ToastType.INFO, duration = DEFAULT_DURATION, options = {}) {
    const { dismissible = true, onClick } = options;

    const container = getContainer();
    const toast = document.createElement('div');

    toast.className = `toast ${type}`;
    toast.innerHTML = `
        ${toastIcons[type] || toastIcons.info}
        <span>${escapeHtml(message)}</span>
    `;

    // Handle click to dismiss
    if (dismissible || onClick) {
        toast.style.cursor = 'pointer';
        toast.addEventListener('click', () => {
            if (onClick) onClick();
            dismissToast(toast);
        });
    }

    container.appendChild(toast);

    // Auto-dismiss after duration
    if (duration > 0) {
        setTimeout(() => dismissToast(toast), duration);
    }

    return toast;
}

/**
 * Dismiss a toast with animation
 *
 * @param {HTMLElement} toast - Toast element to dismiss
 */
export function dismissToast(toast) {
    if (!toast || toast.classList.contains('removing')) return;

    toast.classList.add('removing');

    // Remove after animation completes
    setTimeout(() => {
        if (toast.parentNode) {
            toast.parentNode.removeChild(toast);
        }
    }, 300);
}

/**
 * Clear all toasts
 */
export function clearAllToasts() {
    const container = document.getElementById(CONTAINER_ID);
    if (container) {
        const toasts = container.querySelectorAll('.toast');
        toasts.forEach(toast => dismissToast(toast));
    }
}

/**
 * Show success toast
 *
 * @param {string} message - Message to display
 * @param {number} [duration] - Duration in ms
 * @returns {HTMLElement} - Toast element
 */
export function showSuccess(message, duration) {
    return showToast(message, ToastType.SUCCESS, duration);
}

/**
 * Show error toast
 *
 * @param {string} message - Message to display
 * @param {number} [duration] - Duration in ms
 * @returns {HTMLElement} - Toast element
 */
export function showError(message, duration) {
    return showToast(message, ToastType.ERROR, duration);
}

/**
 * Show warning toast
 *
 * @param {string} message - Message to display
 * @param {number} [duration] - Duration in ms
 * @returns {HTMLElement} - Toast element
 */
export function showWarning(message, duration) {
    return showToast(message, ToastType.WARNING, duration);
}

/**
 * Show info toast
 *
 * @param {string} message - Message to display
 * @param {number} [duration] - Duration in ms
 * @returns {HTMLElement} - Toast element
 */
export function showInfo(message, duration) {
    return showToast(message, ToastType.INFO, duration);
}

// Export namespace object for convenience
export const Toast = {
    show: showToast,
    dismiss: dismissToast,
    clearAll: clearAllToasts,
    success: showSuccess,
    error: showError,
    warning: showWarning,
    info: showInfo,
    Type: ToastType
};
