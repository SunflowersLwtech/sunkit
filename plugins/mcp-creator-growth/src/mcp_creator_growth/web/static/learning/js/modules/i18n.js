/**
 * Internationalization (i18n) Module
 * ====================================
 * Multi-language support with auto-detection and dynamic loading.
 */

/**
 * Supported languages
 */
export const SupportedLanguages = {
    EN: 'en',
    ZH_CN: 'zh-CN',
    ZH_TW: 'zh-TW'
};

/**
 * Default language
 */
const DEFAULT_LANGUAGE = SupportedLanguages.EN;

/**
 * Local storage key for language preference
 */
const STORAGE_KEY = 'mcp-learning-lang';

/**
 * i18n class for internationalization
 */
class I18n {
    constructor() {
        this.currentLang = DEFAULT_LANGUAGE;
        this.translations = {};
        this.loadedLanguages = new Set();
        this.listeners = [];
    }

    /**
     * Initialize i18n with language detection and loading
     *
     * @returns {Promise<void>}
     */
    async init() {
        // Detect and set language
        this.currentLang = this.detectLanguage();

        // Load the current language
        await this.loadLanguage(this.currentLang);

        // Update UI
        this.updateUI();
    }

    /**
     * Detect preferred language
     *
     * @returns {string} - Detected language code
     */
    detectLanguage() {
        // Check localStorage first
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved && Object.values(SupportedLanguages).includes(saved)) {
            return saved;
        }

        // Check navigator language
        const navLang = navigator.language || navigator.userLanguage || '';

        if (navLang.startsWith('zh')) {
            // Distinguish between simplified and traditional Chinese
            if (navLang.includes('TW') || navLang.includes('HK') || navLang.includes('Hant')) {
                return SupportedLanguages.ZH_TW;
            }
            return SupportedLanguages.ZH_CN;
        }

        // Default to English
        return DEFAULT_LANGUAGE;
    }

    /**
     * Load language translations from JSON file
     *
     * @param {string} lang - Language code
     * @returns {Promise<Object>} - Loaded translations
     */
    async loadLanguage(lang) {
        if (this.loadedLanguages.has(lang)) {
            return this.translations[lang];
        }

        try {
            const response = await fetch(`/static/locales/${lang}.json`);
            if (!response.ok) {
                throw new Error(`Failed to load ${lang}.json`);
            }

            const data = await response.json();
            this.translations[lang] = data;
            this.loadedLanguages.add(lang);

            return data;
        } catch (error) {
            console.warn(`Failed to load language ${lang}, falling back to inline:`, error);

            // Use inline fallback translations
            this.translations[lang] = this.getInlineTranslations(lang);
            this.loadedLanguages.add(lang);

            return this.translations[lang];
        }
    }

    /**
     * Get inline fallback translations
     *
     * @param {string} lang - Language code
     * @returns {Object} - Inline translations
     */
    getInlineTranslations(lang) {
        const translations = {
            en: {
                app: { title: 'Learning Sidecar' },
                status: { waiting: 'Waiting', active: 'In Progress', completed: 'Completed', error: 'Error', reconnecting: 'Reconnecting...' },
                summary: { title: 'Session Summary', loading: 'Loading...', noData: 'No data available' },
                reasoning: { title: 'Reasoning Insights (5-Why)', goal: 'Goal', trigger: 'Trigger', mechanism: 'Mechanism', alternative: 'Alternative', risk: 'Risk', nextStep: 'Next Step', noData: 'No data' },
                quiz: { title: 'Quick Quizzes', noData: 'No quizzes', correct: 'Correct!', incorrect: 'Not quite...' },
                progress: { label: "Today's Progress", correct: 'Correct' },
                buttons: { cancel: 'Cancel', submit: 'Complete Learning', completed: 'Completed' },
                shortcuts: { submit: 'Submit', copy: 'Copy' },
                badges: { loading: 'Loading...', learningSession: 'Learning Session' },
                toast: {
                    copySuccess: 'Copied!',
                    copyError: 'Copy failed',
                    exportSuccess: 'Exported!',
                    submitSuccess: 'Completed!',
                    noSession: 'No session',
                    reconnected: 'Reconnected!',
                    sessionStorageUnavailable: 'Session storage is unavailable. Your progress will not be saved.'
                },
                errors: { network: 'Network error', timeout: 'Timeout', server: 'Server error', unknown: 'Unknown error' }
            },
            'zh-CN': {
                app: { title: '学习助手' },
                status: { waiting: '等待中', active: '进行中', completed: '已完成', error: '错误', reconnecting: '重连中...' },
                summary: { title: '会话摘要', loading: '加载中...', noData: '无数据' },
                reasoning: { title: '推理洞察 (5-Why)', goal: '目标', trigger: '触发', mechanism: '机制', alternative: '替代方案', risk: '风险', nextStep: '下一步', noData: '无数据' },
                quiz: { title: '快速测验', noData: '无测验', correct: '正确!', incorrect: '不太对...' },
                progress: { label: '今日进度', correct: '正确' },
                buttons: { cancel: '取消', submit: '完成学习', completed: '已完成' },
                shortcuts: { submit: '提交', copy: '复制' },
                badges: { loading: '加载中...', learningSession: '学习会话' },
                toast: {
                    copySuccess: '已复制!',
                    copyError: '复制失败',
                    exportSuccess: '已导出!',
                    submitSuccess: '完成!',
                    noSession: '无会话',
                    reconnected: '已重连!',
                    sessionStorageUnavailable: '会话存储不可用，你的进度将不会保存。'
                },
                errors: { network: '网络错误', timeout: '超时', server: '服务器错误', unknown: '未知错误' }
            },
            'zh-TW': {
                app: { title: '學習助手' },
                status: { waiting: '等待中', active: '進行中', completed: '已完成', error: '錯誤', reconnecting: '重連中...' },
                summary: { title: '會話摘要', loading: '載入中...', noData: '無資料' },
                reasoning: { title: '推理洞察 (5-Why)', goal: '目標', trigger: '觸發', mechanism: '機制', alternative: '替代方案', risk: '風險', nextStep: '下一步', noData: '無資料' },
                quiz: { title: '快速測驗', noData: '無測驗', correct: '正確!', incorrect: '不太對...' },
                progress: { label: '今日進度', correct: '正確' },
                buttons: { cancel: '取消', submit: '完成學習', completed: '已完成' },
                shortcuts: { submit: '提交', copy: '複製' },
                badges: { loading: '載入中...', learningSession: '學習會話' },
                toast: {
                    copySuccess: '已複製!',
                    copyError: '複製失敗',
                    exportSuccess: '已匯出!',
                    submitSuccess: '完成!',
                    noSession: '無會話',
                    reconnected: '已重連!',
                    sessionStorageUnavailable: '會話儲存不可用，你的進度將不會保存。'
                },
                errors: { network: '網路錯誤', timeout: '逾時', server: '伺服器錯誤', unknown: '未知錯誤' }
            }
        };

        return translations[lang] || translations.en;
    }

    /**
     * Get translation by key
     *
     * @param {string} key - Translation key (dot-separated, e.g., 'toast.copySuccess')
     * @param {Object} [params] - Interpolation parameters
     * @returns {string} - Translated string
     */
    t(key, params) {
        const keys = key.split('.');
        let value = this.translations[this.currentLang];

        // Traverse the key path
        for (const k of keys) {
            value = value?.[k];
            if (value === undefined) break;
        }

        // Fallback to English if not found
        if (value === undefined && this.currentLang !== DEFAULT_LANGUAGE) {
            value = this.translations[DEFAULT_LANGUAGE];
            for (const k of keys) {
                value = value?.[k];
                if (value === undefined) break;
            }
        }

        // Return key if still not found
        if (value === undefined) {
            console.warn(`Translation not found: ${key}`);
            return key;
        }

        // Handle interpolation
        if (params && typeof value === 'string') {
            for (const [paramKey, paramValue] of Object.entries(params)) {
                value = value.replace(new RegExp(`\\{${paramKey}\\}`, 'g'), paramValue);
            }
        }

        return value;
    }

    /**
     * Set current language
     *
     * @param {string} lang - Language code
     * @returns {Promise<void>}
     */
    async setLanguage(lang) {
        if (!Object.values(SupportedLanguages).includes(lang)) {
            console.warn(`Unsupported language: ${lang}`);
            return;
        }

        // Load language if not already loaded
        await this.loadLanguage(lang);

        // Update current language
        this.currentLang = lang;

        // Save to localStorage
        localStorage.setItem(STORAGE_KEY, lang);

        // Update UI
        this.updateUI();

        // Notify listeners
        this.notifyListeners();
    }

    /**
     * Update all elements with data-i18n attribute
     */
    updateUI() {
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            const translated = this.t(key);

            // Handle different element types
            if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
                el.placeholder = translated;
            } else {
                el.textContent = translated;
            }
        });

        // Update document title
        document.title = this.t('app.title');
    }

    /**
     * Add language change listener
     *
     * @param {Function} callback - Callback function
     * @returns {Function} - Unsubscribe function
     */
    onLanguageChange(callback) {
        this.listeners.push(callback);
        return () => {
            this.listeners = this.listeners.filter(cb => cb !== callback);
        };
    }

    /**
     * Notify all listeners of language change
     */
    notifyListeners() {
        this.listeners.forEach(callback => {
            try {
                callback(this.currentLang);
            } catch (error) {
                console.error('Language change listener error:', error);
            }
        });
    }

    /**
     * Get current language
     *
     * @returns {string} - Current language code
     */
    getCurrentLanguage() {
        return this.currentLang;
    }

    /**
     * Get all supported languages
     *
     * @returns {Object} - Supported languages object
     */
    getSupportedLanguages() {
        return { ...SupportedLanguages };
    }
}

// Create singleton instance
export const i18n = new I18n();

// Export class for testing
export { I18n };
