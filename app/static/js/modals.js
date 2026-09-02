/**
 * modals.js - LiteLLM Model Manager
 * Dialogs, settings management, selection export/import, health check triggers, and proxy restart.
 */

/**
 * Exports currently selected model IDs into a downloadable JSON file.
 */
function exportSelections() {
    const selectedCheckboxes = document.querySelectorAll('input[name="models"]:checked');
    const selectedIds = Array.from(selectedCheckboxes).map(cb => cb.value);

    if (selectedIds.length === 0) {
        alert('No models currently selected to export.');
        return;
    }

    const versionEl = document.querySelector('.header-title small');
    const version = versionEl && versionEl.innerText ? versionEl.innerText.replace(/[^\d.]/g, '') : '1.0';

    const exportData = {
        app: "LiteLLM Model Manager",
        version: version || "1.0",
        exported_at: new Date().toISOString(),
        count: selectedIds.length,
        selected_models: selectedIds
    };

    const jsonString = JSON.stringify(exportData, null, 2);
    const blob = new Blob([jsonString], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const dateStr = new Date().toISOString().slice(0, 10);
    a.href = url;
    a.download = `litellm_selected_models_${dateStr}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

/**
 * Opens the Import Model Selection modal dialog.
 */
function openImportModal() {
    const txt = document.getElementById('importTextarea');
    const file = document.getElementById('importFileInput');
    const modal = document.getElementById('importModal');
    if (txt) txt.value = '';
    if (file) file.value = '';
    if (modal) modal.style.display = 'block';
}

/**
 * Closes the Import Model Selection modal dialog.
 */
function closeImportModal() {
    const modal = document.getElementById('importModal');
    if (modal) modal.style.display = 'none';
}

/**
 * Handles JSON file upload from disk into the import textarea.
 * @param {Event} event - File input change event.
 */
function handleImportFile(event) {
    const file = event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
        const txt = document.getElementById('importTextarea');
        if (txt) txt.value = e.target.result;
    };
    reader.readAsText(file);
}

/**
 * Parses and applies imported model IDs into the selection lists.
 */
function applyImportedSelection() {
    const txt = document.getElementById('importTextarea');
    const raw = txt ? txt.value.trim() : '';
    if (!raw) {
        alert('Please select a file or paste JSON / model IDs.');
        return;
    }

    let ids = [];
    try {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
            ids = parsed;
        } else if (parsed && Array.isArray(parsed.selected_models)) {
            ids = parsed.selected_models;
        } else if (parsed && Array.isArray(parsed.models)) {
            ids = parsed.models;
        }
    } catch (e) {
        ids = raw.split(/[\n,]+/).map(s => s.trim().replace(/^["']|["']$/g, '')).filter(Boolean);
    }

    if (!ids || ids.length === 0) {
        alert('Could not parse any model IDs from input.');
        return;
    }

    // Uncheck all current checkboxes first
    document.querySelectorAll('input[name="models"]').forEach(cb => {
        cb.checked = false;
        const item = cb.closest('.model-item');
        if (item) {
            item.classList.remove('selected');
            const isVertex = (item.dataset.id || '').startsWith('vertex_ai/');
            const isLocal = (item.dataset.id || '').startsWith('local/');
            let availList = document.getElementById('orAvailableList');
            if (isVertex) availList = document.getElementById('vxAvailableList');
            else if (isLocal) availList = document.getElementById('localAvailableList');
            if (availList && item.parentElement !== availList) {
                availList.appendChild(item);
            }
        }
    });

    // Now check and move the imported models
    const orSelectedList = document.getElementById('orSelectedList');
    const vxSelectedList = document.getElementById('vxSelectedList');
    const localSelectedList = document.getElementById('localSelectedList');
    let matchedCount = 0;

    ids.forEach(id => {
        const cb = document.querySelector(`input[name="models"][value="${id}"]`);
        if (cb) {
            cb.checked = true;
            matchedCount++;
            const item = cb.closest('.model-item');
            if (item) {
                item.classList.add('selected');
                const isVertex = id.startsWith('vertex_ai/');
                const isLocal = id.startsWith('local/');
                let targetList = orSelectedList;
                if (isVertex) targetList = vxSelectedList;
                else if (isLocal) targetList = localSelectedList;
                if (targetList) targetList.appendChild(item);
            }
        } else {
            matchedCount++;
            const isVertex = id.startsWith('vertex_ai/');
            const isLocal = id.startsWith('local/');
            let targetList = orSelectedList;
            if (isVertex) targetList = vxSelectedList;
            else if (isLocal) targetList = localSelectedList;

            if (targetList) {
                const makeOrphan = typeof createOrphanedModel === 'function'
                    ? createOrphanedModel
                    : (window.createOrphanedModel || null);
                if (makeOrphan) {
                    const div = makeOrphan(id, 'Imported model not currently in catalog. Uncheck to remove.');
                    targetList.prepend(div);
                }
            }
        }
    });

    closeImportModal();
    if (typeof applyAllFilters === 'function') {
        applyAllFilters();
    } else if (window.applyAllFilters) {
        window.applyAllFilters();
    }
    alert(`✅ Successfully imported ${matchedCount} model selections! Click 'Save & Sync' (FAB or submit) to apply to LiteLLM.`);
}

/**
 * Alias for applyImportedSelection to maintain interface consistency.
 */
function processImportSelections() {
    return applyImportedSelection();
}

/**
 * Toggles a password input between masked and visible text.
 * @param {string} id - DOM ID of input element.
 */
function togglePassword(id) {
    const input = document.getElementById(id);
    if (input) {
        input.type = input.type === 'password' ? 'text' : 'password';
    }
}

/**
 * Toggles the visibility of the Google Cloud Service Account JSON textarea in settings.
 */
function toggleServiceAccountJson() {
    const txt = document.getElementById('setting_VX_JSON');
    const btn = document.getElementById('toggleVxJsonBtn');
    if (!txt || !btn) return;
    if (txt.classList.contains('revealed')) {
        txt.classList.remove('revealed');
        btn.innerText = '👁️ Reveal JSON';
    } else {
        txt.classList.add('revealed');
        btn.innerText = '🔒 Mask JSON';
    }
}

/**
 * Loads current system settings via API and displays the settings modal.
 */
async function openSettings() {
    try {
        const resp = await fetch('/api/settings');
        const settings = await resp.json();

        if (document.getElementById('setting_OR_KEY')) document.getElementById('setting_OR_KEY').value = settings.OPENROUTER_API_KEY || '';
        if (document.getElementById('setting_VX_PROJ')) document.getElementById('setting_VX_PROJ').value = settings.VERTEX_PROJECT || '';
        if (document.getElementById('setting_VX_LOC')) document.getElementById('setting_VX_LOC').value = settings.VERTEX_LOCATION || 'global';
        if (document.getElementById('setting_VX_JSON')) document.getElementById('setting_VX_JSON').value = settings.VERTEX_CREDENTIALS_JSON || '';
        if (document.getElementById('setting_LOCAL_URL')) document.getElementById('setting_LOCAL_URL').value = settings.LOCAL_LLM_URL || 'http://10.0.0.21:5246';
        if (document.getElementById('setting_LOCAL_ENABLED')) document.getElementById('setting_LOCAL_ENABLED').checked = (settings.LOCAL_LLM_ENABLED || 'true').toLowerCase() === 'true';
        if (document.getElementById('setting_CONFIG_PATH')) document.getElementById('setting_CONFIG_PATH').value = settings.LITELLM_CONFIG || '/app/config/config.yaml';

        if (document.getElementById('setting_APPRISE_URL')) document.getElementById('setting_APPRISE_URL').value = settings.APPRISE_URL || '';
        if (document.getElementById('setting_NOTIF_ENABLED')) document.getElementById('setting_NOTIF_ENABLED').checked = (settings.NOTIFICATION_ENABLED || 'true').toLowerCase() === 'true';
        if (document.getElementById('setting_NOTIF_UNAVAIL')) document.getElementById('setting_NOTIF_UNAVAIL').checked = (settings.NOTIFY_ON_UNAVAILABLE || 'true').toLowerCase() === 'true';
        if (document.getElementById('setting_NOTIF_TRENDING')) document.getElementById('setting_NOTIF_TRENDING').checked = (settings.NOTIFY_ON_TRENDING || 'true').toLowerCase() === 'true';
        if (document.getElementById('setting_HEALTH_INTERVAL')) document.getElementById('setting_HEALTH_INTERVAL').value = settings.HEALTH_CHECK_INTERVAL_HOURS || '24';
        if (document.getElementById('setting_PROBE_MODE')) document.getElementById('setting_PROBE_MODE').value = settings.PROBE_MODE || 'catalog';

        // Reset JSON mask state
        const txt = document.getElementById('setting_VX_JSON');
        const btn = document.getElementById('toggleVxJsonBtn');
        if (txt) txt.classList.remove('revealed');
        if (btn) btn.innerText = '👁️ Reveal JSON';

        const modal = document.getElementById('settingsModal');
        if (modal) modal.style.display = 'block';
    } catch (e) {
        alert('Failed to load settings');
    }
}

/**
 * Closes the settings modal.
 */
function closeSettings() {
    const modal = document.getElementById('settingsModal');
    if (modal) modal.style.display = 'none';
}

/**
 * Triggers a test notification through Apprise.
 */
async function testNotification() {
    const urlEl = document.getElementById('setting_APPRISE_URL');
    const url = urlEl ? urlEl.value : '';
    try {
        const resp = await fetch('/api/notifications/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url })
        });
        const res = await resp.json();
        if (res.status === 'success') {
            alert('✅ Test alert sent successfully!');
        } else {
            alert('❌ Test alert failed: ' + (res.message || res.response || JSON.stringify(res)));
        }
    } catch (e) {
        alert('Error sending test notification: ' + e);
    }
}

/**
 * Triggers an immediate 0-token health check probe across all enabled models.
 */
async function triggerHealthCheck() {
    try {
        const resp = await fetch('/api/health/check', { method: 'POST' });
        const res = await resp.json();
        if (res.status === 'success') {
            alert(`🩺 Health check complete!\nChecked: ${res.total_checked}\nHealthy: ${res.healthy}\nUnhealthy: ${res.unhealthy}`);
        } else {
            alert('Health check error: ' + (res.message || JSON.stringify(res)));
        }
    } catch (e) {
        alert('Error triggering health check: ' + e);
    }
}

/**
 * Forces an immediate refresh of upstream provider catalog metadata.
 */
async function forceRefresh() {
    if (!confirm('Fetch latest models?')) return;
    const btn = document.querySelector('.btn-refresh');
    if (btn) {
        btn.innerText = 'Refreshing...';
        btn.disabled = true;
    }
    try {
        const resp = await fetch('/force-refresh', { method: 'POST' });
        if (resp.ok) window.location.reload();
    } catch (e) {
        alert('Error refreshing metadata');
        if (btn) {
            btn.innerText = 'Force Refresh Metadata';
            btn.disabled = false;
        }
    }
}

/**
 * Restarts the LiteLLM container and verifies its health endpoint.
 */
async function restartLiteLLM() {
    if (!confirm('Restart LiteLLM container and verify health?')) return;
    const fabBtn = document.getElementById('restartProxyFabBtn');
    let originalText = '';
    if (fabBtn) {
        originalText = fabBtn.innerText;
        fabBtn.innerText = '⏳';
        fabBtn.disabled = true;
    }

    try {
        const resp = await fetch('/restart-litellm', { method: 'POST' });
        const res = await resp.json();
        if (res.status === 'success') {
            alert('✅ ' + (res.message || 'LiteLLM restarted and health verified (HTTP 200 OK)!'));
        } else if (res.reverted) {
            alert('⚠️ ' + res.message);
        } else {
            alert('❌ Restart error: ' + (res.message || JSON.stringify(res)));
        }
    } catch (e) {
        alert('Error restarting LiteLLM: ' + e);
    } finally {
        if (fabBtn) {
            fabBtn.innerText = originalText;
            fabBtn.disabled = false;
        }
    }
}

// Expose globally for inline HTML event handlers and cross-module access
window.exportSelections = exportSelections;
window.openImportModal = openImportModal;
window.closeImportModal = closeImportModal;
window.handleImportFile = handleImportFile;
window.applyImportedSelection = applyImportedSelection;
window.processImportSelections = processImportSelections;
window.togglePassword = togglePassword;
window.toggleServiceAccountJson = toggleServiceAccountJson;
window.openSettings = openSettings;
window.closeSettings = closeSettings;
window.testNotification = testNotification;
window.triggerHealthCheck = triggerHealthCheck;
window.forceRefresh = forceRefresh;
window.restartLiteLLM = restartLiteLLM;
