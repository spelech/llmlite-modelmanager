/**
 * filters.js - LiteLLM Model Manager
 * Multi-dimensional model filtering, search query matching, benchmark evaluation, and list sorting.
 */

/**
 * Checks and updates the empty-state placeholder message inside a model list container.
 * @param {string} listId - Container DOM ID.
 * @param {number} count - Number of visible models in the container.
 * @param {string} msg - Message to display when count is 0.
 */
function checkEmptyState(listId, count, msg) {
    const list = document.getElementById(listId);
    if (!list) return;
    let emptyEl = list.querySelector('.empty-section-message');
    if (count === 0) {
        if (!emptyEl) {
            emptyEl = document.createElement('div');
            emptyEl.className = 'empty-section-message';
            emptyEl.innerText = msg;
            list.appendChild(emptyEl);
        }
    } else if (emptyEl) {
        emptyEl.remove();
    }
}

/**
 * Sorts child model cards within a specified list container based on the active sort order.
 * @param {string} listId - Container DOM ID.
 * @param {string} [sortOrder] - The sorting strategy key.
 */
function sortList(listId, sortOrder) {
    const list = document.getElementById(listId);
    if (!list) return;
    if (!sortOrder) {
        const sortSelect = document.getElementById('sortOrder');
        sortOrder = sortSelect ? sortSelect.value : 'popularity';
    }
    const items = Array.from(list.querySelectorAll('.model-item'));
    items.sort((a, b) => {
        // Always keep orphaned models at the very top of lists
        if (a.classList.contains('orphaned-model') && !b.classList.contains('orphaned-model')) return -1;
        if (!a.classList.contains('orphaned-model') && b.classList.contains('orphaned-model')) return 1;

        if (sortOrder === 'popularity') {
            return parseInt(a.dataset.popularity || 9999) - parseInt(b.dataset.popularity || 9999);
        } else if (sortOrder === 'codingDesc') {
            const sA = a.dataset.coding !== undefined && a.dataset.coding !== '' ? parseFloat(a.dataset.coding) : -1;
            const sB = b.dataset.coding !== undefined && b.dataset.coding !== '' ? parseFloat(b.dataset.coding) : -1;
            if (sB !== sA) return sB - sA;
            return (a.dataset.name || '').localeCompare(b.dataset.name || '');
        } else if (sortOrder === 'intelDesc') {
            const sA = a.dataset.intel !== undefined && a.dataset.intel !== '' ? parseFloat(a.dataset.intel) : -1;
            const sB = b.dataset.intel !== undefined && b.dataset.intel !== '' ? parseFloat(b.dataset.intel) : -1;
            if (sB !== sA) return sB - sA;
            return (a.dataset.name || '').localeCompare(b.dataset.name || '');
        } else if (sortOrder === 'agenticDesc') {
            const sA = a.dataset.agentic !== undefined && a.dataset.agentic !== '' ? parseFloat(a.dataset.agentic) : -1;
            const sB = b.dataset.agentic !== undefined && b.dataset.agentic !== '' ? parseFloat(b.dataset.agentic) : -1;
            if (sB !== sA) return sB - sA;
            return (a.dataset.name || '').localeCompare(b.dataset.name || '');
        } else if (sortOrder === 'priceAsc') {
            return parseFloat(a.dataset.price || 0) - parseFloat(b.dataset.price || 0);
        } else if (sortOrder === 'priceDesc') {
            return parseFloat(b.dataset.price || 0) - parseFloat(a.dataset.price || 0);
        } else if (sortOrder === 'name') {
            return (a.dataset.name || '').localeCompare(b.dataset.name || '');
        } else if (sortOrder === 'brand') {
            const brandDiff = (a.dataset.brand || '').localeCompare(b.dataset.brand || '');
            if (brandDiff !== 0) return brandDiff;
            return (a.dataset.name || '').localeCompare(b.dataset.name || '');
        }
        return 0;
    });
    items.forEach(item => list.appendChild(item));
}

/**
 * Main filtering evaluation pipeline. Reads all sidebar filter controls, searches,
 * benchmarks, capabilities, and pricing constraints, and applies visibility to all cards.
 */
function applyAllFilters() {
    const globalSearchEl = document.getElementById('globalSearch');
    const query = globalSearchEl ? globalSearchEl.value.toLowerCase() : '';

    const showOR = !document.getElementById('provOpenRouter') || document.getElementById('provOpenRouter').checked;
    const showVX = !document.getElementById('provVertex') || document.getElementById('provVertex').checked;
    const showLocal = !document.getElementById('provLocal') || document.getElementById('provLocal').checked;

    const colOR = document.getElementById('orColumn');
    const colVX = document.getElementById('vxColumn');
    const colLocal = document.getElementById('localColumn');
    if (colOR) colOR.style.display = showOR ? 'flex' : 'none';
    if (colVX) colVX.style.display = showVX ? 'flex' : 'none';
    if (colLocal) colLocal.style.display = showLocal ? 'flex' : 'none';

    const selectedBrands = new Set();
    document.querySelectorAll('#brandFilterList input:checked').forEach(cb => selectedBrands.add(cb.value));

    const selectedTiers = new Set();
    if (document.getElementById('tierFrontier') && document.getElementById('tierFrontier').checked) selectedTiers.add('frontier');
    if (document.getElementById('tierModerate') && document.getElementById('tierModerate').checked) selectedTiers.add('moderate');
    if (document.getElementById('tierCheap') && document.getElementById('tierCheap').checked) selectedTiers.add('cheap');

    const maxInPrice = parseFloat(document.getElementById('maxInPrice')?.value) || Infinity;
    const maxOutPrice = parseFloat(document.getElementById('maxOutPrice')?.value) || Infinity;
    const minCoding = parseFloat(document.getElementById('minCoding')?.value || 0) || 0;
    const minIntel = parseFloat(document.getElementById('minIntel')?.value || 0) || 0;
    const minAgentic = parseFloat(document.getElementById('minAgentic')?.value || 0) || 0;
    const includeUnrated = document.getElementById('includeUnrated') ? document.getElementById('includeUnrated').checked : false;

    const imgIn = document.getElementById('capImageIn')?.checked || false;
    const imgOut = document.getElementById('capImageOut')?.checked || false;
    const audIn = document.getElementById('capAudioIn')?.checked || false;
    const audOut = document.getElementById('capAudioOut')?.checked || false;
    const func = document.getElementById('capFunc')?.checked || false;
    const onlySelected = document.getElementById('filterSelected')?.checked || false;

    // Prepare Wildcard / Regex
    let regex = null;
    if (query) {
        try {
            if (query.startsWith('/') && query.endsWith('/') && query.length > 2) {
                regex = new RegExp(query.slice(1, -1), 'i');
            } else {
                const pattern = query.replace(/\*/g, '.*');
                regex = new RegExp(pattern, 'i');
            }
        } catch (e) {
            regex = null;
        }
    }

    let counts = {
        orSelected: 0,
        orAvailable: 0,
        vxSelected: 0,
        vxAvailable: 0,
        localSelected: 0,
        localAvailable: 0
    };

    document.querySelectorAll('.model-item').forEach(item => {
        const name = item.dataset.name || '';
        const id = item.dataset.id || '';
        const iBrand = item.dataset.brand;
        const iTier = item.dataset.tier || 'moderate';
        const iInPrice = parseFloat(item.dataset.inPrice || 0);
        const iOutPrice = parseFloat(item.dataset.outPrice || 0);
        const iCoding = item.dataset.coding !== undefined && item.dataset.coding !== '' ? parseFloat(item.dataset.coding) : null;
        const iIntel = item.dataset.intel !== undefined && item.dataset.intel !== '' ? parseFloat(item.dataset.intel) : null;
        const iAgentic = item.dataset.agentic !== undefined && item.dataset.agentic !== '' ? parseFloat(item.dataset.agentic) : null;
        const iImgIn = item.dataset.imageIn === 'true';
        const iImgOut = item.dataset.imageOut === 'true';
        const iAudIn = item.dataset.audioIn === 'true';
        const iAudOut = item.dataset.audioOut === 'true';
        const iFunc = item.dataset.func === 'true';
        const checkbox = item.querySelector('input[type="checkbox"]');
        const isSelected = checkbox ? checkbox.checked : false;

        // Update selected visual highlight class
        if (isSelected) {
            item.classList.add('selected');
        } else {
            item.classList.remove('selected');
        }

        // Update human-readable tokens display
        const specsDiv = item.querySelector('.model-specs');
        if (specsDiv) {
            const inLimit = parseInt(item.dataset.maxInput, 10);
            const outLimit = parseInt(item.dataset.maxOutput, 10);
            let specsText = '';
            const fmt = typeof formatTokens === 'function' ? formatTokens : (window.formatTokens || ((n) => n));
            if (inLimit) specsText += `In: ${fmt(inLimit)}`;
            if (outLimit) specsText += ` · Out: ${fmt(outLimit)}`;
            specsDiv.innerText = specsText || 'In: ? · Out: ?';
        }

        let visible = true;

        if (regex) {
            visible = regex.test(name) || regex.test(id);
        } else if (query) {
            visible = name.includes(query) || id.includes(query);
        }

        if (visible && selectedBrands.size > 0 && !selectedBrands.has(iBrand)) visible = false;
        if (visible && selectedTiers.size > 0 && !selectedTiers.has(iTier)) visible = false;
        if (visible && iInPrice > maxInPrice) visible = false;
        if (visible && iOutPrice > maxOutPrice) visible = false;

        if (visible && minCoding > 0) {
            if (iCoding !== null) {
                if (iCoding < minCoding) visible = false;
            } else if (!includeUnrated) {
                visible = false;
            }
        }
        if (visible && minIntel > 0) {
            if (iIntel !== null) {
                if (iIntel < minIntel) visible = false;
            } else if (!includeUnrated) {
                visible = false;
            }
        }
        if (visible && minAgentic > 0) {
            if (iAgentic !== null) {
                if (iAgentic < minAgentic) visible = false;
            } else if (!includeUnrated) {
                visible = false;
            }
        }

        if (visible && imgIn && !iImgIn) visible = false;
        if (visible && imgOut && !iImgOut) visible = false;
        if (visible && audIn && !iAudIn) visible = false;
        if (visible && audOut && !iAudOut) visible = false;
        if (visible && func && !iFunc) visible = false;
        if (visible && onlySelected && !isSelected) visible = false;

        item.style.display = visible ? 'flex' : 'none';

        if (visible) {
            const parentId = item.parentElement ? item.parentElement.id : '';
            if (parentId === 'orSelectedList') counts.orSelected++;
            else if (parentId === 'orAvailableList') counts.orAvailable++;
            else if (parentId === 'vxSelectedList') counts.vxSelected++;
            else if (parentId === 'vxAvailableList') counts.vxAvailable++;
            else if (parentId === 'localSelectedList') counts.localSelected++;
            else if (parentId === 'localAvailableList') counts.localAvailable++;
        }
    });

    // Update empty states
    checkEmptyState('orSelectedList', counts.orSelected, 'No models selected');
    checkEmptyState('orAvailableList', counts.orAvailable, 'No available models matching filters');
    checkEmptyState('vxSelectedList', counts.vxSelected, 'No models selected');
    checkEmptyState('vxAvailableList', counts.vxAvailable, 'No available models matching filters');
    checkEmptyState('localSelectedList', counts.localSelected, 'No models selected');
    checkEmptyState('localAvailableList', counts.localAvailable, 'No available models matching filters');

    const sortOrder = document.getElementById('sortOrder') ? document.getElementById('sortOrder').value : 'popularity';

    sortList('orSelectedList', sortOrder);
    sortList('orAvailableList', sortOrder);
    sortList('vxSelectedList', sortOrder);
    sortList('vxAvailableList', sortOrder);
    sortList('localSelectedList', sortOrder);
    sortList('localAvailableList', sortOrder);

    if (document.getElementById('orSelectedCount')) document.getElementById('orSelectedCount').innerText = counts.orSelected;
    if (document.getElementById('orAvailableCount')) document.getElementById('orAvailableCount').innerText = counts.orAvailable;
    if (document.getElementById('orCount')) document.getElementById('orCount').innerText = counts.orSelected + counts.orAvailable;
    if (document.getElementById('orCollapsedCount')) document.getElementById('orCollapsedCount').innerText = counts.orSelected + counts.orAvailable;

    if (document.getElementById('vxSelectedCount')) document.getElementById('vxSelectedCount').innerText = counts.vxSelected;
    if (document.getElementById('vxAvailableCount')) document.getElementById('vxAvailableCount').innerText = counts.vxAvailable;
    if (document.getElementById('vxCount')) document.getElementById('vxCount').innerText = counts.vxSelected + counts.vxAvailable;
    if (document.getElementById('vxCollapsedCount')) document.getElementById('vxCollapsedCount').innerText = counts.vxSelected + counts.vxAvailable;

    if (document.getElementById('localSelectedCount')) document.getElementById('localSelectedCount').innerText = counts.localSelected;
    if (document.getElementById('localAvailableCount')) document.getElementById('localAvailableCount').innerText = counts.localAvailable;
    if (document.getElementById('localCount')) document.getElementById('localCount').innerText = counts.localSelected + counts.localAvailable;
    if (document.getElementById('localCollapsedCount')) document.getElementById('localCollapsedCount').innerText = counts.localSelected + counts.localAvailable;
}

// Expose globally for inline HTML event handlers and cross-module access
window.checkEmptyState = checkEmptyState;
window.sortList = sortList;
window.applyAllFilters = applyAllFilters;
