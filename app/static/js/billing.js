/**
 * billing.js - LiteLLM Model Manager
 * OpenRouter credit balance, Vertex AI spend/budget badges, and catalog model updates modal.
 */

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
