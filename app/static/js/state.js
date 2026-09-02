/**
 * state.js - LiteLLM Model Manager
 * Global state constants and helper utilities.
 */

const STORAGE_KEYS = {
    COLLAPSED_COLS: 'modelmanager_collapsed_cols'
};

/**
 * Smoothly scrolls the main window and all model column lists back to the top.
 */
function scrollToTop() {
    window.scrollTo({ top: 0, behavior: 'smooth' });
    document.querySelectorAll('.model-list').forEach(list => {
        list.scrollTo({ top: 0, behavior: 'smooth' });
    });
}

// Expose globally for inline event handlers and cross-module access
window.STORAGE_KEYS = STORAGE_KEYS;
window.scrollToTop = scrollToTop;
