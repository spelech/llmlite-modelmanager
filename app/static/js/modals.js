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
        if (document.getElementById('setting_OR_THRESHOLD')) document.getElementById('setting_OR_THRESHOLD').value = settings.OPENROUTER_LOW_CREDIT_THRESHOLD || '5.0';
        if (document.getElementById('setting_OR_ALERT_ENABLED')) document.getElementById('setting_OR_ALERT_ENABLED').checked = (settings.OPENROUTER_BALANCE_ALERT_ENABLED || 'true').toLowerCase() === 'true';
        const orCreditStatus = document.getElementById('orCreditStatusText');
        if (orCreditStatus) orCreditStatus.innerText = '';
        if (document.getElementById('setting_VX_PROJ')) document.getElementById('setting_VX_PROJ').value = settings.VERTEX_PROJECT || '';
        if (document.getElementById('setting_VX_LOC')) document.getElementById('setting_VX_LOC').value = settings.VERTEX_LOCATION || 'global';
        if (document.getElementById('setting_VX_JSON')) document.getElementById('setting_VX_JSON').value = settings.VERTEX_CREDENTIALS_JSON || '';
        if (document.getElementById('setting_VX_BUDGET')) document.getElementById('setting_VX_BUDGET').value = settings.VERTEX_MONTHLY_BUDGET || '25.0';
        if (document.getElementById('setting_VX_ALERT_ENABLED')) document.getElementById('setting_VX_ALERT_ENABLED').checked = (settings.VERTEX_BUDGET_ALERT_ENABLED || 'true').toLowerCase() === 'true';
        const vxBillingStatus = document.getElementById('vxBillingStatusText');
        if (vxBillingStatus) vxBillingStatus.innerText = '';

        if (document.getElementById('setting_LOCAL_URL')) document.getElementById('setting_LOCAL_URL').value = settings.LOCAL_LLM_URL || '';
        if (document.getElementById('setting_LOCAL_ENABLED')) document.getElementById('setting_LOCAL_ENABLED').checked = (settings.LOCAL_LLM_ENABLED || 'true').toLowerCase() === 'true';
        if (document.getElementById('setting_CONFIG_PATH')) document.getElementById('setting_CONFIG_PATH').value = settings.LITELLM_CONFIG || '/app/config/config.yaml';

        if (document.getElementById('setting_OPENCODE_REMOTE_ENABLED')) document.getElementById('setting_OPENCODE_REMOTE_ENABLED').checked = (settings.OPENCODE_REMOTE_ENABLED || 'false').toLowerCase() === 'true';
        if (document.getElementById('setting_OPENCODE_REMOTE_HOST')) document.getElementById('setting_OPENCODE_REMOTE_HOST').value = settings.OPENCODE_REMOTE_HOST || '';
        if (document.getElementById('setting_OPENCODE_REMOTE_PORT')) document.getElementById('setting_OPENCODE_REMOTE_PORT').value = settings.OPENCODE_REMOTE_PORT || '22';
        if (document.getElementById('setting_OPENCODE_REMOTE_USER')) document.getElementById('setting_OPENCODE_REMOTE_USER').value = settings.OPENCODE_REMOTE_USER || '';
        if (document.getElementById('setting_OPENCODE_REMOTE_CONFIG_PATH')) document.getElementById('setting_OPENCODE_REMOTE_CONFIG_PATH').value = settings.OPENCODE_REMOTE_CONFIG_PATH || '';
        if (document.getElementById('setting_OPENCODE_REMOTE_PLUGIN_PATH')) document.getElementById('setting_OPENCODE_REMOTE_PLUGIN_PATH').value = settings.OPENCODE_REMOTE_PLUGIN_PATH || '';
        if (document.getElementById('setting_OPENCODE_REMOTE_KEY')) document.getElementById('setting_OPENCODE_REMOTE_KEY').value = settings.OPENCODE_REMOTE_KEY || '';
        if (document.getElementById('setting_OPENCODE_REMOTE_KEY_PASSPHRASE')) document.getElementById('setting_OPENCODE_REMOTE_KEY_PASSPHRASE').value = settings.OPENCODE_REMOTE_KEY_PASSPHRASE || '';
        
        const testStatus = document.getElementById('testRemoteOpenCodeStatus');
        if (testStatus) testStatus.innerText = '';

        if (document.getElementById('setting_APPRISE_URL')) document.getElementById('setting_APPRISE_URL').value = settings.APPRISE_URL || '';
        if (document.getElementById('setting_NOTIF_ENABLED')) document.getElementById('setting_NOTIF_ENABLED').checked = (settings.NOTIFICATION_ENABLED || 'true').toLowerCase() === 'true';
        if (document.getElementById('setting_NOTIF_UNAVAIL')) document.getElementById('setting_NOTIF_UNAVAIL').checked = (settings.NOTIFY_ON_UNAVAILABLE || 'true').toLowerCase() === 'true';
        if (document.getElementById('setting_NOTIF_TRENDING')) document.getElementById('setting_NOTIF_TRENDING').checked = (settings.NOTIFY_ON_TRENDING || 'true').toLowerCase() === 'true';
        if (document.getElementById('setting_NOTIF_PRICE_CHANGE')) document.getElementById('setting_NOTIF_PRICE_CHANGE').checked = (settings.NOTIFY_ON_PRICE_CHANGE || 'true').toLowerCase() === 'true';
        if (document.getElementById('setting_HEALTH_INTERVAL')) document.getElementById('setting_HEALTH_INTERVAL').value = settings.HEALTH_CHECK_INTERVAL_HOURS || '24';
        if (document.getElementById('setting_PROBE_MODE')) document.getElementById('setting_PROBE_MODE').value = settings.PROBE_MODE || 'catalog';

        // Reset JSON and SSH mask state
        const txt = document.getElementById('setting_VX_JSON');
        const btn = document.getElementById('toggleVxJsonBtn');
        if (txt) txt.classList.remove('revealed');
        if (btn) btn.innerText = '👁️ Reveal JSON';

        const sshKey = document.getElementById('setting_OPENCODE_REMOTE_KEY');
        const sshBtn = document.getElementById('toggleSshKeyBtn');
        if (sshKey) sshKey.classList.remove('revealed');
        if (sshBtn) sshBtn.innerText = '👁️ Reveal Key';

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

/**
 * Toggles SSH key masking in the settings modal.
 */
function toggleSshKeyMask() {
    const keyEl = document.getElementById('setting_OPENCODE_REMOTE_KEY');
    const btn = document.getElementById('toggleSshKeyBtn');
    if (!keyEl || !btn) return;

    if (keyEl.classList.contains('revealed')) {
        keyEl.classList.remove('revealed');
        btn.innerText = '👁️ Reveal Key';
    } else {
        keyEl.classList.add('revealed');
        btn.innerText = '🔒 Mask Key';
    }
}

/**
 * Tests SSH connection and remote path accessibility for OpenCode.
 */
async function testRemoteOpenCode() {
    const btn = document.getElementById('testRemoteOpenCodeBtn');
    const statusEl = document.getElementById('testRemoteOpenCodeStatus');
    if (btn) btn.disabled = true;
    if (statusEl) {
        statusEl.innerText = 'Testing connection...';
        statusEl.style.color = 'var(--text-dim)';
    }

    const payload = {
        OPENCODE_REMOTE_HOST: document.getElementById('setting_OPENCODE_REMOTE_HOST')?.value || '',
        OPENCODE_REMOTE_PORT: document.getElementById('setting_OPENCODE_REMOTE_PORT')?.value || '',
        OPENCODE_REMOTE_USER: document.getElementById('setting_OPENCODE_REMOTE_USER')?.value || '',
        OPENCODE_REMOTE_KEY: document.getElementById('setting_OPENCODE_REMOTE_KEY')?.value || '',
        OPENCODE_REMOTE_KEY_PASSPHRASE: document.getElementById('setting_OPENCODE_REMOTE_KEY_PASSPHRASE')?.value || '',
        OPENCODE_REMOTE_CONFIG_PATH: document.getElementById('setting_OPENCODE_REMOTE_CONFIG_PATH')?.value || ''
    };

    try {
        const resp = await fetch('/api/settings/test-remote-opencode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const res = await resp.json();
        if (res.status === 'success') {
            const pathInfo = res.config_path_status ? ` (path: ${res.config_path_status})` : '';
            if (statusEl) {
                statusEl.innerText = `✅ Connected!${pathInfo}`;
                statusEl.style.color = 'var(--success, #22c55e)';
            }
        } else {
            if (statusEl) {
                statusEl.innerText = `❌ ${res.message || 'Connection failed'}`;
                statusEl.style.color = 'var(--danger, #ef4444)';
            }
        }
    } catch (e) {
        if (statusEl) {
            statusEl.innerText = `❌ Error: ${e.message || e}`;
            statusEl.style.color = 'var(--danger, #ef4444)';
        }
    } finally {
        if (btn) btn.disabled = false;
    }
}

/**
 * Triggers an on-demand check of OpenRouter credit balance and updates UI status.
 */
async function checkOpenRouterCreditsNow() {
    const statusEl = document.getElementById('orCreditStatusText');
    if (statusEl) {
        statusEl.style.color = 'var(--text-dim)';
        statusEl.innerText = 'Checking OpenRouter balance...';
    }
    try {
        const resp = await fetch('/api/openrouter/check-credits', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ notify: false })
        });
        const data = await resp.json();
        if (data.status === 'success') {
            const bal = Number(data.balance).toFixed(2);
            const usage = Number(data.total_usage || 0).toFixed(2);
            if (statusEl) {
                statusEl.style.color = data.is_low ? 'var(--danger, #ef4444)' : 'var(--success, #22c55e)';
                statusEl.innerText = `Balance: $${bal} (${data.is_low ? '⚠️ LOW' : 'OK'}) | Total Used: $${usage}`;
            }
            updateOpenRouterBalanceBadge(data.balance, data.is_low);
        } else {
            if (statusEl) {
                statusEl.style.color = 'var(--danger, #ef4444)';
                statusEl.innerText = `❌ ${data.message || 'Failed to check balance'}`;
            }
        }
    } catch (e) {
        if (statusEl) {
            statusEl.style.color = 'var(--danger, #ef4444)';
            statusEl.innerText = `❌ Error: ${e.message || e}`;
        }
    }
}

/**
 * Loads current OpenRouter balance and updates header badge.
 */
async function loadOpenRouterBalanceBadge() {
    try {
        const resp = await fetch('/api/openrouter/credits');
        const data = await resp.json();
        if (data.status === 'success') {
            const threshold = 5.0;
            const isLow = Number(data.balance) <= threshold;
            updateOpenRouterBalanceBadge(data.balance, isLow);
        }
    } catch (e) {
        // silent fallback on startup
    }
}

/**
 * Updates DOM state of the header balance badge.
 */
function updateOpenRouterBalanceBadge(balance, isLow) {
    const badge = document.getElementById('openrouterBalanceBadge');
    const val = document.getElementById('openrouterBalanceVal');
    if (!badge || !val) return;
    badge.style.display = 'inline-flex';
    val.innerText = `$${Number(balance).toFixed(2)}`;
    if (isLow) {
        badge.style.background = 'rgba(239, 68, 68, 0.15)';
        badge.style.borderColor = 'rgba(239, 68, 68, 0.4)';
        badge.style.color = '#f87171';
        badge.title = 'OpenRouter Balance LOW! Click to open settings.';
    } else {
        badge.style.background = 'rgba(59, 130, 246, 0.15)';
        badge.style.borderColor = 'rgba(59, 130, 246, 0.3)';
        badge.style.color = '#60a5fa';
        badge.title = 'OpenRouter Prepaid Balance (Click to open settings)';
    }
}

/**
 * Triggers an on-demand check of Vertex AI spend and GCP billing status.
 */
async function checkVertexBillingNow() {
    const statusEl = document.getElementById('vxBillingStatusText');
    if (statusEl) {
        statusEl.innerText = 'Checking Vertex spend & GCP billing...';
        statusEl.style.color = 'var(--text-dim)';
    }

    try {
        const resp = await fetch('/api/vertex/billing');
        const data = await resp.json();
        if (data.status === 'success') {
            const mtd = Number(data.current_month_spend || 0).toFixed(2);
            const budget = Number(data.monthly_budget || 25).toFixed(2);
            const pct = data.percent_used || 0;
            const billingEnabled = data.billing_enabled !== false;
            const acct = data.gcp_billing?.billing_account_id || 'N/A';

            if (statusEl) {
                if (!billingEnabled) {
                    statusEl.style.color = 'var(--danger, #ef4444)';
                    statusEl.innerText = `🚨 GCP Billing DISABLED! (Acct: ${acct})`;
                } else if (data.is_over_budget) {
                    statusEl.style.color = 'var(--danger, #ef4444)';
                    statusEl.innerText = `⚠️ MTD: $${mtd} / $${budget} (${pct}%) — OVER BUDGET! (Acct: ${acct})`;
                } else {
                    statusEl.style.color = 'var(--success, #22c55e)';
                    statusEl.innerText = `✅ MTD: $${mtd} / $${budget} (${pct}%) | GCP Billing Active (${acct})`;
                }
            }
            updateVertexSpendBadge(data.current_month_spend, data.monthly_budget, data.is_over_budget, billingEnabled);
        } else {
            if (statusEl) {
                statusEl.style.color = 'var(--danger, #ef4444)';
                statusEl.innerText = `❌ ${data.message || 'Failed to check Vertex billing'}`;
            }
        }
    } catch (e) {
        if (statusEl) {
            statusEl.style.color = 'var(--danger, #ef4444)';
            statusEl.innerText = `❌ Error: ${e.message || e}`;
        }
    }
}

/**
 * Loads current Vertex AI spend and updates header badge.
 */
async function loadVertexBillingBadge() {
    try {
        const resp = await fetch('/api/vertex/billing');
        const data = await resp.json();
        if (data.status === 'success') {
            const billingEnabled = data.billing_enabled !== false;
            updateVertexSpendBadge(data.current_month_spend, data.monthly_budget, data.is_over_budget, billingEnabled);
        }
    } catch (e) {
        // silent fallback on startup
    }
}

/**
 * Updates DOM state of the header Vertex spend badge.
 */
function updateVertexSpendBadge(spend, budget, isOverBudget, isBillingEnabled) {
    const badge = document.getElementById('vertexSpendBadge');
    const val = document.getElementById('vertexSpendVal');
    if (!badge || !val) return;
    badge.style.display = 'inline-flex';
    val.innerText = `$${Number(spend || 0).toFixed(2)}/mo`;

    if (!isBillingEnabled) {
        badge.style.background = 'rgba(239, 68, 68, 0.2)';
        badge.style.borderColor = 'rgba(239, 68, 68, 0.6)';
        badge.style.color = '#f87171';
        badge.title = 'CRITICAL: Google Cloud Billing is DISABLED! Click to open settings.';
    } else if (isOverBudget) {
        badge.style.background = 'rgba(239, 68, 68, 0.15)';
        badge.style.borderColor = 'rgba(239, 68, 68, 0.4)';
        badge.style.color = '#f87171';
        badge.title = `Vertex AI Budget Exceeded ($${Number(spend).toFixed(2)} / $${Number(budget).toFixed(2)})! Click to open settings.`;
    } else {
        badge.style.background = 'rgba(16, 185, 129, 0.15)';
        badge.style.borderColor = 'rgba(16, 185, 129, 0.3)';
        badge.style.color = '#34d399';
        badge.title = `Vertex AI Month-to-Date Spend: $${Number(spend).toFixed(2)} / $${Number(budget).toFixed(2)} (Click to open settings)`;
    }
}

let _modelUpdatesData = null;
let _activeUpdatesTab = 'new';

/**
 * Opens the Model Updates and Price History modal and fetches latest updates.
 */
async function openModelUpdatesModal() {
    const modal = document.getElementById('modelUpdatesModal');
    if (modal) modal.style.display = 'block';

    const contentArea = document.getElementById('updatesContentArea');
    if (contentArea) {
        contentArea.innerHTML = '<div style="text-align: center; color: var(--text-dim); padding: 25px;">⏳ Loading updates from catalog...</div>';
    }

    try {
        const resp = await fetch('/api/models/updates?limit=50');
        _modelUpdatesData = await resp.json();
        renderUpdatesView();
    } catch (err) {
        if (contentArea) {
            contentArea.innerHTML = `<div style="text-align: center; color: var(--danger, #ef4444); padding: 25px;">❌ Failed to load updates: ${err.message || err}</div>`;
        }
    }
}

/**
 * Closes the Model Updates and Price History modal.
 */
function closeModelUpdatesModal() {
    const modal = document.getElementById('modelUpdatesModal');
    if (modal) modal.style.display = 'none';
}

/**
 * Switches between 'new' and 'price' tabs in the Model Updates modal.
 */
function switchUpdatesTab(tab) {
    _activeUpdatesTab = tab;
    renderUpdatesView();
}

/**
 * Helper to jump to and highlight a model card in the main list.
 */
function jumpToModelCard(modelId) {
    closeModelUpdatesModal();
    const searchInput = document.getElementById('globalSearch');
    if (searchInput) {
        searchInput.value = modelId;
        if (typeof applyAllFilters === 'function') {
            applyAllFilters();
        }
    }
    const cleanId = 'item-' + modelId.replace(/\//g, '-').replace(/\./g, '-').replace(/:/g, '-');
    const el = document.getElementById(cleanId);
    if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        el.style.transition = 'box-shadow 0.3s ease';
        el.style.boxShadow = '0 0 15px var(--accent)';
        setTimeout(() => {
            el.style.boxShadow = '';
        }, 2000);
    }
}

/**
 * Renders the contents of the active updates tab.
 */
function renderUpdatesView() {
    const contentArea = document.getElementById('updatesContentArea');
    if (!contentArea || !_modelUpdatesData) return;

    // Update tab button active styles
    const tabNew = document.getElementById('tabUpdatesNew');
    const tabPrice = document.getElementById('tabUpdatesPrice');
    if (tabNew && tabPrice) {
        if (_activeUpdatesTab === 'new') {
            tabNew.style.background = 'var(--accent)';
            tabNew.style.color = 'var(--on-accent)';
            tabPrice.style.background = 'var(--bg-input)';
            tabPrice.style.color = 'var(--text-main)';
        } else {
            tabPrice.style.background = 'var(--accent)';
            tabPrice.style.color = 'var(--on-accent)';
            tabNew.style.background = 'var(--bg-input)';
            tabNew.style.color = 'var(--text-main)';
        }
    }

    if (_activeUpdatesTab === 'new') {
        const items = _modelUpdatesData.new_models || [];
        if (items.length === 0) {
            contentArea.innerHTML = '<div style="text-align: center; color: var(--text-dim); padding: 30px;">✨ No newly discovered models in the last 14 days.</div>';
            return;
        }

        let html = '';
        items.forEach(m => {
            const firstSeenDate = m.first_seen ? new Date(m.first_seen * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : 'Recently';
            const isRouter = m.is_dynamic_router;
            const priceText = isRouter 
                ? '<span class="badge-chip badge-router">⚡ Dynamic Router</span>' 
                : `<span style="color: var(--text-dim); font-size: 0.8em;">In: $${Number(m.pricing_prompt_1m || 0).toFixed(2)}/1M · Out: $${Number(m.pricing_completion_1m || 0).toFixed(2)}/1M</span>`;

            html += `
            <div style="background: var(--bg-item); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 10px 14px; display: flex; justify-content: space-between; align-items: center; gap: 10px;">
                <div style="min-width: 0; flex: 1;">
                    <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 3px;">
                        <span class="badge-chip badge-new">✨ NEW</span>
                        <strong style="font-size: 0.9em; color: var(--text-main); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${m.name || m.id}</strong>
                        <span class="provider-tag provider-${m.model_type}">${m.model_type}</span>
                    </div>
                    <div style="font-size: 0.78em; color: var(--text-dim); font-family: monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${m.id}</div>
                    <div style="margin-top: 4px; display: flex; gap: 12px; align-items: center;">
                        ${priceText}
                        <span style="font-size: 0.75em; color: var(--text-dim);">Added: ${firstSeenDate}</span>
                    </div>
                </div>
                <div>
                    <button type="button" class="btn-refresh" onclick="jumpToModelCard('${m.id}')" style="font-size: 0.78em; padding: 4px 10px; white-space: nowrap;">Find in List</button>
                </div>
            </div>`;
        });
        contentArea.innerHTML = html;
    } else {
        const items = _modelUpdatesData.price_changes || [];
        if (items.length === 0) {
            contentArea.innerHTML = '<div style="text-align: center; color: var(--text-dim); padding: 30px;">📉 No price changes recorded yet.<br><small style="margin-top: 6px; display: block;">Price tracking captures adjustments on subsequent catalog discovery runs.</small></div>';
            return;
        }

        let html = '';
        items.forEach(m => {
            const dateStr = m.price_last_changed ? new Date(m.price_last_changed * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : 'Recently';
            const isDrop = m.price_change_direction === 'drop';
            const badgeClass = isDrop ? 'badge-drop' : 'badge-hike';
            const badgeText = isDrop ? `📉 -${m.price_change_pct}%` : `📈 +${m.price_change_pct}%`;
            
            const prevIn = Number(m.previous_price_prompt_1m || 0).toFixed(2);
            const currIn = Number(m.pricing_prompt_1m || 0).toFixed(2);
            const prevOut = Number(m.previous_price_completion_1m || 0).toFixed(2);
            const currOut = Number(m.pricing_completion_1m || 0).toFixed(2);

            html += `
            <div style="background: var(--bg-item); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 10px 14px; display: flex; justify-content: space-between; align-items: center; gap: 10px;">
                <div style="min-width: 0; flex: 1;">
                    <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 3px;">
                        <span class="badge-chip ${badgeClass}">${badgeText}</span>
                        <strong style="font-size: 0.9em; color: var(--text-main); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${m.name || m.id}</strong>
                        <span class="provider-tag provider-${m.model_type}">${m.model_type}</span>
                    </div>
                    <div style="font-size: 0.78em; color: var(--text-dim); font-family: monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${m.id}</div>
                    <div style="margin-top: 4px; display: flex; gap: 12px; align-items: center; font-size: 0.78em; color: var(--text-dim);">
                        <span>Prompt: <s style="opacity: 0.7;">$${prevIn}</s> &rarr; <strong style="color: var(--accent);">$${currIn}</strong>/1M</span>
                        <span>Comp: <s style="opacity: 0.7;">$${prevOut}</s> &rarr; <strong style="color: var(--accent);">$${currOut}</strong>/1M</span>
                        <span style="font-size: 0.75em; color: var(--text-dim);">Updated: ${dateStr}</span>
                    </div>
                </div>
                <div>
                    <button type="button" class="btn-refresh" onclick="jumpToModelCard('${m.id}')" style="font-size: 0.78em; padding: 4px 10px; white-space: nowrap;">Find in List</button>
                </div>
            </div>`;
        });
        contentArea.innerHTML = html;
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
window.toggleSshKeyMask = toggleSshKeyMask;
window.testRemoteOpenCode = testRemoteOpenCode;
window.openSettings = openSettings;
window.closeSettings = closeSettings;
window.testNotification = testNotification;
window.triggerHealthCheck = triggerHealthCheck;
window.forceRefresh = forceRefresh;
window.restartLiteLLM = restartLiteLLM;
window.checkOpenRouterCreditsNow = checkOpenRouterCreditsNow;
window.loadOpenRouterBalanceBadge = loadOpenRouterBalanceBadge;
window.updateOpenRouterBalanceBadge = updateOpenRouterBalanceBadge;
window.checkVertexBillingNow = checkVertexBillingNow;
window.loadVertexBillingBadge = loadVertexBillingBadge;
window.updateVertexSpendBadge = updateVertexSpendBadge;
window.openModelUpdatesModal = openModelUpdatesModal;
window.closeModelUpdatesModal = closeModelUpdatesModal;
window.switchUpdatesTab = switchUpdatesTab;
window.jumpToModelCard = jumpToModelCard;


