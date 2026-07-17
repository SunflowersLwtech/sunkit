/**
 * Error Handler Module
 * =====================
 * Centralized error handling with classification and user-friendly messages.
 */

import { showToast } from './toast.js';
import { i18n } from './i18n.js';

/**
 * Error types enum
 */
export const ErrorType = {
    NETWORK: 'network',
    TIMEOUT: 'timeout',
    SERVER: 'server',
    VALIDATION: 'validation',
    USER_CANCEL: 'user_cancel',
    UNKNOWN: 'unknown'
};

/**
 * Error severity levels
 */
export const ErrorSeverity = {
    LOW: 'low',
    MEDIUM: 'medium',
    HIGH: 'high',
    CRITICAL: 'critical'
};

/**
 * Classify an error based on its message/type
 *
 * @param {Error|string} error - Error object or message
 * @returns {string} - Error type from ErrorType enum
 */
export function classifyError(error) {
    const msg = (error.message || error || '').toLowerCase();

    // Network errors
    if (msg.includes('network') ||
        msg.includes('fetch') ||
        msg.includes('failed to fetch') ||
        msg.includes('net::') ||
        msg.includes('connection refused')) {
        return ErrorType.NETWORK;
    }

    // Timeout errors
    if (msg.includes('timeout') ||
        msg.includes('timed out') ||
        msg.includes('aborted')) {
        return ErrorType.TIMEOUT;
    }

    // Server errors
    if (msg.includes('server') ||
        msg.includes('500') ||
        msg.includes('502') ||
        msg.includes('503') ||
        msg.includes('504') ||
        msg.includes('internal error')) {
        return ErrorType.SERVER;
    }

    // Validation errors
    if (msg.includes('validation') ||
        msg.includes('invalid') ||
        msg.includes('400') ||
        msg.includes('422')) {
        return ErrorType.VALIDATION;
    }

    // User cancellation
    if (msg.includes('cancel') ||
        msg.includes('abort') && !msg.includes('timeout')) {
        return ErrorType.USER_CANCEL;
    }

    return ErrorType.UNKNOWN;
}

/**
 * Get user-friendly error message
 *
 * @param {Error|string} error - Error object or message
 * @returns {string} - Translated user-friendly message
 */
export function getUserMessage(error) {
    const type = classifyError(error);
    const translatedMsg = i18n.t(`errors.${type}`);

    // If we have a good translation, use it; otherwise show the original
    if (translatedMsg && !translatedMsg.startsWith('errors.')) {
        return translatedMsg;
    }

    return error.message || String(error);
}

/**
 * Get severity for an error type
 *
 * @param {string} errorType - Error type from ErrorType enum
 * @returns {string} - Severity level from ErrorSeverity enum
 */
export function getSeverity(errorType) {
    switch (errorType) {
        case ErrorType.NETWORK:
            return ErrorSeverity.HIGH;
        case ErrorType.SERVER:
            return ErrorSeverity.HIGH;
        case ErrorType.TIMEOUT:
            return ErrorSeverity.MEDIUM;
        case ErrorType.VALIDATION:
            return ErrorSeverity.LOW;
        case ErrorType.USER_CANCEL:
            return ErrorSeverity.LOW;
        default:
            return ErrorSeverity.MEDIUM;
    }
}

/**
 * Handle an error - logs and shows toast notification
 *
 * @param {Error|string} error - Error to handle
 * @param {string} [context=''] - Context where error occurred
 * @param {Object} [options={}] - Additional options
 * @param {boolean} [options.silent=false] - Whether to suppress toast
 * @param {boolean} [options.rethrow=false] - Whether to rethrow the error
 */
export function handleError(error, context = '', options = {}) {
    const { silent = false, rethrow = false } = options;

    const errorType = classifyError(error);
    const severity = getSeverity(errorType);
    const userMessage = getUserMessage(error);

    // Log to console with context
    const logPrefix = context ? `[${context}]` : '[Error]';
    console.error(logPrefix, {
        type: errorType,
        severity,
        message: error.message || error,
        stack: error.stack,
        timestamp: new Date().toISOString()
    });

    // Show toast unless silent or user cancelled
    if (!silent && errorType !== ErrorType.USER_CANCEL) {
        const toastType = severity === ErrorSeverity.HIGH || severity === ErrorSeverity.CRITICAL
            ? 'error'
            : 'warning';
        showToast(userMessage, toastType);
    }

    // Rethrow if requested
    if (rethrow) {
        throw error;
    }
}

/**
 * Create a wrapped async function with error handling
 *
 * @param {Function} fn - Async function to wrap
 * @param {string} [context=''] - Context for error messages
 * @returns {Function} - Wrapped function
 */
export function withErrorHandling(fn, context = '') {
    return async function(...args) {
        try {
            return await fn.apply(this, args);
        } catch (error) {
            handleError(error, context);
            return null;
        }
    };
}

/**
 * Retry an async operation with exponential backoff
 *
 * @param {Function} fn - Async function to retry
 * @param {Object} [options={}] - Retry options
 * @param {number} [options.maxRetries=3] - Maximum retry attempts
 * @param {number} [options.baseDelay=1000] - Base delay in ms
 * @param {string} [options.context=''] - Context for error messages
 * @returns {Promise<*>} - Result of successful call
 */
export async function retryWithBackoff(fn, options = {}) {
    const { maxRetries = 3, baseDelay = 1000, context = '' } = options;

    let lastError;

    for (let attempt = 0; attempt < maxRetries; attempt++) {
        try {
            return await fn();
        } catch (error) {
            lastError = error;
            const errorType = classifyError(error);

            // Don't retry user cancellations or validation errors
            if (errorType === ErrorType.USER_CANCEL || errorType === ErrorType.VALIDATION) {
                throw error;
            }

            // Calculate delay with exponential backoff
            const delay = baseDelay * Math.pow(2, attempt);

            console.warn(`[${context}] Attempt ${attempt + 1} failed, retrying in ${delay}ms...`, error.message);

            if (attempt < maxRetries - 1) {
                await new Promise(resolve => setTimeout(resolve, delay));
            }
        }
    }

    // All retries exhausted
    handleError(lastError, context);
    throw lastError;
}

// Export as namespace object for convenience
export const ErrorHandler = {
    ErrorType,
    ErrorSeverity,
    classifyError,
    getUserMessage,
    getSeverity,
    handleError,
    withErrorHandling,
    retryWithBackoff
};
