/**
 * columns.js - LiteLLM Model Manager
 * Multi-column layout controls, collapsible sections, and persistent column collapse state.
 */

/**
 * Toggles an accordion section within a column (e.g. Selected vs Available models).
 * @param {string} sectionId - The DOM ID of the section container.
 */
function toggleSection(sectionId) {
    const sec = document.getElementById(sectionId);
    if (sec) {
        sec.classList.toggle('collapsed');
    }
}

/**
 * Toggles the collapsed state of a provider column (OpenRouter, Vertex AI, Local)
 * and persists the state to localStorage.
 * @param {string} colId - The DOM ID of the column element.
 */
function toggleColumn(colId) {
    const col = document.getElementById(colId);
    if (!col) return;
    col.classList.toggle('is-collapsed');

    try {
        const state = {
            or: document.getElementById('orColumn')?.classList.contains('is-collapsed') || false,
            vx: document.getElementById('vxColumn')?.classList.contains('is-collapsed') || false,
            local: document.getElementById('localColumn')?.classList.contains('is-collapsed') || false
        };
        const key = (window.STORAGE_KEYS && window.STORAGE_KEYS.COLLAPSED_COLS) || 'modelmanager_collapsed_cols';
        localStorage.setItem(key, JSON.stringify(state));
    } catch (e) {
        console.warn('Unable to persist column collapse state to localStorage:', e);
    }
}

/**
 * Restores the collapsed state of provider columns from localStorage upon application startup.
 */
function restoreColumnCollapseState() {
    try {
        const key = (window.STORAGE_KEYS && window.STORAGE_KEYS.COLLAPSED_COLS) || 'modelmanager_collapsed_cols';
        const saved = localStorage.getItem(key);
        if (saved) {
            const state = JSON.parse(saved);
            if (state.or) document.getElementById('orColumn')?.classList.add('is-collapsed');
            if (state.vx) document.getElementById('vxColumn')?.classList.add('is-collapsed');
            if (state.local) document.getElementById('localColumn')?.classList.add('is-collapsed');
        }
    } catch (e) {
        console.warn('Unable to restore column collapse state from localStorage:', e);
    }
}

// Expose globally for inline HTML event handlers and cross-module access
window.toggleSection = toggleSection;
window.toggleColumn = toggleColumn;
window.restoreColumnCollapseState = restoreColumnCollapseState;
