// ============================================================================
// Segments Manager — front-end (vanilla JS, no external dependencies)
// Read-only dashboard: view segments, per-site stats, search, filter, export.
// ============================================================================

// ---- Global state ----------------------------------------------------------
let currentFilter = "all";
let currentSite = "";
let currentSearchQuery = "";
let isOnline = true;
let allSites = [];

function quickSearchMatches(segment, needle) {
    const hay = (value) => String(value ?? "").toLowerCase();
    return (
        hay(segment.site).includes(needle) ||
        hay(segment.vlan_id).includes(needle) ||
        hay(segment.epg_name).includes(needle) ||
        hay(segment.segment).includes(needle) ||
        hay(segment.cluster_name).includes(needle)
    );
}

// ---- Column visibility ------------------------------------------------------
const ALL_COLUMNS = ["type", "site", "vlan_id", "epg_name", "segment", "dhcp", "cluster", "status"];
let hiddenColumns = new Set();

function loadHiddenColumns() {
    try {
        const saved = JSON.parse(localStorage.getItem("sm-hidden-columns") || "[]");
        hiddenColumns = new Set(saved.filter((c) => ALL_COLUMNS.includes(c)));
    } catch (e) {
        hiddenColumns = new Set();
    }
}

function saveHiddenColumns() {
    try {
        localStorage.setItem("sm-hidden-columns", JSON.stringify([...hiddenColumns]));
    } catch (e) {}
}

function applyColumnVisibility() {
    document.querySelectorAll("[data-col]").forEach((el) => {
        el.style.display = hiddenColumns.has(el.getAttribute("data-col")) ? "none" : "";
    });
}

function toggleColumn(col, visible) {
    if (visible) hiddenColumns.delete(col);
    else hiddenColumns.add(col);
    saveHiddenColumns();
    applyColumnVisibility();
}

// ---- Per-column header filters (Excel-style) --------------------------------
const COLUMN_FILTER_LABELS = {
    type: "Type",
    site: "Site",
    vlan_id: "VLAN ID",
    epg_name: "EPG Name",
    segment: "Network Segment",
    dhcp: "DHCP",
    cluster: "Cluster",
    status: "Status",
};

function columnFilterValue(segment, col) {
    switch (col) {
        case "dhcp":
            return segment.dhcp ? "On" : "Off";
        case "status":
            return segmentStatusLabel(segment);
        case "cluster":
            return segment.cluster_name || "";
        default:
            return segment[col] === null || segment[col] === undefined ? "" : String(segment[col]);
    }
}

let columnFilters = {}; // { [col]: Set<string> } — a Set present means that column is actively filtered
let lastBaseSegments = []; // segments after search/status/site, before column filters — source for dropdown options
let openFilterCol = null;
let filterDraftSelected = null; // Set<string>, uncommitted until OK
let filterDraftSearch = "";

function segmentPassesColumnFilters(segment) {
    return Object.keys(columnFilters).every((col) => {
        const set = columnFilters[col];
        if (!set) return true;
        return set.has(columnFilterValue(segment, col));
    });
}

function columnOptions(col) {
    const values = new Set();
    lastBaseSegments.forEach((s) => values.add(columnFilterValue(s, col)));
    return [...values].sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" }));
}

function updateColumnFilterButtonStates() {
    document.querySelectorAll(".col-filter-btn").forEach((btn) => {
        const col = btn.getAttribute("data-filter-col");
        btn.classList.toggle("is-active", !!columnFilters[col]);
    });
}

function closeColumnFilterPopover() {
    const popover = document.getElementById("colFilterPopover");
    if (popover) popover.remove();
    if (openFilterCol) {
        const btn = document.querySelector(`.col-filter-btn[data-filter-col="${openFilterCol}"]`);
        if (btn) btn.setAttribute("aria-expanded", "false");
    }
    openFilterCol = null;
    filterDraftSelected = null;
    filterDraftSearch = "";
}

function renderColumnFilterPopover() {
    const popover = document.getElementById("colFilterPopover");
    if (!popover || !openFilterCol) return;

    const options = columnOptions(openFilterCol);
    const needle = filterDraftSearch.trim().toLowerCase();
    const visible = needle
        ? options.filter((v) => (v === "" ? "(blank)" : v.toLowerCase()).includes(needle))
        : options;
    const allVisibleSelected = visible.length > 0 && visible.every((v) => filterDraftSelected.has(v));

    const rows = visible
        .map((v) => {
            const checked = filterDraftSelected.has(v) ? "checked" : "";
            const label = v === "" ? "(Blank)" : v;
            return `<label class="col-filter__item"><input type="checkbox" data-value="${escapeHTML(
                v
            )}" ${checked}> ${escapeHTML(label)}</label>`;
        })
        .join("");

    const focusSearch = document.activeElement && document.activeElement.id === "colFilterSearchInput";

    popover.innerHTML = `
        <input type="text" class="col-filter__search" id="colFilterSearchInput" placeholder="Search…" value="${escapeHTML(
            filterDraftSearch
        )}">
        <label class="col-filter__item col-filter__selectall"><input type="checkbox" id="colFilterSelectAll" ${
            allVisibleSelected ? "checked" : ""
        }> (Select All)</label>
        <div class="col-filter__list">${rows || '<div class="col-filter__empty">No values</div>'}</div>
        <div class="col-filter__footer">
            <button type="button" class="btn btn-ghost" id="colFilterClearBtn">Clear</button>
            <button type="button" class="btn btn-primary" id="colFilterOkBtn">OK</button>
        </div>`;

    const searchInput = document.getElementById("colFilterSearchInput");
    if (focusSearch) {
        searchInput.focus();
        const pos = searchInput.value.length;
        searchInput.setSelectionRange(pos, pos);
    }
}

function openColumnFilterPopover(col, btn) {
    if (openFilterCol === col) {
        closeColumnFilterPopover();
        return;
    }
    closeColumnFilterPopover();

    openFilterCol = col;
    filterDraftSearch = "";
    const options = columnOptions(col);
    filterDraftSelected = columnFilters[col] ? new Set(columnFilters[col]) : new Set(options);

    const popover = document.createElement("div");
    popover.id = "colFilterPopover";
    popover.className = "col-filter-popover";
    popover.setAttribute("role", "dialog");
    popover.setAttribute("aria-label", `Filter ${COLUMN_FILTER_LABELS[col] || col}`);
    document.body.appendChild(popover);
    renderColumnFilterPopover();

    const rect = btn.getBoundingClientRect();
    popover.style.top = Math.min(rect.bottom + 6, window.innerHeight - popover.offsetHeight - 8) + "px";
    popover.style.left = Math.min(rect.left, window.innerWidth - popover.offsetWidth - 8) + "px";
    btn.setAttribute("aria-expanded", "true");
}

function applyColumnFilterDraft(col) {
    const options = columnOptions(col);
    if (filterDraftSelected.size >= options.length) {
        delete columnFilters[col];
    } else {
        columnFilters[col] = new Set(filterDraftSelected);
    }
    closeColumnFilterPopover();
    updateColumnFilterButtonStates();
    loadSegments(true);
}

function clearColumnFilter(col) {
    delete columnFilters[col];
    closeColumnFilterPopover();
    updateColumnFilterButtonStates();
    loadSegments(true);
}

document.addEventListener("input", (e) => {
    if (e.target.id === "colFilterSearchInput") {
        filterDraftSearch = e.target.value;
        renderColumnFilterPopover();
    }
});

document.addEventListener("change", (e) => {
    if (!openFilterCol) return;
    if (e.target.id === "colFilterSelectAll") {
        const needle = filterDraftSearch.trim().toLowerCase();
        const options = columnOptions(openFilterCol);
        const visible = needle
            ? options.filter((v) => (v === "" ? "(blank)" : v.toLowerCase()).includes(needle))
            : options;
        if (e.target.checked) visible.forEach((v) => filterDraftSelected.add(v));
        else visible.forEach((v) => filterDraftSelected.delete(v));
        renderColumnFilterPopover();
    } else if (e.target.matches(".col-filter__list input[type='checkbox']")) {
        const value = e.target.getAttribute("data-value");
        if (e.target.checked) filterDraftSelected.add(value);
        else filterDraftSelected.delete(value);
        renderColumnFilterPopover();
    }
});

document.addEventListener("click", (e) => {
    if (e.target.id === "colFilterOkBtn") applyColumnFilterDraft(openFilterCol);
    else if (e.target.id === "colFilterClearBtn") clearColumnFilter(openFilterCol);
});

// ---- Inline SVG icons (kept in one place) ----------------------------------
const ICONS = {
    server:
        '<svg viewBox="0 0 24 24" class="icon icon-sm"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>',
    inbox:
        '<svg viewBox="0 0 24 24" class="icon"><polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>',
    alert:
        '<svg viewBox="0 0 24 24" class="icon"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    check:
        '<svg viewBox="0 0 24 24" class="icon icon-sm toast__icon"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
    xCircle:
        '<svg viewBox="0 0 24 24" class="icon icon-sm toast__icon"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    copy:
        '<svg viewBox="0 0 24 24" class="icon icon-sm copyable__icon" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>',
    alertCircle:
        '<svg viewBox="0 0 24 24" class="icon icon-sm" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
    alertTriangle:
        '<svg viewBox="0 0 24 24" class="icon icon-sm" aria-hidden="true"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
};

// ---- Copy to clipboard ------------------------------------------------------
const COPY_LABELS = {
    vlan_id: "VLAN ID",
    epg_name: "EPG name",
    segment: "Segment",
};

async function copyToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (e) {
            // fall through to legacy method
        }
    }
    try {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        const ok = document.execCommand("copy");
        document.body.removeChild(ta);
        return ok;
    } catch (e) {
        return false;
    }
}

async function handleCopyableActivate(cell) {
    const value = cell.getAttribute("data-copy");
    if (!value) return;
    const ok = await copyToClipboard(value);
    const label = COPY_LABELS[cell.getAttribute("data-col")] || "Value";
    if (ok) showSuccess(`${label} copied to clipboard`);
    else showError("Copy failed. Please copy manually.");
}

// ---- Utilities -------------------------------------------------------------
function escapeHTML(value) {
    if (value === null || value === undefined) return "";
    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

// ---- Toast notifications ---------------------------------------------------
function showToast(message, type) {
    const region = document.getElementById("toastRegion");
    if (!region) return;

    const toast = document.createElement("div");
    toast.className = "toast toast--" + (type === "error" ? "error" : "success");
    toast.setAttribute("role", type === "error" ? "alert" : "status");
    toast.innerHTML =
        (type === "error" ? ICONS.xCircle : ICONS.check) +
        '<div class="toast__body">' +
        escapeHTML(message) +
        "</div>";
    region.appendChild(toast);

    const remove = () => {
        toast.classList.add("leaving");
        toast.addEventListener("animationend", () => toast.remove(), { once: true });
        setTimeout(() => toast.remove(), 300);
    };
    setTimeout(remove, type === "error" ? 6000 : 4000);
}

function showError(message) {
    showToast(message, "error");
}

function showSuccess(message) {
    showToast(message, "success");
}

// ---- Connection status (tracked silently; gates auto-refresh) --------------
function updateConnectionStatus(online) {
    isOnline = online;
}

// ---- API helpers -----------------------------------------------------------
async function fetchAPI(endpoint, options = {}) {
    try {
        const response = await fetch(`/api${endpoint}`, {
            ...options,
            headers: { "Content-Type": "application/json", ...options.headers },
        });

        updateConnectionStatus(true);

        if (!response.ok) {
            const error = await response
                .json()
                .catch(() => ({ detail: "Unknown error" }));

            if (Array.isArray(error.detail)) {
                const messages = error.detail
                    .map((err) => err.msg || err.message || "Validation error")
                    .join("; ");
                throw new Error(messages);
            }
            throw new Error(error.detail || `HTTP ${response.status}`);
        }

        return await response.json();
    } catch (error) {
        if (
            error.message.includes("Failed to fetch") ||
            error.message.includes("NetworkError")
        ) {
            updateConnectionStatus(false);
            throw new Error("Connection lost. Please check your network.");
        }
        throw error;
    }
}

// ---- Export ----------------------------------------------------------------
function triggerDownload(blob, filename) {
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.style.display = "none";
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);
}

window.exportData = async function exportData(format) {
    try {
        let endpoint = "";
        let filename = "";

        if (format === "csv") {
            endpoint = "/export/segments/csv";
            filename = "segments.csv";
        } else if (format === "excel") {
            endpoint = "/export/segments/excel";
            filename = "segments.xlsx";
        }

        const params = new URLSearchParams();
        if (currentFilter === "available") params.append("status", "Available");
        else if (currentFilter === "allocated") params.append("status", "Allocated");
        if (currentSite) params.append("site", currentSite);

        const queryString = params.toString();
        const fullEndpoint = queryString ? `${endpoint}?${queryString}` : endpoint;

        const response = await fetch(`/api${fullEndpoint}`);
        if (response.ok) {
            triggerDownload(await response.blob(), filename);
            showSuccess(`${format.toUpperCase()} export completed`);
        } else {
            const error = await response.json().catch(() => ({}));
            showError(error.detail || "Export failed");
        }
    } catch (error) {
        showError("Export failed. Please try again.");
    }
};

// ---- Sites -----------------------------------------------------------------
async function loadSites() {
    try {
        const data = await fetchAPI("/sites");
        allSites = data.sites || [];

        const select = document.getElementById("siteFilter");
        const current = select.value;
        select.innerHTML = '<option value="">All sites</option>';
        allSites.forEach((site) => {
            const opt = document.createElement("option");
            opt.value = site;
            opt.textContent = site;
            select.appendChild(opt);
        });
        select.value = current;
    } catch (error) {
        showError("Failed to load sites: " + error.message);
    }
}

// ---- Stats -----------------------------------------------------------------
function statSkeleton() {
    const row = `
        <div class="trow">
            <span class="skeleton" style="height:12px"></span>
            <span class="skeleton" style="height:7px;border-radius:999px"></span>
            <span class="skeleton" style="width:48px;height:12px"></span>
        </div>`;
    return `
        <div class="stat-card">
            <div class="stat-card__head">
                <span class="skeleton" style="width:90px;height:16px"></span>
            </div>
            <div class="types">${row.repeat(3)}</div>
        </div>`;
}

// Maps a segment type to its accent class, which sets --type-c in CSS
// (used by the table type badge and the sites-summary rows).
function typeClass(type) {
    return type ? "type-" + String(type).toLowerCase() : "";
}

// Renders the per-type usage rows for one site: allocated out of total per type.
function renderTypeUsage(stat) {
    const types = (stat.by_type || []).filter((t) => Number(t.total) > 0);
    if (types.length === 0) {
        return '<div class="types-empty">No HC / MCE / INVENTORY / PXE segments</div>';
    }
    const rows = types
        .map((t) => {
            const allocated = Number(t.allocated) || 0;
            const total = Number(t.total) || 0;
            const pct = total > 0 ? Math.round((allocated / total) * 100) : 0;
            const full = total > 0 && allocated >= total;
            const idle = allocated === 0;
            const high = pct >= 85;
            const fillClass = high ? "is-high" : idle ? "is-empty" : "";
            const countClass = full ? "is-full" : idle ? "is-idle" : "";
            return `
                <div class="trow ${typeClass(t.type)}">
                    <span class="tname">${escapeHTML(t.type)}</span>
                    <div class="tbar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100" aria-label="${escapeHTML(
                t.type
            )} usage">
                        <div class="tbar__fill ${fillClass}" style="width:${pct}%"></div>
                    </div>
                    <span class="tcount ${countClass}">${allocated}<span class="den">/${total}</span></span>
                </div>`;
        })
        .join("");
    return `<div class="types">${rows}</div>`;
}

async function loadStats(showSkeleton = false) {
    const container = document.getElementById("statsGrid");
    if (showSkeleton && container) {
        container.setAttribute("aria-busy", "true");
        container.innerHTML = statSkeleton().repeat(3);
    }

    try {
        const stats = await fetchAPI("/stats");
        if (!container) return;
        container.removeAttribute("aria-busy");

        if (!stats || stats.length === 0) {
            container.innerHTML =
                '<div class="stat-card"><div class="stat-card__site">No sites configured</div></div>';
            return;
        }

        container.innerHTML = stats
            .map((stat) => {
                return `
                <article class="stat-card">
                    <div class="stat-card__head">
                        <div class="stat-card__site">${ICONS.server}<span>${escapeHTML(
                    stat.site
                )}</span></div>
                        <span class="panel__count">${formatSegmentCount(stat.total_segments)}</span>
                    </div>
                    ${renderTypeUsage(stat)}
                </article>`;
            })
            .join("");
    } catch (error) {
        if (container) {
            container.removeAttribute("aria-busy");
            if (showSkeleton) {
                container.innerHTML =
                    '<div class="stat-card"><div class="stat-card__site">Failed to load statistics</div></div>';
            }
        }
    }
}

// ---- Segments --------------------------------------------------------------
function rowSkeleton() {
    const cell = (col, w) =>
        `<td data-col="${col}"><span class="skeleton" style="width:${w}"></span></td>`;
    return (
        "<tr>" +
        cell("type", "70px") +
        cell("site", "60px") +
        cell("vlan_id", "50px") +
        cell("epg_name", "70%") +
        cell("segment", "120px") +
        cell("dhcp", "36px") +
        cell("cluster", "80px") +
        cell("status", "80px") +
        "</tr>"
    );
}

function emptyState(icon, title, desc) {
    return `
        <tr>
            <td colspan="8" class="state-cell">
                <div class="state">
                    ${icon}
                    <span class="state__title">${escapeHTML(title)}</span>
                    <span class="state__desc">${escapeHTML(desc)}</span>
                </div>
            </td>
        </tr>`;
}

function formatSegmentCount(n) {
    n = Number(n) || 0;
    return n + (n === 1 ? " segment" : " segments");
}

function updateSegmentCount(n) {
    const el = document.getElementById("segmentCount");
    if (el) el.textContent = formatSegmentCount(n);
}

// ---- Segment-connectivity request-ids popover ---------------------------------------
// While the segment-connectivity orchestrator has firewall requests awaiting approval
// for a segment, the row's status cell shows a "Requests ID" button; clicking
// it opens a small popover (anchored to the button) listing the pending ids.
let reqIdsAnchor = null;

function closeReqIdsPopover() {
    const popover = document.getElementById("reqIdsPopover");
    if (popover) popover.remove();
    if (reqIdsAnchor) {
        reqIdsAnchor.setAttribute("aria-expanded", "false");
        reqIdsAnchor = null;
    }
}

// Parses a server timestamp, defaulting to UTC when it carries no timezone.
// `new Date("2026-07-13T10:00:00")` (no 'Z'/offset) is read as LOCAL time by the
// browser, which would skew "Submitted N ago" by the viewer's UTC offset. Our
// timestamps are always UTC, so treat an offset-less string as UTC.
function parseTimestampUTC(raw) {
    if (!raw) return null;
    const hasTZ = /[zZ]|[+-]\d{2}:?\d{2}$/.test(raw);
    return new Date(hasTZ ? raw : raw + "Z");
}

// Formats the time since a request was submitted, escalating the unit as it
// grows (minutes -> hours -> days) so the header stays readable no matter how
// long firewall approval takes (can be minutes, hours, or days).
function formatElapsedSince(date) {
    const ms = Date.now() - date.getTime();
    if (!Number.isFinite(ms) || ms < 0) return null;
    const minutes = Math.floor(ms / 60000);
    if (minutes < 1) return "Submitted just now";
    if (minutes < 60) return `Submitted ${minutes} minute${minutes === 1 ? "" : "s"} ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `Submitted ${hours} hour${hours === 1 ? "" : "s"} ago`;
    const days = Math.floor(hours / 24);
    return `Submitted ${days} day${days === 1 ? "" : "s"} ago`;
}

function openReqIdsPopover(btn) {
    closeReqIdsPopover();
    let ids = [];
    try {
        ids = JSON.parse(btn.getAttribute("data-request-ids")) || [];
    } catch (e) {}
    const submittedAtRaw = btn.getAttribute("data-submitted-at");
    const submittedAt = parseTimestampUTC(submittedAtRaw);
    const elapsedLabel =
        submittedAt && !Number.isNaN(submittedAt.getTime()) ? formatElapsedSince(submittedAt) : null;
    const popover = document.createElement("div");
    popover.id = "reqIdsPopover";
    popover.className = "req-ids-popover";
    popover.setAttribute("role", "dialog");
    popover.setAttribute("aria-label", "Pending segment-connectivity request IDs");
    const header = elapsedLabel
        ? `<div class="req-ids-popover__title">${escapeHTML(elapsedLabel)}</div>`
        : "";
    popover.innerHTML =
        header + ids.map((id) => `<div class="req-ids-popover__id">${escapeHTML(id)}</div>`).join("");
    document.body.appendChild(popover);
    // Anchor just below the button, clamped to the viewport (position: fixed).
    const rect = btn.getBoundingClientRect();
    popover.style.top = Math.min(rect.bottom + 6, window.innerHeight - popover.offsetHeight - 8) + "px";
    popover.style.left = Math.min(rect.left, window.innerWidth - popover.offsetWidth - 8) + "px";
    btn.setAttribute("aria-expanded", "true");
    reqIdsAnchor = btn;
}

// ---- Segment-connectivity failure popover -------------------------------------------
// When the segment-connectivity orchestrator's workflow fails or is cancelled after
// submission, the row's status cell shows a "Workflow failed" pill beside the
// (still Locked) status badge; clicking it opens a popover with the failure
// message and how long ago it failed.
let connFailedAnchor = null;

function closeConnFailedPopover() {
    const popover = document.getElementById("connFailedPopover");
    if (popover) popover.remove();
    if (connFailedAnchor) {
        connFailedAnchor.setAttribute("aria-expanded", "false");
        connFailedAnchor = null;
    }
}

function openConnFailedPopover(btn) {
    closeConnFailedPopover();
    const message = btn.getAttribute("data-failure") || "";
    const failedAt = parseTimestampUTC(btn.getAttribute("data-failed-at"));
    const elapsedLabel =
        failedAt && !Number.isNaN(failedAt.getTime()) ? formatElapsedSince(failedAt) : null;
    const popover = document.createElement("div");
    popover.id = "connFailedPopover";
    popover.className = "conn-failed-popover";
    popover.setAttribute("role", "dialog");
    popover.setAttribute("aria-label", "Segment-connectivity workflow failure");
    const timeLabel = elapsedLabel ? elapsedLabel.replace(/^Submitted/, "Failed") : "Workflow failed";
    popover.innerHTML =
        `<div class="conn-failed-popover__head">${ICONS.alertTriangle}` +
        `<span class="conn-failed-popover__title">Workflow failed</span>` +
        `<span class="conn-failed-popover__time">${escapeHTML(timeLabel)}</span></div>` +
        `<div class="conn-failed-popover__msg">${escapeHTML(message)}</div>`;
    document.body.appendChild(popover);
    // Anchor just below the button, clamped to the viewport (position: fixed).
    const rect = btn.getBoundingClientRect();
    popover.style.top = Math.min(rect.bottom + 6, window.innerHeight - popover.offsetHeight - 8) + "px";
    popover.style.left = Math.min(rect.left, window.innerWidth - popover.offsetWidth - 8) + "px";
    btn.setAttribute("aria-expanded", "true");
    connFailedAnchor = btn;
}

// ---- Segment-connectivity attention alert (floating "!" button) --------------------
// A single floating button surfaces two exception states that an operator
// would otherwise have to hunt for in the table:
//   1. Failed workflows — a segment-connectivity workflow that failed/was cancelled
//      (the segment is stuck Locked). Always surfaced.
//   2. Pending over 24h — requests submitted to the next (firewall) service but
//      still unhandled after 24h (normal approval is far quicker).
// The two are grouped separately in the popover. Independent of the table's
// status/site/search filters.
const PENDING_ALERT_THRESHOLD_MS = 24 * 60 * 60 * 1000; // 24h
let pendingPopoverOpen = false;

// Compact elapsed label for the group header: hours until 2 days, then days.
function formatElapsedCompact(ms) {
    const hours = Math.floor(ms / 3600000);
    if (hours < 48) return `${hours}h`;
    return `${Math.floor(hours / 24)}d`;
}

// One overdue segment -> one group { elapsedMs, ids }. Sorted most-overdue first.
function computePendingOverdue(segments) {
    if (!Array.isArray(segments)) return [];
    const now = Date.now();
    const groups = [];
    for (const seg of segments) {
        const ids = Array.isArray(seg.segment_connectivity_requests) ? seg.segment_connectivity_requests : [];
        if (!ids.length) continue;
        const submittedAt = parseTimestampUTC(seg.segment_connectivity_requests_submitted_at);
        if (!submittedAt || Number.isNaN(submittedAt.getTime())) continue;
        const elapsedMs = now - submittedAt.getTime();
        if (elapsedMs < PENDING_ALERT_THRESHOLD_MS) continue;
        groups.push({ elapsedMs, ids });
    }
    groups.sort((a, b) => b.elapsedMs - a.elapsedMs);
    return groups;
}

// One failed segment -> one entry { segment, message, elapsedMs }. A failure is
// always surfaced (no time threshold); most-recent first.
function computeFailed(segments) {
    if (!Array.isArray(segments)) return [];
    const now = Date.now();
    const items = [];
    for (const seg of segments) {
        const message = seg.segment_connectivity_failure;
        if (!message) continue;
        const failedAt = parseTimestampUTC(seg.segment_connectivity_failure_at);
        const elapsedMs =
            failedAt && !Number.isNaN(failedAt.getTime()) ? now - failedAt.getTime() : null;
        items.push({ segment: seg.segment, message, elapsedMs });
    }
    items.sort((a, b) => (a.elapsedMs ?? Infinity) - (b.elapsedMs ?? Infinity));
    return items;
}

function pendingGroupHTML(group) {
    const count = group.ids.length;
    const chips = group.ids
        .map((id) => `<span class="pending-chip">${escapeHTML(id)}</span>`)
        .join("");
    return `
        <div class="pending-group">
            <div class="pending-group__head">
                <span class="pending-group__time">${escapeHTML(formatElapsedCompact(group.elapsedMs))}</span>
                <span class="pending-group__meta">${count} request${count === 1 ? "" : "s"}</span>
            </div>
            <div class="pending-group__chips">${chips}</div>
        </div>`;
}

function failedGroupHTML(item) {
    const when = item.elapsedMs != null ? formatElapsedCompact(item.elapsedMs) : "—";
    return `
        <div class="pending-group pending-group--failed">
            <div class="pending-group__head">
                <span class="pending-group__time pending-group__time--failed">${escapeHTML(when)}</span>
                <span class="pending-group__meta">${escapeHTML(item.segment)}</span>
            </div>
            <div class="pending-group__msg">${escapeHTML(item.message)}</div>
        </div>`;
}

function setPendingPopoverOpen(open) {
    pendingPopoverOpen = open;
    const pop = document.getElementById("pendingPopover");
    const fab = document.getElementById("pendingFab");
    if (pop) pop.hidden = !open;
    if (fab) fab.setAttribute("aria-expanded", open ? "true" : "false");
}

// Renders (or updates in place) the floating button + popover. Updating in
// place instead of rebuilding keeps content live across the 30s refresh without
// replaying the open animation or collapsing an open popover; the entrance
// animation then only plays when the popover actually transitions to visible.
// The open/closed state is preserved via the module-level pendingPopoverOpen.
function renderAttentionAlert(overdue, failed) {
    let popover = document.getElementById("pendingPopover");
    let fab = document.getElementById("pendingFab");

    if (!overdue.length && !failed.length) {
        if (popover) popover.remove();
        if (fab) fab.remove();
        pendingPopoverOpen = false;
        return;
    }

    const overdueTotal = overdue.reduce((n, g) => n + g.ids.length, 0);
    // Badge counts attention items: one per failed segment + one per overdue id.
    const count = failed.length + overdueTotal;
    const badge = count > 99 ? "99+" : String(count);
    const labelParts = [];
    if (failed.length) labelParts.push(`${failed.length} failed workflow${failed.length === 1 ? "" : "s"}`);
    if (overdueTotal) labelParts.push(`${overdueTotal} request${overdueTotal === 1 ? "" : "s"} pending over 24h`);
    const label = labelParts.join(", ");
    // A failure is more severe than a slow-but-pending request: flag the whole
    // control as critical (red) whenever any failure is present.
    const hasFailure = failed.length > 0;

    if (!popover) {
        popover = document.createElement("div");
        popover.id = "pendingPopover";
        popover.className = "pending-popover";
        popover.setAttribute("role", "dialog");
        popover.hidden = !pendingPopoverOpen;
        document.body.appendChild(popover);
    }
    popover.setAttribute("aria-label", label);
    const failedSection = failed.length
        ? `<div class="pending-section pending-section--failed">` +
          `<div class="pending-popover__head">` +
          ICONS.alertTriangle +
          `<span class="pending-popover__title">Failed Workflows</span>` +
          `<span class="pending-popover__badge pending-popover__badge--failed">${failed.length}</span>` +
          `</div>` +
          `<div class="pending-popover__list">${failed.map(failedGroupHTML).join("")}</div>` +
          `</div>`
        : "";
    const overdueSection = overdue.length
        ? `<div class="pending-section">` +
          `<div class="pending-popover__head">` +
          ICONS.alertCircle +
          `<span class="pending-popover__title">Pending Requests</span>` +
          `<span class="pending-popover__badge">24h+</span>` +
          `</div>` +
          `<div class="pending-popover__list">${overdue.map(pendingGroupHTML).join("")}</div>` +
          `</div>`
        : "";
    popover.innerHTML = failedSection + overdueSection;

    if (!fab) {
        fab = document.createElement("button");
        fab.type = "button";
        fab.id = "pendingFab";
        fab.setAttribute("aria-haspopup", "dialog");
        fab.setAttribute("aria-controls", "pendingPopover");
        document.body.appendChild(fab);
    }
    fab.className = hasFailure ? "pending-fab pending-fab--failed" : "pending-fab";
    fab.setAttribute("aria-expanded", pendingPopoverOpen ? "true" : "false");
    fab.setAttribute("aria-label", label);
    fab.setAttribute("title", label);
    fab.innerHTML = `!<span class="pending-fab__count">${escapeHTML(badge)}</span>`;
}

// Fetches ALL segments (unfiltered, so the alert is independent of the table's
// current filters) and refreshes the floating alert. Failures are non-fatal.
async function refreshPendingRequests() {
    try {
        const segments = await fetchAPI("/segments");
        renderAttentionAlert(computePendingOverdue(segments), computeFailed(segments));
    } catch (e) {
        // Non-critical: leave whatever is currently displayed.
    }
}

// ---- Column sorting ----------------------------------------------------------
let sortColumn = null;
let sortDirection = "asc";

function segmentStatusLabel(segment) {
    return segment.status || "Available";
}

function compareSegments(a, b, column, direction) {
    let av, bv;
    switch (column) {
        case "vlan_id":
            av = Number(a.vlan_id) || 0;
            bv = Number(b.vlan_id) || 0;
            break;
        case "dhcp":
            av = a.dhcp ? 1 : 0;
            bv = b.dhcp ? 1 : 0;
            break;
        case "cluster":
            av = (a.cluster_name || "").toLowerCase();
            bv = (b.cluster_name || "").toLowerCase();
            break;
        case "status":
            av = segmentStatusLabel(a).toLowerCase();
            bv = segmentStatusLabel(b).toLowerCase();
            break;
        default:
            av = String(a[column] ?? "").toLowerCase();
            bv = String(b[column] ?? "").toLowerCase();
    }
    const cmp = typeof av === "number" ? av - bv : av < bv ? -1 : av > bv ? 1 : 0;
    return direction === "desc" ? -cmp : cmp;
}

function sortSegments(segments) {
    if (!sortColumn) return segments;
    return segments.slice().sort((a, b) => compareSegments(a, b, sortColumn, sortDirection));
}

function updateSortHeaders() {
    document.querySelectorAll("th[data-sort]").forEach((th) => {
        const col = th.getAttribute("data-sort");
        th.classList.remove("sort-active", "sort-desc");
        th.removeAttribute("aria-sort");
        if (col === sortColumn) {
            th.classList.add("sort-active");
            if (sortDirection === "desc") th.classList.add("sort-desc");
            th.setAttribute("aria-sort", sortDirection === "desc" ? "descending" : "ascending");
        }
    });
}

async function loadSegments(showSkeleton = false) {
    // Every render path below rewrites the table, orphaning the popover's anchor.
    closeReqIdsPopover();
    const container = document.getElementById("segmentsList");
    if (showSkeleton && container) {
        container.innerHTML = rowSkeleton().repeat(8);
        applyColumnVisibility();
    }

    try {
        const params = new URLSearchParams();
        if (currentFilter === "available") params.append("status", "Available");
        else if (currentFilter === "allocated") params.append("status", "Allocated");
        if (currentSite) params.append("site", currentSite);

        const queryString = params.toString();
        const endpoint = "/segments" + (queryString ? "?" + queryString : "");

        let segments = await fetchAPI(endpoint);
        if (!container) return;

        const needle = currentSearchQuery.trim().toLowerCase();
        if (needle) {
            segments = segments.filter((s) => quickSearchMatches(s, needle));
        }

        lastBaseSegments = segments;

        const hasColumnFilters = Object.keys(columnFilters).length > 0;
        if (hasColumnFilters) {
            segments = segments.filter((s) => segmentPassesColumnFilters(s));
        }
        segments = sortSegments(segments);

        const isFiltering = needle.length > 0 || hasColumnFilters;

        if (!segments || segments.length === 0) {
            updateSegmentCount(0);
            container.innerHTML = emptyState(
                ICONS.inbox,
                isFiltering ? "No matches found" : "No segments",
                isFiltering
                    ? "Try a different search term or filter, or clear the current filters."
                    : "No segments match the current filters."
            );
            return;
        }

        updateSegmentCount(segments.length);

        container.innerHTML = segments
            .map((segment) => {
                const statusLabel = segmentStatusLabel(segment);
                const statusClass = statusLabel.toLowerCase();
                const dhcp = segment.dhcp;
                const reqIds = Array.isArray(segment.segment_connectivity_requests)
                    ? segment.segment_connectivity_requests
                    : [];
                const reqIdsBtn = reqIds.length
                    ? `<button type="button" class="req-ids-btn" aria-haspopup="dialog" aria-expanded="false" data-request-ids="${escapeHTML(JSON.stringify(reqIds))}" data-submitted-at="${escapeHTML(segment.segment_connectivity_requests_submitted_at || "")}">Request IDs</button>`
                    : "";
                const failMsg = segment.segment_connectivity_failure;
                const failBtn = failMsg
                    ? `<button type="button" class="conn-failed-btn" aria-haspopup="dialog" aria-expanded="false" data-failure="${escapeHTML(failMsg)}" data-failed-at="${escapeHTML(segment.segment_connectivity_failure_at || "")}">${ICONS.alertTriangle}Workflow failed</button>`
                    : "";
                return `
                <tr>
                    <td data-col="type">${
                        segment.type
                            ? `<span class="badge-type ${typeClass(segment.type)}">${escapeHTML(segment.type)}</span>`
                            : '<span class="cell-muted">—</span>'
                    }</td>
                    <td data-col="site"><span class="site-chip">${escapeHTML(segment.site)}</span></td>
                    <td data-col="vlan_id" class="cell-strong copyable" tabindex="0" data-copy="${escapeHTML(segment.vlan_id)}">${escapeHTML(segment.vlan_id)}${ICONS.copy}</td>
                    <td data-col="epg_name" class="col-epg cell-mono copyable" tabindex="0" data-copy="${escapeHTML(segment.epg_name)}">${escapeHTML(segment.epg_name)}${ICONS.copy}</td>
                    <td data-col="segment" class="cell-mono copyable" tabindex="0" data-copy="${escapeHTML(segment.segment)}">${escapeHTML(segment.segment)}${ICONS.copy}</td>
                    <td data-col="dhcp"><span class="badge-soft ${
                        dhcp ? "dhcp-on" : ""
                    }">${dhcp ? "On" : "Off"}</span></td>
                    <td data-col="cluster">${
                        segment.cluster_name
                            ? escapeHTML(segment.cluster_name)
                            : '<span class="cell-muted">—</span>'
                    }</td>
                    <td data-col="status"><span class="badge ${statusClass}">${statusLabel}</span>${reqIdsBtn}${failBtn}</td>
                </tr>`;
            })
            .join("");
        applyColumnVisibility();
    } catch (error) {
        if (container) {
            updateSegmentCount(0);
            container.innerHTML = emptyState(
                ICONS.alert,
                "Failed to load segments",
                error.message || "Please refresh the page to try again."
            );
        }
    }
}

// ---- Init ------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", function () {
    // Sortable column headers
    document.querySelectorAll("th[data-sort]").forEach((th) => {
        const activateSort = () => {
            const col = th.getAttribute("data-sort");
            if (sortColumn === col) {
                sortDirection = sortDirection === "asc" ? "desc" : "asc";
            } else {
                sortColumn = col;
                sortDirection = "asc";
            }
            updateSortHeaders();
            loadSegments(false);
        };
        th.addEventListener("click", (e) => {
            if (e.target.closest(".col-filter-btn")) return;
            activateSort();
        });
        th.addEventListener("keydown", (e) => {
            if (e.target.closest(".col-filter-btn")) return;
            if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                activateSort();
            }
        });
    });

    // Per-column header filters (Excel-style)
    document.querySelectorAll(".col-filter-btn").forEach((btn) => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            openColumnFilterPopover(btn.getAttribute("data-filter-col"), btn);
        });
    });

    // Status tabs
    document.querySelectorAll(".segmented__tab").forEach((tab) => {
        tab.addEventListener("click", (e) => {
            currentFilter = e.currentTarget.getAttribute("data-filter");
            document.querySelectorAll(".segmented__tab").forEach((t) => {
                t.classList.remove("active");
                t.setAttribute("aria-selected", "false");
            });
            e.currentTarget.classList.add("active");
            e.currentTarget.setAttribute("aria-selected", "true");
            loadSegments(true);
        });
    });

    // Site filter
    document.getElementById("siteFilter").addEventListener("change", (e) => {
        currentSite = e.target.value;
        loadSegments(true);
    });

    // Search
    const searchInput = document.getElementById("searchInput");
    const clearSearch = document.getElementById("clearSearch");
    let searchTimeout;

    searchInput.addEventListener("input", (e) => {
        const query = e.target.value;
        clearSearch.classList.toggle("visible", query.trim().length > 0);

        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            currentSearchQuery = query;
            loadSegments(true);
        }, 300);
    });

    searchInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            clearTimeout(searchTimeout);
            currentSearchQuery = e.target.value;
            loadSegments(true);
        }
    });

    clearSearch.addEventListener("click", () => {
        searchInput.value = "";
        currentSearchQuery = "";
        clearSearch.classList.remove("visible");
        searchInput.focus();
        loadSegments(true);
    });

    // Column visibility ("funnel" picker)
    loadHiddenColumns();
    document.querySelectorAll('#columnsPopover input[type="checkbox"]').forEach((cb) => {
        cb.checked = !hiddenColumns.has(cb.dataset.col);
        cb.addEventListener("change", (e) => {
            toggleColumn(e.target.dataset.col, e.target.checked);
        });
    });
    applyColumnVisibility();

    const columnsBtn = document.getElementById("columnsBtn");
    const columnsPopover = document.getElementById("columnsPopover");
    columnsBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        closeColumnFilterPopover();
        columnsPopover.hidden = !columnsPopover.hidden;
        columnsBtn.setAttribute("aria-expanded", String(!columnsPopover.hidden));
    });

    // Close popovers on outside click / Escape
    document.addEventListener("click", (e) => {
        if (
            openFilterCol &&
            !e.target.closest(".col-filter-btn") &&
            !e.target.closest(".col-filter-popover")
        ) {
            closeColumnFilterPopover();
        }
        const columnsPicker = document.getElementById("columnsPicker");
        if (!columnsPopover.hidden && columnsPicker && !columnsPicker.contains(e.target)) {
            columnsPopover.hidden = true;
            columnsBtn.setAttribute("aria-expanded", "false");
        }
        if (
            reqIdsAnchor &&
            !e.target.closest(".req-ids-btn") &&
            !e.target.closest(".req-ids-popover")
        ) {
            closeReqIdsPopover();
        }
        if (
            connFailedAnchor &&
            !e.target.closest(".conn-failed-btn") &&
            !e.target.closest(".conn-failed-popover")
        ) {
            closeConnFailedPopover();
        }
        // Floating pending-requests alert: toggle on its button, close on outside click.
        if (e.target.closest(".pending-fab")) {
            setPendingPopoverOpen(!pendingPopoverOpen);
        } else if (pendingPopoverOpen && !e.target.closest(".pending-popover")) {
            setPendingPopoverOpen(false);
        }
    });
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            closeColumnFilterPopover();
            closeReqIdsPopover();
            closeConnFailedPopover();
            setPendingPopoverOpen(false);
            columnsPopover.hidden = true;
            columnsBtn.setAttribute("aria-expanded", "false");
        }
    });

    // Click-to-copy (VLAN ID, EPG name, network segment cells) + request-ids popover
    const segmentsList = document.getElementById("segmentsList");
    segmentsList.addEventListener("click", (e) => {
        const reqBtn = e.target.closest(".req-ids-btn");
        if (reqBtn) {
            if (reqIdsAnchor === reqBtn) closeReqIdsPopover();
            else openReqIdsPopover(reqBtn);
            return;
        }
        const failBtn = e.target.closest(".conn-failed-btn");
        if (failBtn) {
            if (connFailedAnchor === failBtn) closeConnFailedPopover();
            else openConnFailedPopover(failBtn);
            return;
        }
        const cell = e.target.closest(".copyable");
        if (cell) handleCopyableActivate(cell);
    });
    segmentsList.addEventListener("keydown", (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        const cell = e.target.closest(".copyable");
        if (!cell) return;
        e.preventDefault();
        handleCopyableActivate(cell);
    });

    // First load
    (async function init() {
        await loadSites();
        await Promise.all([loadStats(true), loadSegments(true)]);
        refreshPendingRequests();
    })().catch(() => {
        showError("Failed to load initial data. Please refresh the page.");
    });

    // Auto-refresh (silent, no skeleton)
    setInterval(() => {
        if (isOnline) {
            loadStats(false);
            loadSegments(false);
            refreshPendingRequests();
        }
    }, 30000);

    // Connection heartbeat
    setInterval(async () => {
        try {
            await fetchAPI("/health");
            updateConnectionStatus(true);
        } catch {
            updateConnectionStatus(false);
        }
    }, 10000);
});
