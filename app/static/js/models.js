/**
 * models.js - LiteLLM Model Manager
 * Model selection handling, token formatting, live endpoint testing, and orphaned model synthesis.
 */

/**
 * Formats a raw token number into a compact human-readable string (e.g. 128K, 1M, 2M).
 * @param {number|string} num - The token limit count.
 * @returns {string} Formatted token count string.
 */
function formatTokens(num) {
    if (!num || num === 0 || num === '0') return '0';
    const parsed = typeof num === 'number' ? num : parseFloat(num);
    if (isNaN(parsed) || parsed === 0) return '0';
    if (parsed >= 1000000) return (parsed / 1000000).toFixed(1).replace(/\.0$/, '') + 'M';
    if (parsed >= 1000) return (parsed / 1000).toFixed(1).replace(/\.0$/, '') + 'K';
    return parsed.toString();
}

/**
 * Creates a DOM node for an orphaned / unavailable model that is present in the configuration
 * or import payload but not returned in the active catalog.
 * @param {string} id - The model identifier (e.g. "openrouter/anthropic/claude-3-opus").
 * @param {string} [note] - Descriptive message for the model status.
 * @returns {HTMLDivElement} Constructed model card element.
 */
function createOrphanedModel(id, note) {
    const isVertex = id.startsWith('vertex_ai/');
    const isLocal = id.startsWith('local/');
    let brand = 'other';
    let provClass = 'provider-openrouter';
    let provName = 'OPENROUTER';
    if (isVertex) {
        brand = 'google';
        provClass = 'provider-vertex';
        provName = 'VERTEX';
    } else if (isLocal) {
        brand = 'ollama';
        provClass = 'provider-local';
        provName = 'LOCAL';
    }

    const description = note || 'Model in config but no longer returned by provider. Uncheck to remove.';

    const div = document.createElement('div');
    div.className = 'model-item selected orphaned-model';
    div.style.backgroundColor = 'rgba(248, 113, 113, 0.12)';
    div.style.borderColor = '#f87171';
    div.style.borderLeft = '3px solid #f87171';
    div.dataset.name = id;
    div.dataset.id = id;
    div.dataset.brand = brand;
    div.dataset.price = '0';
    div.dataset.popularity = '-1';
    div.innerHTML = `
        <div class="model-checkbox-wrap">
            <input type="checkbox" name="models" value="${id}" checked onchange="handleModelToggle(this)">
        </div>
        <div class="model-info">
            <div class="model-header-row">
                <div class="model-title-wrap">
                    <span class="model-tier tier-frontier" style="background: rgba(248, 113, 113, 0.2); color: #f87171; border-color: #f87171;">UNAVAILABLE</span>
                    <span class="model-name" style="color: #f87171; font-weight: bold;" title="${id}">${id}</span>
                    <span class="model-brand">${brand}</span>
                    <span class="provider-tag ${provClass}">${provName}</span>
                </div>
            </div>
            <div class="model-id">${description}</div>
            <div class="model-meta-row">
                <span class="model-specs">In: ? · Out: ?</span>
            </div>
        </div>
    `;
    return div;
}

/**
 * Handles toggling a model's selection checkbox, moving its card between Selected and Available lists.
 * @param {HTMLInputElement} checkbox - The checkbox element.
 */
function handleModelToggle(checkbox) {
    const item = checkbox.closest('.model-item');
    if (!item) return;

    const isVertex = (item.dataset.id || '').startsWith('vertex_ai/');
    const isLocal = (item.dataset.id || '').startsWith('local/');
    let selectedList = document.getElementById('orSelectedList');
    let availableList = document.getElementById('orAvailableList');
    if (isVertex) {
        selectedList = document.getElementById('vxSelectedList');
        availableList = document.getElementById('vxAvailableList');
    } else if (isLocal) {
        selectedList = document.getElementById('localSelectedList');
        availableList = document.getElementById('localAvailableList');
    }

    if (checkbox.checked) {
        item.classList.add('selected');
        if (selectedList) selectedList.appendChild(item);
    } else {
        item.classList.remove('selected');
        if (availableList) availableList.appendChild(item);
    }

    if (typeof applyAllFilters === 'function') {
        applyAllFilters();
    } else if (window.applyAllFilters) {
        window.applyAllFilters();
    }
}

/**
 * Sends a test inference probe request to the backend for a specific model ID.
 * @param {string} modelId - The model identifier.
 */
async function testModel(modelId) {
    const safeId = 'item-' + modelId.replaceAll('/', '-').replaceAll('.', '-').replaceAll(':', '-');
    const item = document.getElementById(safeId);
    if (!item) return;
    const btn = item.querySelector('.btn-test');
    if (!btn) return;
    const originalText = btn.innerText;
    btn.innerText = '...';
    btn.disabled = true;

    try {
        const formData = new FormData();
        formData.append('model_id', modelId);
        const resp = await fetch('/test', { method: 'POST', body: formData });
        const result = await resp.json();
        if (result.status === 'success') {
            btn.innerText = 'OK';
            btn.style.backgroundColor = 'var(--success)';
        } else {
            btn.innerText = 'FAIL';
            btn.style.backgroundColor = 'var(--danger)';
            console.error(result.message);
        }
    } catch (e) {
        btn.innerText = 'ERR';
    } finally {
        if (btn.innerText !== 'OK') {
            setTimeout(() => {
                btn.innerText = originalText;
                btn.disabled = false;
                btn.style.backgroundColor = '';
            }, 3000);
        }
    }
}

// Expose globally for inline HTML event handlers and cross-module access
window.formatTokens = formatTokens;
window.createOrphanedModel = createOrphanedModel;
window.handleModelToggle = handleModelToggle;
window.testModel = testModel;
