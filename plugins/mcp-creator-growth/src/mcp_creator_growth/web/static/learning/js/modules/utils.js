/**
 * Utils Module
 * =============
 * Common utility functions including dual-layer clipboard copy strategy.
 */

// Note: showToast and i18n are imported dynamically to avoid circular dependencies
let _showToast = null;
let _i18n = null;

/**
 * Initialize dependencies (called after all modules are loaded)
 */
export function initUtilsDeps(showToastFn, i18nObj) {
    _showToast = showToastFn;
    _i18n = i18nObj;
}

/**
 * Dual-layer clipboard copy strategy
 * First tries modern Clipboard API, falls back to execCommand
 *
 * @param {string} text - Text to copy
 * @param {string} [successMsg] - Success message (optional)
 * @param {string} [errorMsg] - Error message (optional)
 * @returns {Promise<boolean>} - Whether copy was successful
 */
export async function copyToClipboard(text, successMsg, errorMsg) {
    const defaultSuccess = _i18n ? _i18n.t('toast.copySuccess') : 'Copied!';
    const defaultError = _i18n ? _i18n.t('toast.copyError') : 'Copy failed';
    successMsg = successMsg || defaultSuccess;
    errorMsg = errorMsg || defaultError;

    try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(text);
            if (_showToast) _showToast(successMsg, 'success');
            return true;
        } else {
            return fallbackCopy(text, successMsg, errorMsg);
        }
    } catch (err) {
        console.warn('Clipboard API failed, using fallback:', err);
        return fallbackCopy(text, successMsg, errorMsg);
    }
}

/**
 * Fallback copy using deprecated execCommand
 *
 * @param {string} text - Text to copy
 * @param {string} successMsg - Success message
 * @param {string} errorMsg - Error message
 * @returns {boolean} - Whether copy was successful
 */
export function fallbackCopy(text, successMsg, errorMsg) {
    try {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.cssText = 'position:fixed;left:-9999px;top:-9999px';
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        const success = document.execCommand('copy');
        document.body.removeChild(textarea);
        if (_showToast) _showToast(success ? successMsg : errorMsg, success ? 'success' : 'error');
        return success;
    } catch (err) {
        if (_showToast) _showToast(errorMsg, 'error');
        return false;
    }
}

/**
 * Debounce function - delays execution until after wait ms have elapsed
 *
 * @param {Function} func - Function to debounce
 * @param {number} wait - Wait time in ms
 * @returns {Function} - Debounced function
 */
export function debounce(func, wait) {
    let timeout;
    return function(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

/**
 * Throttle function - limits function calls to at most once per limit ms
 *
 * @param {Function} func - Function to throttle
 * @param {number} limit - Minimum time between calls in ms
 * @returns {Function} - Throttled function
 */
export function throttle(func, limit) {
    let inThrottle;
    return function(...args) {
        if (!inThrottle) {
            func.apply(this, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

/**
 * Generate a unique ID
 *
 * @param {string} [prefix='id'] - ID prefix
 * @returns {string} - Generated ID
 */
export function generateId(prefix = 'id') {
    return `${prefix}_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

/**
 * Format file size in human readable format
 *
 * @param {number} bytes - Size in bytes
 * @returns {string} - Formatted size
 */
export function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

/**
 * Escape HTML special characters to prevent XSS
 *
 * @param {string} text - Text to escape
 * @returns {string} - Escaped text
 */
export function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Format time ago from timestamp
 *
 * @param {number|Date} timestamp - Timestamp or Date object
 * @returns {string} - Formatted time ago string
 */
export function formatTimeAgo(timestamp) {
    const now = Date.now();
    const time = timestamp instanceof Date ? timestamp.getTime() : timestamp;
    const diff = Math.floor((now - time) / 1000);

    if (diff < 60) return 'Just now';
    if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} hours ago`;
    return `${Math.floor(diff / 86400)} days ago`;
}

/**
 * Deep clone an object
 *
 * @param {*} obj - Object to clone
 * @returns {*} - Cloned object
 */
export function deepClone(obj) {
    if (obj === null || typeof obj !== 'object') return obj;
    if (obj instanceof Date) return new Date(obj.getTime());
    if (obj instanceof Array) return obj.map(item => deepClone(item));
    if (typeof obj === 'object') {
        const cloned = {};
        for (const key in obj) {
            if (obj.hasOwnProperty(key)) {
                cloned[key] = deepClone(obj[key]);
            }
        }
        return cloned;
    }
    return obj;
}

/**
 * Wait for specified milliseconds
 *
 * @param {number} ms - Milliseconds to wait
 * @returns {Promise<void>}
 */
export function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Parse URL query parameters
 *
 * @param {string} [url] - URL to parse (defaults to current URL)
 * @returns {Object} - Query parameters object
 */
export function parseQueryParams(url) {
    const params = new URLSearchParams(url || window.location.search);
    const result = {};
    for (const [key, value] of params) {
        result[key] = value;
    }
    return result;
}

/**
 * Download data as a file
 *
 * @param {string|Blob} data - Data to download
 * @param {string} filename - Filename
 * @param {string} [mimeType='application/json'] - MIME type
 */
export function downloadFile(data, filename, mimeType = 'application/json') {
    const blob = data instanceof Blob ? data : new Blob([data], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}

// Export all utilities as a namespace object for convenience
export const Utils = {
    copyToClipboard,
    fallbackCopy,
    debounce,
    throttle,
    generateId,
    formatFileSize,
    escapeHtml,
    formatTimeAgo,
    deepClone,
    sleep,
    parseQueryParams,
    downloadFile
};
