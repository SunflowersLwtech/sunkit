/**
 * MCP Learning Sidecar - Main Application
 * =========================================
 * Entry point for the Learning Sidecar WebUI.
 */

import { i18n } from './modules/i18n.js';
import { showToast } from './modules/toast.js';
import { copyToClipboard, escapeHtml, downloadFile, parseQueryParams, initUtilsDeps } from './modules/utils.js';
import { handleError } from './modules/error-handler.js';
import { WebSocketManager, ConnectionState } from './modules/websocket-manager.js';
import { icons } from './modules/icons.js';

// Initialize utils dependencies to avoid circular imports
initUtilsDeps(showToast, i18n);

// ==================== Application State ====================
const state = {
    currentSession: null,
    selectedAnswers: {},
    currentScore: 0,
    startTime: Date.now(),
    isDark: false,
    wsManager: null,
    shownWarnings: new Set()
};

// ==================== Theme Management ====================
function toggleTheme() {
    state.isDark = !state.isDark;
    document.body.classList.toggle('dark', state.isDark);
    document.getElementById('moon-icon').style.display = state.isDark ? 'none' : 'block';
    document.getElementById('sun-icon').style.display = state.isDark ? 'block' : 'none';
    localStorage.setItem('mcp-theme', state.isDark ? 'dark' : 'light');
}

function initTheme() {
    const saved = localStorage.getItem('mcp-theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    state.isDark = saved ? saved === 'dark' : prefersDark;
    document.body.classList.toggle('dark', state.isDark);
    document.getElementById('moon-icon').style.display = state.isDark ? 'none' : 'block';
    document.getElementById('sun-icon').style.display = state.isDark ? 'block' : 'none';
}

// ==================== Connection Status ====================
function updateConnectionStatus(connectionState) {
    const indicator = document.getElementById('connection-indicator');
    indicator.classList.remove('disconnected', 'reconnecting');

    switch (connectionState) {
        case ConnectionState.DISCONNECTED:
        case ConnectionState.ERROR:
            indicator.classList.add('disconnected');
            break;
        case ConnectionState.RECONNECTING:
            indicator.classList.add('reconnecting');
            break;
    }
}

// ==================== Session Loading ====================
function getSessionIdFromUrl() {
    const params = parseQueryParams();
    return params.session;
}

async function loadSession() {
    const sessionId = getSessionIdFromUrl();

    try {
        const endpoint = sessionId
            ? `/api/learning/session/${sessionId}`
            : '/api/learning/current';

        const resp = await fetch(endpoint);

        if (!resp.ok) {
            throw new Error('Session not found');
        }

        const data = await resp.json();

        if (data.has_session === false) {
            showToast(i18n.t('toast.noSession'), 'warning');
            return;
        }

        state.currentSession = data.data || data;
        renderSession(state.currentSession);
        showSessionWarnings(state.currentSession);

        // Mark session as started
        if (state.currentSession.session_id) {
            fetch(`/api/learning/session/${state.currentSession.session_id}/start`, { method: 'POST' });
            state.startTime = Date.now();
        }

    } catch (e) {
        handleError(e, 'loadSession');
    }
}

function showSessionWarnings(session) {
    if (!session?.warnings?.length) return;
    session.warnings.forEach((warning) => {
        if (state.shownWarnings.has(warning)) return;
        state.shownWarnings.add(warning);
        const message = i18n.t(`toast.${warning}`);
        showToast(message, 'warning');
    });
}

// ==================== Utility Functions ====================
/**
 * Normalize answer to label format (A, B, C, D)
 * Handles various formats: "A", "B", 0, 1, "0", "1", etc.
 */
function normalizeAnswerToLabel(answer) {
    if (typeof answer === 'string') {
        // Already a label like "A", "B", "C", "D"
        if (/^[A-Da-d]$/.test(answer)) {
            return answer.toUpperCase();
        }
        // Numeric string like "0", "1", "2"
        const num = parseInt(answer, 10);
        if (!isNaN(num) && num >= 0 && num <= 3) {
            return String.fromCharCode(65 + num);
        }
    }
    // Numeric value like 0, 1, 2
    if (typeof answer === 'number' && answer >= 0 && answer <= 3) {
        return String.fromCharCode(65 + answer);
    }
    // Default: return as-is (uppercase if string)
    return typeof answer === 'string' ? answer.toUpperCase() : String(answer);
}

// ==================== Rendering ====================
function renderSession(session) {
    updateStatus(session.status);
    document.getElementById('session-id-display').textContent = session.session_id?.slice(0, 8) || 'N/A';
    document.getElementById('session-id-display').setAttribute('data-full-id', session.session_id || '');

    renderSummary(session);
    renderTerms(session.terms || []);
    renderReasoning(session.reasoning);
    renderQuizzes(session.quizzes || []);
}

function renderSummary(session) {
    const badgesContainer = document.getElementById('summary-badges');
    const summaryText = document.getElementById('summary-text');
    const skeletonContainer = document.getElementById('summary-text-container');

    let badges = `<span class="badge action">${i18n.t('badges.learningSession')}</span>`;

    if (session.focus_areas) {
        session.focus_areas.forEach(area => {
            badges += `<span class="badge file">${icons.file}${escapeHtml(area)}</span>`;
        });
    }

    badgesContainer.innerHTML = badges;
    summaryText.textContent = session.summary || i18n.t('summary.noData');

    // Hide skeleton, show actual content
    if (skeletonContainer) {
        skeletonContainer.style.display = 'none';
    }
    summaryText.style.display = 'block';
}

function renderTerms(terms) {
    const section = document.getElementById('terms-section');
    const container = document.getElementById('terms-container');

    if (!terms || terms.length === 0) {
        section.style.display = 'none';
        return;
    }

    section.style.display = 'block';

    // Format domain name for display
    const formatDomain = (domain) => {
        return domain
            .replace(/_/g, ' ')
            .replace(/\b\w/g, l => l.toUpperCase());
    };

    // Render terms - expects single-language format from server
    container.innerHTML = terms.map(term => `
        <div class="term-card" data-domain="${escapeHtml(term.domain || '')}">
            <div class="term-header">
                <div class="term-name">
                    <span>${escapeHtml(term.term)}</span>
                </div>
                <span class="term-domain">${escapeHtml(formatDomain(term.domain || 'general'))}</span>
            </div>
            <div class="term-definition">
                ${escapeHtml(term.definition)}
            </div>
        </div>
    `).join('');
}

function renderReasoning(reasoning) {
    const container = document.getElementById('reasoning-container');

    if (!reasoning) {
        container.innerHTML = `<p style="color: hsl(var(--muted-foreground)); padding: 16px;">${i18n.t('reasoning.noData')}</p>`;
        return;
    }

    const r = reasoning;
    container.innerHTML = `
        <div class="card reasoning-card card-glow">
            <div class="card-header">
                <div class="card-header-left" onclick="window.app.toggleCard(this)">
                    <span class="chevron open">${icons.chevron}</span>
                    <span class="card-header-title">${i18n.t('reasoning.title')}</span>
                </div>
                <button class="icon-btn" onclick="window.app.copyReasoning(event)" title="${i18n.t('buttons.copy')}">
                    ${icons.copy}
                </button>
            </div>
            <div class="collapsible-content open">
                <div class="card-content">
                    <div class="timeline">
                        <div class="timeline-item">
                            <div class="timeline-dot goal">${icons.target}</div>
                            <div class="timeline-label goal">${i18n.t('reasoning.goal')}</div>
                            <div class="timeline-value">${escapeHtml(r.goal || 'N/A')}</div>
                        </div>
                        <div class="timeline-item">
                            <div class="timeline-dot trigger">${icons.zap}</div>
                            <div class="timeline-label trigger">${i18n.t('reasoning.trigger')}</div>
                            <div class="timeline-value code">${escapeHtml(r.trigger || 'N/A')}</div>
                        </div>
                        <div class="timeline-item">
                            <div class="timeline-dot mechanism">${icons.cog}</div>
                            <div class="timeline-label mechanism">${i18n.t('reasoning.mechanism')}</div>
                            <div class="timeline-value">${escapeHtml(r.mechanism || 'N/A')}</div>
                        </div>
                        <div class="timeline-item">
                            <div class="timeline-dot alternative">${icons.scale}</div>
                            <div class="timeline-label alternative">${i18n.t('reasoning.alternative')}</div>
                            <div class="timeline-value">${escapeHtml(r.alternatives || 'N/A')}</div>
                        </div>
                    </div>
                    <div class="risk-next-grid">
                        <div class="risk-item">
                            ${icons.alert}
                            <div>
                                <div class="label">${i18n.t('reasoning.risk')}</div>
                                <div class="value">${escapeHtml(r.risks || 'N/A')}</div>
                            </div>
                        </div>
                        <div class="next-item">
                            ${icons.search}
                            <div>
                                <div class="label">${i18n.t('reasoning.nextStep')}</div>
                                <div class="value">Review and verify understanding</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function renderQuizzes(quizzes) {
    const container = document.getElementById('quiz-container');

    if (!quizzes.length) {
        container.innerHTML = `<p style="color: hsl(var(--muted-foreground)); padding: 16px;">${i18n.t('quiz.noData')}</p>`;
        document.getElementById('submit-btn').disabled = false;
        return;
    }

    container.innerHTML = quizzes.map((quiz, index) => `
        <div class="card quiz-card card-glow" id="quiz-${index}" data-index="${index}">
            <div class="card-header">
                <div class="card-header-left" onclick="window.app.toggleCard(this)">
                    <span class="chevron open">${icons.chevron}</span>
                    <span class="lightbulb">${icons.lightbulb}</span>
                    <span class="card-header-title">${i18n.t('quiz.question')} ${index + 1}</span>
                </div>
                <span class="result-badge" id="quiz-result-${index}"></span>
            </div>
            <div class="collapsible-content open">
                <div class="card-content">
                    <p class="quiz-question-text">${escapeHtml(quiz.question)}</p>
                    <div class="quiz-options" id="quiz-options-${index}">
                        ${quiz.options.map((opt, optIndex) => {
        const label = String.fromCharCode(65 + optIndex);
        // Normalize the correct answer to compare properly
        const correctLabel = normalizeAnswerToLabel(quiz.answer);
        const isCorrect = label === correctLabel;
        return `
                                <div class="quiz-option" onclick="window.app.selectAnswer(${index}, '${label}', ${isCorrect})" data-label="${label}">
                                    <span class="option-label">${label}</span>
                                    <span class="option-text">${escapeHtml(opt)}</span>
                                </div>
                            `;
    }).join('')}
                    </div>
                    <div class="quiz-feedback" id="quiz-feedback-${index}" style="display: none;">
                        <div class="feedback-header">
                            <span class="feedback-icon"></span>
                            <span class="feedback-title"></span>
                        </div>
                        <p class="feedback-text">${escapeHtml(quiz.explanation || '')}</p>
                    </div>
                </div>
            </div>
        </div>
    `).join('');
}

// ==================== Interactions ====================
function toggleCard(header) {
    const card = header.closest('.card');
    const content = card.querySelector('.collapsible-content');
    const chevron = header.querySelector('.chevron');
    const isOpen = content.classList.contains('open');
    content.classList.toggle('open', !isOpen);
    chevron.classList.toggle('open', !isOpen);
}

function selectAnswer(quizIndex, answer, isCorrect) {
    if (state.selectedAnswers[quizIndex] !== undefined) return;
    state.selectedAnswers[quizIndex] = answer;

    const optionsContainer = document.getElementById(`quiz-options-${quizIndex}`);
    const options = optionsContainer.querySelectorAll('.quiz-option');

    // Get the correct answer and normalize it to a label (A, B, C, D)
    const correctAnswer = state.currentSession.quizzes[quizIndex].answer;
    const correctLabel = normalizeAnswerToLabel(correctAnswer);

    options.forEach(opt => {
        const label = opt.dataset.label;
        opt.classList.add('disabled');
        if (label === answer) {
            opt.classList.add(isCorrect ? 'correct' : 'wrong');
            // Wrap icon with option-icon class for proper sizing
            const iconClass = isCorrect ? 'check' : 'x';
            opt.insertAdjacentHTML('beforeend', `<span class="option-icon ${iconClass}">${isCorrect ? icons.checkSimple : icons.xSimple}</span>`);
        } else if (label === correctLabel && !isCorrect) {
            // Show correct answer when user selected wrong option
            opt.classList.add('correct');
            opt.insertAdjacentHTML('beforeend', `<span class="option-icon check">${icons.checkSimple}</span>`);
        }
    });

    const feedback = document.getElementById(`quiz-feedback-${quizIndex}`);
    const feedbackIcon = feedback.querySelector('.feedback-icon');
    const feedbackTitle = feedback.querySelector('.feedback-title');
    feedback.classList.remove('correct', 'incorrect');
    feedback.classList.add(isCorrect ? 'correct' : 'incorrect');
    // Use simple icons for feedback too
    feedbackIcon.innerHTML = isCorrect ? icons.checkSimple : icons.xSimple;
    feedbackTitle.textContent = isCorrect ? i18n.t('quiz.correct') : i18n.t('quiz.incorrect');
    feedback.style.display = 'block';

    const resultBadge = document.getElementById(`quiz-result-${quizIndex}`);
    resultBadge.textContent = isCorrect ? '✓' : '✗';
    resultBadge.classList.add(isCorrect ? 'correct' : 'incorrect');

    updateScore();

    const totalQuestions = state.currentSession?.quizzes?.length || 0;
    if (Object.keys(state.selectedAnswers).length >= totalQuestions) {
        document.getElementById('submit-btn').disabled = false;
    }
}

function updateScore() {
    if (!state.currentSession?.quizzes) return;
    let score = 0;
    state.currentSession.quizzes.forEach((quiz, index) => {
        const correctLabel = normalizeAnswerToLabel(quiz.answer);
        if (state.selectedAnswers[index] === correctLabel) score++;
    });
    // Score elements removed - just track internally
    state.currentScore = score;
}

function updateStatus(status) {
    const badge = document.getElementById('status-badge');
    const text = document.getElementById('status-text');
    badge.classList.remove('waiting', 'active', 'completed', 'error', 'reconnecting');

    switch (status) {
        case 'waiting':
            badge.classList.add('waiting');
            text.textContent = i18n.t('status.waiting');
            break;
        case 'in_progress':
            badge.classList.add('active');
            text.textContent = i18n.t('status.active');
            break;
        case 'completed':
            badge.classList.add('completed');
            text.textContent = i18n.t('status.completed');
            break;
        default:
            badge.classList.add('error');
            text.textContent = status;
    }
}

// ==================== Actions ====================
async function submitLearning() {
    if (!state.currentSession) {
        showToast(i18n.t('toast.noSession'), 'error');
        return;
    }

    const score = state.currentScore || 0;
    const answers = Object.entries(state.selectedAnswers).map(([q, a]) => ({
        question: parseInt(q),
        answer: a
    }));

    try {
        const resp = await fetch('/api/learning/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: state.currentSession.session_id,
                answers: answers,
                score: score
            })
        });

        const data = await resp.json();

        if (data.success) {
            updateStatus('completed');
            showToast(i18n.t('toast.submitSuccess'), 'success');
            document.getElementById('submit-btn').disabled = true;
            document.getElementById('submit-btn').innerHTML = `${icons.check} <span>${i18n.t('buttons.completed')}</span>`;
        } else {
            showToast(i18n.t('toast.submitError') + ': ' + data.message, 'error');
        }
    } catch (e) {
        handleError(e, 'submitLearning');
    }
}

async function cancelSession() {
    if (!state.currentSession) return;
    if (!confirm(i18n.t('confirm.cancel'))) return;

    try {
        await fetch(`/api/learning/session/${state.currentSession.session_id}/cancel`, { method: 'POST' });
        updateStatus('cancelled');
        showToast(i18n.t('toast.cancelSuccess'), 'success');
    } catch (e) {
        handleError(e, 'cancelSession');
    }
}

function copySessionId() {
    const fullId = document.getElementById('session-id-display').getAttribute('data-full-id');
    if (fullId) {
        copyToClipboard(fullId, i18n.t('toast.sessionIdCopied'));
    }
}

function copySummary() {
    if (!state.currentSession) return;
    const text = `### Learning Session Summary\n${state.currentSession.summary || 'No summary available'}`;
    copyToClipboard(text, i18n.t('toast.summaryCopied'));
}

function copyReasoning(event) {
    event.stopPropagation();
    if (!state.currentSession?.reasoning) return;
    const r = state.currentSession.reasoning;
    const text = `### 5-Why Reasoning\n- **Goal**: ${r.goal}\n- **Trigger**: ${r.trigger}\n- **Mechanism**: ${r.mechanism}\n- **Alternative**: ${r.alternatives}\n- **Risk**: ${r.risks}`;
    copyToClipboard(text, i18n.t('toast.reasoningCopied'));
}

function exportSession() {
    if (!state.currentSession) {
        showToast(i18n.t('toast.noSession'), 'warning');
        return;
    }
    const data = JSON.stringify(state.currentSession, null, 2);
    const filename = `learning_session_${state.currentSession.session_id?.slice(0, 8) || 'export'}.json`;
    downloadFile(data, filename);
    showToast(i18n.t('toast.exportSuccess'), 'success');
}

// ==================== Keyboard Shortcuts ====================
function initKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            e.preventDefault();
            if (!document.getElementById('submit-btn').disabled) {
                submitLearning();
            }
        }
    });
}

// ==================== WebSocket Setup ====================
function initWebSocket() {
    state.wsManager = new WebSocketManager({
        path: '/ws/learning',
        onMessage: (data) => {
            switch (data.type) {
                case 'session_data':
                    state.currentSession = data.data;
                    renderSession(state.currentSession);
                    showSessionWarnings(state.currentSession);
                    break;
                case 'status':
                    updateStatus(data.status);
                    break;
                case 'notification':
                    showToast(data.content, data.severity || 'info');
                    break;
            }
        },
        onStateChange: updateConnectionStatus
    });

    // Connect WebSocket for real-time updates
    state.wsManager.connect(getSessionIdFromUrl());
}

// ==================== Initialize ====================
async function init() {
    // Init i18n
    await i18n.init();

    // Language selector
    const langSelect = document.getElementById('lang-select');
    langSelect.value = i18n.getCurrentLanguage();
    langSelect.addEventListener('change', async (e) => {
        await i18n.setLanguage(e.target.value);
        if (state.currentSession) renderSession(state.currentSession);
    });

    // Theme
    initTheme();
    document.getElementById('theme-toggle').addEventListener('click', toggleTheme);

    // Export button
    document.getElementById('export-btn').addEventListener('click', exportSession);

    // Action buttons
    document.getElementById('submit-btn').addEventListener('click', submitLearning);
    document.getElementById('cancel-btn').addEventListener('click', cancelSession);
    document.getElementById('session-id-display').addEventListener('click', copySessionId);
    document.getElementById('copy-summary-btn').addEventListener('click', copySummary);

    // Keyboard shortcuts
    initKeyboardShortcuts();

    // WebSocket
    initWebSocket();

    // Load session
    await loadSession();
}

// ==================== Export for HTML onclick handlers ====================
window.app = {
    toggleCard,
    selectAnswer,
    copyReasoning,
    copySessionId,
    copySummary,
    exportSession,
    submitLearning,
    cancelSession
};

// ==================== Start Application ====================
document.addEventListener('DOMContentLoaded', init);
