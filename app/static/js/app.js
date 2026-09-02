/**
 * app.js - LiteLLM Model Manager
 * Application initialization, brand list generation, initial config loader, and form submission lifecycle.
 */

/**
 * Dynamically aggregates unique brands from all rendered model cards
 * and populates the sidebar brand filter checklist.
 */
function populateBrands() {
    const brands = new Set();
    document.querySelectorAll('.model-item').forEach(item => {
        if (item.dataset.brand) brands.add(item.dataset.brand);
    });
    const list = document.getElementById('brandFilterList');
    if (!list) return;

    const checked = new Set();
    list.querySelectorAll('input:checked').forEach(cb => checked.add(cb.value));

    list.innerHTML = '';

    Array.from(brands).sort().forEach(b => {
        const label = document.createElement('label');
        label.className = 'brand-filter-item';

        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.value = b;
        cb.onchange = () => {
            if (typeof applyAllFilters === 'function') {
                applyAllFilters();
            } else if (window.applyAllFilters) {
                window.applyAllFilters();
            }
        };
        if (checked.has(b)) cb.checked = true;

        const text = document.createTextNode(' ' + b.charAt(0).toUpperCase() + b.slice(1));

        label.appendChild(cb);
        label.appendChild(text);
        list.appendChild(label);
    });
}

/**
 * Main application startup and bootstrap sequence.
 */
async function initApp() {
    if (typeof restoreColumnCollapseState === 'function') {
        restoreColumnCollapseState();
    } else if (window.restoreColumnCollapseState) {
        window.restoreColumnCollapseState();
    }

    populateBrands();

    try {
        const resp = await fetch('/api/config');
        const data = await resp.json();
        if (data.selected_ids) {
            const orSelectedList = document.getElementById('orSelectedList');
            const vxSelectedList = document.getElementById('vxSelectedList');
            const localSelectedList = document.getElementById('localSelectedList');

            data.selected_ids.forEach(id => {
                const checkbox = document.querySelector(`input[name="models"][value="${id}"]`);
                if (checkbox) {
                    checkbox.checked = true;
                    const item = checkbox.closest('.model-item');
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
                    // Model no longer available! Surface to top of selected list.
                    const isVertex = id.startsWith('vertex_ai/');
                    const isLocal = id.startsWith('local/');
                    let targetList = orSelectedList;
                    if (isVertex) targetList = vxSelectedList;
                    else if (isLocal) targetList = localSelectedList;

                    const makeOrphan = typeof createOrphanedModel === 'function'
                        ? createOrphanedModel
                        : (window.createOrphanedModel || null);
                    if (targetList && makeOrphan) {
                        const div = makeOrphan(id, 'Model in config but no longer returned by provider. Uncheck to remove.');
                        targetList.prepend(div);
                    }
                }
            });
        }
    } catch (e) {
        console.error("Failed to load config", e);
    }

    if (typeof applyAllFilters === 'function') {
        applyAllFilters();
    } else if (window.applyAllFilters) {
        window.applyAllFilters();
    }

    // Attach Settings Form Submit Handler
    const settingsForm = document.getElementById('settingsForm');
    if (settingsForm) {
        settingsForm.onsubmit = async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const data = Object.fromEntries(formData.entries());

            // Explicitly handle checkboxes
            const notifEnabled = document.getElementById('setting_NOTIF_ENABLED');
            const notifUnavail = document.getElementById('setting_NOTIF_UNAVAIL');
            const notifTrending = document.getElementById('setting_NOTIF_TRENDING');
            const localEnabled = document.getElementById('setting_LOCAL_ENABLED');

            data.NOTIFICATION_ENABLED = notifEnabled && notifEnabled.checked ? 'true' : 'false';
            data.NOTIFY_ON_UNAVAILABLE = notifUnavail && notifUnavail.checked ? 'true' : 'false';
            data.NOTIFY_ON_TRENDING = notifTrending && notifTrending.checked ? 'true' : 'false';
            data.LOCAL_LLM_ENABLED = localEnabled && localEnabled.checked ? 'true' : 'false';

            try {
                const resp = await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                if (resp.ok) {
                    if (typeof closeSettings === 'function') {
                        closeSettings();
                    } else if (window.closeSettings) {
                        window.closeSettings();
                    }
                    alert('Settings saved. Refreshing models...');
                    window.location.reload();
                }
            } catch (err) {
                alert('Error saving settings: ' + err);
            }
        };
    }

    // Attach Sync Form Submit Handler
    const syncForm = document.getElementById('syncForm');
    if (syncForm) {
        syncForm.onsubmit = async (e) => {
            e.preventDefault();
            const fabBtn = document.getElementById('syncConfigFabBtn');
            let originalText = '';
            if (fabBtn) {
                originalText = fabBtn.innerText;
                fabBtn.innerText = '⏳';
                fabBtn.disabled = true;
            }

            try {
                const formData = new FormData(e.target);
                const resp = await fetch('/sync', { method: 'POST', body: formData });
                const result = await resp.json();
                if (result.status === 'success') {
                    alert(`✅ Saved & synced ${result.updated_models} models into LiteLLM, OpenCode, and LibreChat configs!`);
                } else {
                    alert('❌ Sync failed: ' + (result.message || JSON.stringify(result)));
                }
            } catch (err) {
                alert('Error syncing configuration: ' + err);
            } finally {
                if (fabBtn) {
                    fabBtn.innerText = originalText;
                    fabBtn.disabled = false;
                }
            }
        };
    }
}

// Bootstrap on window load
window.onload = initApp;

// Expose globally
window.populateBrands = populateBrands;
window.initApp = initApp;
