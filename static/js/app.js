// Global state
let currentFilter = 'all';
let currentSite = '';
let currentSearchQuery = '';
let isOnline = true;
let isDarkMode = localStorage.getItem('darkMode') === 'true';
let allSites = []; // All configured sites
let isAuthenticated = false; // Authentication state

// Export Functions - Make explicitly global
window.exportData = async function exportData(format) {
    try {
        let endpoint = '';
        let filename = '';

        if (format === 'csv') {
            endpoint = '/export/segments/csv';
            filename = 'segments.csv';
        } else if (format === 'excel') {
            endpoint = '/export/segments/excel';
            filename = 'segments.xlsx';
        }

        // Add current filter parameters
        const params = new URLSearchParams();

        if (currentFilter === 'available') {
            params.append('allocated', 'false');
        } else if (currentFilter === 'allocated') {
            params.append('allocated', 'true');
        }

        if (currentSite) {
            params.append('site', currentSite);
        }

        const queryString = params.toString();
        const fullEndpoint = queryString ? `${endpoint}?${queryString}` : endpoint;

        const response = await fetch(`/api${fullEndpoint}`);

        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);

            showSuccess(`${format.toUpperCase()} export completed`);
        } else {
            const error = await response.json();
            showError(error.detail || 'Export failed');
        }
    } catch (error) {
        console.error('Export error:', error);
        showError('Export failed. Please try again.');
    }
};

window.exportStats = async function exportStats(format) {
    try {
        const response = await fetch('/api/export/stats/csv');

        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = url;
            a.download = 'site_statistics.csv';
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);

            showSuccess('Statistics export completed');
        } else {
            const error = await response.json();
            showError(error.detail || 'Export failed');
        }
    } catch (error) {
        console.error('Export stats error:', error);
        showError('Export failed. Please try again.');
    }
};

// Utility functions
function showError(message) {
    const banner = document.getElementById('errorBanner');
    banner.textContent = message;
    banner.style.display = 'block';
    setTimeout(() => {
        banner.style.display = 'none';
    }, 5000);
}

function showVlanIdImmutableError(errorDetail) {
    const message = `
        🚫 VLAN ID Cannot Be Changed

        Current VLAN ID: ${errorDetail.current_vlan_id}
        Attempted VLAN ID: ${errorDetail.attempted_vlan_id}

        💡 Solution: Create a new segment with the desired VLAN ID and delete the old one if needed.
    `.trim();

    const banner = document.getElementById('errorBanner');
    banner.innerHTML = message.replace(/\n/g, '<br>');
    banner.style.display = 'block';
    banner.style.padding = '15px';
    banner.style.fontSize = '14px';
    banner.style.lineHeight = '1.4';

    setTimeout(() => {
        banner.style.display = 'none';
        banner.style.padding = '';
        banner.style.fontSize = '';
        banner.style.lineHeight = '';
    }, 8000);
}

function showSuccess(message) {
    const banner = document.getElementById('successBanner');
    banner.textContent = message;
    banner.style.display = 'block';
    setTimeout(() => {
        banner.style.display = 'none';
    }, 5000);
}

function updateConnectionStatus(online) {
    isOnline = online;
    const dot = document.getElementById('statusDot');
    const text = document.getElementById('statusText');

    if (online) {
        dot.classList.remove('offline');
        text.textContent = 'Connected';
    } else {
        dot.classList.add('offline');
        text.textContent = 'Offline';
    }
}

async function fetchAPI(endpoint, options = {}) {
    try {
        console.log('Fetching API:', endpoint);
        const response = await fetch(`/api${endpoint}`, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            }
        });

        console.log('API response status:', response.status);
        updateConnectionStatus(true);

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Unknown error' }));

            // Handle Pydantic validation errors (detail is an array)
            if (Array.isArray(error.detail)) {
                const messages = error.detail.map(err => err.msg || err.message || 'Validation error').join('; ');
                throw new Error(messages);
            }

            throw new Error(error.detail || `HTTP ${response.status}`);
        }

        const result = await response.json();
        console.log('API response data:', result);
        return result;
    } catch (error) {
        console.error('API fetch error:', error);
        if (error.message.includes('Failed to fetch') || error.message.includes('NetworkError')) {
            updateConnectionStatus(false);
            throw new Error('Connection lost. Please check your network.');
        }
        throw error;
    }
}

async function loadSites() {
    try {
        console.log('Loading sites...');
        const data = await fetchAPI('/sites');
        console.log('Sites data received:', data);
        const sites = data.sites;
        allSites = sites;

        const segmentSiteSelect = document.getElementById('segmentSite');
        const allocationSiteSelect = document.getElementById('allocationSite');
        const siteFilterSelect = document.getElementById('siteFilter');

        segmentSiteSelect.innerHTML = '<option value="">Select site...</option>';
        allocationSiteSelect.innerHTML = '<option value="">Select site...</option>';
        siteFilterSelect.innerHTML = '<option value="">All Sites</option>';

        sites.forEach(site => {
            segmentSiteSelect.innerHTML += `<option value="${site}">${site}</option>`;
            allocationSiteSelect.innerHTML += `<option value="${site}">${site}</option>`;
            siteFilterSelect.innerHTML += `<option value="${site}">${site}</option>`;
        });

        console.log('Sites loaded successfully:', sites);
    } catch (error) {
        console.error('Failed to load sites:', error);
        showError('Failed to load sites: ' + error.message);
    }
}

async function loadStats() {
    try {
        const stats = await fetchAPI('/stats');
        const container = document.getElementById('statsGrid');

        if (stats.length === 0) {
            container.innerHTML = '<div class="stat-card"><h3>No sites configured</h3></div>';
            return;
        }

        container.innerHTML = stats.map(stat => `
            <div class="stat-card">
                <h3>${stat.site}</h3>
                <div class="stat-item">
                    <span>Total Segments:</span>
                    <strong>${stat.total_segments}</strong>
                </div>
                <div class="stat-item">
                    <span>Allocated:</span>
                    <strong>${stat.allocated}</strong>
                </div>
                <div class="stat-item">
                    <span>Available:</span>
                    <strong style="color: ${stat.available > 0 ? '#48bb78' : '#f56565'}">${stat.available}</strong>
                </div>
                <div class="stat-item">
                    <span>Utilization:</span>
                    <strong>${stat.utilization}%</strong>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: ${stat.utilization}%"></div>
                </div>
            </div>
        `).join('');
    } catch (error) {
        console.error('Failed to load stats:', error);
    }
}

async function loadSegments() {
    try {
        let endpoint = '/segments';
        const params = new URLSearchParams();

        // If there's a search query, use search endpoint
        if (currentSearchQuery.trim()) {
            endpoint = '/segments/search';
            params.append('q', currentSearchQuery.trim());
        }

        if (currentFilter === 'available') {
            params.append('allocated', 'false');
        } else if (currentFilter === 'allocated') {
            params.append('allocated', 'true');
        }

        if (currentSite) {
            params.append('site', currentSite);
        }

        const queryString = params.toString();
        if (queryString) {
            endpoint += '?' + queryString;
        }

        const segments = await fetchAPI(endpoint);
        const container = document.getElementById('segmentsList');

        if (segments.length === 0) {
            container.innerHTML = '<tr><td colspan="8" class="empty-state">No segments found</td></tr>';
            return;
        }

        container.innerHTML = segments.map(segment => {
            const isAllocated = segment.cluster_name && !segment.released;
            return `
                <tr>
                    <td>${segment.site}</td>
                    <td><strong>${segment.vlan_id}</strong></td>
                    <td><code>${segment.epg_name}</code></td>
                    <td><code>${segment.segment}</code></td>
                    <td>${segment.dhcp ? 'Yes' : 'No'}</td>
                    <td>${segment.cluster_name || '-'}</td>
                    <td>
                        <span class="badge ${isAllocated ? 'allocated' : 'available'}">
                            ${isAllocated ? 'Allocated' : 'Available'}
                        </span>
                    </td>
                    <td>
                        ${isAuthenticated ? `
                            <button class="edit"
                                    onclick="editSegment('${segment._id}')"
                                    data-segment-id="${segment._id}">
                                Edit
                            </button>
                            ${isAllocated ? `
                                <button class="release"
                                        onclick="releaseSegment('${segment.cluster_name}', '${segment.site}')"
                                        data-cluster="${segment.cluster_name}"
                                        data-site="${segment.site}">
                                    Release
                                </button>
                            ` : `
                                <button class="delete"
                                        onclick="deleteSegment('${segment._id}')"
                                        data-segment-id="${segment._id}">
                                    Delete
                                </button>
                            `}
                        ` : '<span style="color: #999; font-style: italic;">-</span>'}
                    </td>
                </tr>
            `;
        }).join('');
    } catch (error) {
        console.error('Failed to load segments:', error);
        document.getElementById('segmentsList').innerHTML =
            '<tr><td colspan="8" class="empty-state">Failed to load segments</td></tr>';
    }
}

async function deleteSegment(segmentId) {
    if (!isAuthenticated) {
        showError('Please login to delete segments');
        return;
    }
    if (!confirm('Are you sure you want to delete this segment?')) return;

    try {
        const button = document.querySelector(`button[data-segment-id="${segmentId}"]`);
        if (button) button.disabled = true;

        await fetchAPI(`/segments/${segmentId}`, { method: 'DELETE' });
        showSuccess('Segment deleted successfully');
        await Promise.all([loadSegments(), loadStats()]);
    } catch (error) {
        showError(`Failed to delete segment: ${error.message}`);
        const button = document.querySelector(`button[data-segment-id="${segmentId}"]`);
        if (button) button.disabled = false;
    }
}

async function releaseSegment(clusterName, site) {
    if (!isAuthenticated) {
        showError('Please login to release segments');
        return;
    }
    if (!confirm(`Release segment for ${clusterName} at ${site}?`)) return;

    try {
        const button = document.querySelector(`button[data-cluster="${clusterName}"][data-site="${site}"]`);
        if (button) button.disabled = true;

        await fetchAPI('/release-vlan', {
            method: 'POST',
            body: JSON.stringify({ cluster_name: clusterName, site: site })
        });

        showSuccess(`Segment released for ${clusterName} at ${site}`);
        await Promise.all([loadSegments(), loadStats()]);
    } catch (error) {
        showError(`Failed to release segment: ${error.message}`);
        const button = document.querySelector(`button[data-cluster="${clusterName}"][data-site="${site}"]`);
        if (button) button.disabled = false;
    }
}

async function importBulk() {
    if (!isAuthenticated) {
        showError('Please login to import segments');
        return;
    }
    const textarea = document.getElementById('bulkImport');
    const csvData = textarea.value.trim();

    if (!csvData) {
        showError('Please enter CSV data to import');
        return;
    }

    const lines = csvData.split(/\r?\n/).filter(l => l.trim().length > 0);
    console.log(`Parsing ${lines.length} CSV lines`);
    const segments = [];
    const skippedRows = [];

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const parts = line.split(',').map(p => p.trim());

        // Format: site,vlan_id,epg_name,segment,dhcp,description
        if (parts.length < 5) {
            console.warn(`Row ${i + 1}: Skipped - only ${parts.length} columns found (expected at least 5). Line: ${line}`);
            skippedRows.push(`Row ${i + 1}: Insufficient columns (found ${parts.length}, need 5)`);
            continue;
        }

        const vlan = parseInt(parts[1], 10);
        if (!Number.isFinite(vlan) || vlan < 1 || vlan > 4094) {
            console.warn(`Row ${i + 1}: Skipped - invalid VLAN ID '${parts[1]}'. Line: ${line}`);
            skippedRows.push(`Row ${i + 1}: Invalid VLAN ID '${parts[1]}' (must be 1-4094)`);
            continue;
        }

        const dhcp = parts[4].toLowerCase() === 'true';

        segments.push({
            site: parts[0],
            vlan_id: vlan,
            epg_name: parts[2],
            segment: parts[3],
            dhcp: dhcp,
            description: parts[5] || ''
        });
    }

    console.log(`Parsed ${segments.length} valid segments, skipped ${skippedRows.length} rows`);

    if (segments.length === 0) {
        let errorMsg = 'No valid segments found in CSV data.';
        if (skippedRows.length > 0) {
            errorMsg += '\n\nIssues found:\n' + skippedRows.slice(0, 5).join('\n');
            if (skippedRows.length > 5) {
                errorMsg += `\n... and ${skippedRows.length - 5} more issues`;
            }
        }
        errorMsg += '\n\nExpected format: site,vlan_id,epg_name,segment,dhcp,description';
        showError(errorMsg);
        return;
    }

    try {
        const result = await fetchAPI('/segments/bulk', {
            method: 'POST',
            body: JSON.stringify(segments)
        });

        if (result.errors && result.errors.length > 0) {
            showError(`Created ${result.created} segments. Errors: ${result.errors.join(', ')}`);
        } else {
            showSuccess(`Successfully imported ${result.created} segments`);
        }

        textarea.value = '';
        await Promise.all([loadSegments(), loadStats()]);
    } catch (error) {
        showError(`Failed to import segments: ${error.message}`);
    }
}

// Authentication functions
async function checkAuthStatus() {
    try {
        const response = await fetchAPI('/auth/status');
        isAuthenticated = response.authenticated;
        updateUIAuthState();
        return isAuthenticated;
    } catch (error) {
        console.error('Failed to check auth status:', error);
        isAuthenticated = false;
        updateUIAuthState();
        return false;
    }
}

async function handleLogin(username, password) {
    try {
        const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ username, password })
        });

        if (response.ok) {
            isAuthenticated = true;
            updateUIAuthState();
            showSuccess('Login successful');
            return true;
        } else {
            const error = await response.json();
            showLoginError(error.detail || 'Invalid username or password');
            return false;
        }
    } catch (error) {
        console.error('Login error:', error);
        showLoginError('Login failed. Please try again.');
        return false;
    }
}

async function handleLogout() {
    try {
        await fetch('/api/auth/logout', {
            method: 'POST'
        });
        isAuthenticated = false;
        updateUIAuthState();
        showSuccess('Logged out successfully');
    } catch (error) {
        console.error('Logout error:', error);
        isAuthenticated = false;
        updateUIAuthState();
    }
}

function showLoginError(message) {
    const errorDiv = document.getElementById('loginError');
    if (errorDiv) {
        errorDiv.textContent = message;
        errorDiv.style.display = 'block';
    }
}

function updateUIAuthState() {
    const loginModal = document.getElementById('loginModal');
    const loginBtn = document.getElementById('loginBtn');
    const authSection = document.getElementById('authSection');
    const logoutBtn = document.getElementById('logoutBtn');
    const userGreeting = document.getElementById('userGreeting');

    const addSegmentCard = document.getElementById('addSegmentCard');
    const allocateCard = document.getElementById('allocateCard');
    const bulkImportCard = document.getElementById('bulkImportCard');

    const actionButtons = [
        document.getElementById('addSegmentBtn'),
        document.getElementById('allocateBtn'),
        document.querySelector('button[onclick="importBulk()"]')
    ];

    const actionForms = [
        document.getElementById('addSegmentForm'),
        document.getElementById('allocateForm')
    ];

    if (isAuthenticated) {
        if (loginModal) loginModal.style.display = 'none';

        if (loginBtn) loginBtn.style.display = 'none';
        if (authSection) {
            authSection.style.display = 'flex';
            authSection.style.alignItems = 'center';
        }
        if (userGreeting) userGreeting.textContent = 'Logged in';

        if (addSegmentCard) addSegmentCard.style.display = 'block';
        if (allocateCard) allocateCard.style.display = 'block';
        if (bulkImportCard) bulkImportCard.style.display = 'block';

        actionButtons.forEach(btn => {
            if (btn) btn.disabled = false;
        });

        actionForms.forEach(form => {
            if (form) {
                const inputs = form.querySelectorAll('input, select, textarea, button');
                inputs.forEach(input => {
                    if (input.type !== 'submit') input.disabled = false;
                });
            }
        });

        const bulkImport = document.getElementById('bulkImport');
        if (bulkImport) bulkImport.disabled = false;

        loadSegments();
    } else {
        if (loginModal) loginModal.style.display = 'none';

        if (loginBtn) loginBtn.style.display = 'inline-block';
        if (authSection) authSection.style.display = 'none';

        if (addSegmentCard) addSegmentCard.style.display = 'none';
        if (allocateCard) allocateCard.style.display = 'none';
        if (bulkImportCard) bulkImportCard.style.display = 'none';

        loadSegments();
    }
}

function showLoginModal() {
    const loginModal = document.getElementById('loginModal');
    if (loginModal) {
        loginModal.style.display = 'block';
        setTimeout(() => {
            const usernameField = document.getElementById('loginUsername');
            if (usernameField) usernameField.focus();
        }, 100);
    }
}

function closeLoginModal() {
    const loginModal = document.getElementById('loginModal');
    if (loginModal) {
        loginModal.style.display = 'none';
        const loginForm = document.getElementById('loginForm');
        if (loginForm) loginForm.reset();
        const loginError = document.getElementById('loginError');
        if (loginError) loginError.style.display = 'none';
    }
}

// Make functions globally accessible
window.showLoginModal = showLoginModal;
window.closeLoginModal = closeLoginModal;
window.handleLogout = handleLogout;

document.addEventListener('DOMContentLoaded', function() {
    // Setup login button handler
    document.getElementById('loginBtn').addEventListener('click', () => {
        showLoginModal();
    });

    // Setup login form handler
    document.getElementById('loginForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = document.getElementById('loginUsername').value;
        const password = document.getElementById('loginPassword').value;

        const submitBtn = e.target.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        submitBtn.textContent = 'Logging in...';

        const success = await handleLogin(username, password);

        submitBtn.disabled = false;
        submitBtn.textContent = 'Login';

        if (success) closeLoginModal();
    });

    // Setup logout button handler
    document.getElementById('logoutBtn').addEventListener('click', async () => {
        await handleLogout();
    });

    // Close login modal when clicking outside
    document.addEventListener('click', (e) => {
        const loginModal = document.getElementById('loginModal');
        if (loginModal && e.target === loginModal) closeLoginModal();
    });

    // Check auth status on page load
    checkAuthStatus();

    document.getElementById('addSegmentForm').addEventListener('submit', async (e) => {
        e.preventDefault();

        const button = document.getElementById('addSegmentBtn');
        button.disabled = true;

        const segment = {
            site: document.getElementById('segmentSite').value,
            vlan_id: parseInt(document.getElementById('vlanId').value),
            epg_name: document.getElementById('epgName').value,
            segment: document.getElementById('networkSegment').value,
            dhcp: document.getElementById('segmentDhcp').checked,
            description: document.getElementById('segmentDescription').value
        };

        try {
            await fetchAPI('/segments', {
                method: 'POST',
                body: JSON.stringify(segment)
            });

            showSuccess('Segment created successfully');
            e.target.reset();
            await Promise.all([loadSegments(), loadStats()]);
        } catch (error) {
            showError(`Failed to create segment: ${error.message}`);
        } finally {
            button.disabled = false;
        }
    });

    document.getElementById('allocateForm').addEventListener('submit', async (e) => {
        e.preventDefault();

        const button = document.getElementById('allocateBtn');
        button.disabled = true;

        const request = {
            cluster_name: document.getElementById('clusterName').value,
            site: document.getElementById('allocationSite').value
        };

        try {
            const result = await fetchAPI('/allocate-vlan', {
                method: 'POST',
                body: JSON.stringify(request)
            });

            document.getElementById('allocationResult').innerHTML = `
                <div style="padding: 15px; background: #48bb78; color: white; border-radius: 5px;">
                    <strong>✓ Success!</strong><br>
                    VLAN ID: <strong>${result.vlan_id}</strong><br>
                    EPG: <strong>${result.epg_name}</strong><br>
                    Network: <strong>${result.segment}</strong><br>
                    Cluster: ${result.cluster_name}
                </div>
            `;

            await Promise.all([loadSegments(), loadStats()]);
        } catch (error) {
            document.getElementById('allocationResult').innerHTML = `
                <div style="padding: 15px; background: #f56565; color: white; border-radius: 5px;">
                    <strong>✗ Error:</strong> ${error.message}
                </div>
            `;
        } finally {
            button.disabled = false;
        }
    });

    // Tab switching
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', (e) => {
            const filter = e.target.getAttribute('data-filter');
            currentFilter = filter;

            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            e.target.classList.add('active');

            loadSegments();
        });
    });

    // Site filter
    document.getElementById('siteFilter').addEventListener('change', (e) => {
        currentSite = e.target.value;
        loadSegments();
    });

    // Search functionality
    const searchInput = document.getElementById('searchInput');
    const clearSearch = document.getElementById('clearSearch');
    let searchTimeout;

    searchInput.addEventListener('input', (e) => {
        const query = e.target.value;

        if (query.trim()) {
            clearSearch.classList.add('visible');
        } else {
            clearSearch.classList.remove('visible');
        }

        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            currentSearchQuery = query;
            loadSegments();
        }, 300);
    });

    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            clearTimeout(searchTimeout);
            currentSearchQuery = e.target.value;
            loadSegments();
        }
    });

    clearSearch.addEventListener('click', () => {
        searchInput.value = '';
        currentSearchQuery = '';
        clearSearch.classList.remove('visible');
        loadSegments();
    });

    // Initialize application
    async function init() {
        try {
            console.log('Initializing application...');
            await checkAuthStatus();
            await loadSites();
            console.log('Sites loaded, loading stats and segments...');
            await Promise.all([loadStats(), loadSegments()]);
            console.log('Application initialized successfully');
        } catch (error) {
            console.error('Failed to initialize:', error);
            showError('Failed to load initial data. Please refresh the page.');
        }
    }

    init();

    // Auto-refresh data every 30 seconds
    setInterval(() => {
        if (isOnline) {
            loadStats();
            loadSegments();
        }
    }, 30000);

    // Check connection status
    setInterval(async () => {
        try {
            await fetchAPI('/health');
            updateConnectionStatus(true);
        } catch {
            updateConnectionStatus(false);
        }
    }, 10000);

    initTheme();
});

// Edit segment functionality
async function editSegment(segmentId) {
    if (!isAuthenticated) {
        showError('Please login to edit segments');
        return;
    }
    try {
        const segment = await fetchAPI(`/segments/${segmentId}`);
        showEditModal(segment);
    } catch (error) {
        console.error('Failed to load segment for editing:', error);
        showError('Failed to load segment details for editing');
    }
}

function showEditModal(segment) {
    const modalHTML = `
        <div id="editModal" class="modal">
            <div class="modal-content">
                <div class="modal-header">
                    <h3>Edit Segment</h3>
                    <button class="close-modal" onclick="closeEditModal()">&times;</button>
                </div>
                <form id="editSegmentForm">
                    <div class="form-group">
                        <label for="editSite">Site</label>
                        <select id="editSite" required>
                            <option value="">Select site...</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="editVlanId">VLAN ID</label>
                        <input type="number" id="editVlanId" min="1" max="4094" value="${segment.vlan_id}" required readonly>
                    </div>
                    <div class="form-group">
                        <label for="editEpgName">EPG Name</label>
                        <input type="text" id="editEpgName" value="${segment.epg_name}" required>
                    </div>
                    <div class="form-group">
                        <label for="editNetworkSegment">Network Segment</label>
                        <input type="text" id="editNetworkSegment" value="${segment.segment}" required>
                    </div>
                    <div class="form-group">
                        <label class="checkbox-label">
                            <input type="checkbox" id="editDhcp" ${segment.dhcp ? 'checked' : ''}>
                            <span>DHCP Enabled</span>
                        </label>
                    </div>
                    <div class="form-group">
                        <label for="editDescription">Description (Optional)</label>
                        <input type="text" id="editDescription" value="${segment.description || ''}" placeholder="Optional description">
                    </div>
                    <div class="form-group">
                        <label for="editClusterName">Cluster Name(s)</label>
                        <input type="text" id="editClusterName" value="${segment.cluster_name || ''}" placeholder="cluster1,cluster2 for shared segments">
                        <small style="color: #666; font-size: 12px;">Use commas to separate multiple clusters for shared segments. Leave empty to release allocation.</small>
                    </div>
                    <div class="modal-actions">
                        <button type="button" class="btn btn-secondary" onclick="closeEditModal()">Cancel</button>
                        <button type="submit" class="btn btn-primary">Update Segment</button>
                    </div>
                </form>
            </div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHTML);

    loadSitesForEdit(segment.site);

    document.getElementById('editSegmentForm').addEventListener('submit', (e) => {
        e.preventDefault();
        updateSegment(segment._id);
    });

    document.getElementById('editModal').style.display = 'block';
}

async function loadSitesForEdit(selectedSite) {
    try {
        const data = await fetchAPI('/sites');
        const select = document.getElementById('editSite');

        select.innerHTML = '<option value="">Select site...</option>';
        data.sites.forEach(site => {
            const option = document.createElement('option');
            option.value = site;
            option.textContent = site;
            if (site.toLowerCase() === (selectedSite || '').toLowerCase()) {
                option.selected = true;
            }
            select.appendChild(option);
        });
    } catch (error) {
        console.error('Failed to load sites for edit:', error);
    }
}

async function updateSegment(segmentId) {
    const form = document.getElementById('editSegmentForm');

    const segmentData = {
        site: document.getElementById('editSite').value,
        vlan_id: parseInt(document.getElementById('editVlanId').value),
        epg_name: document.getElementById('editEpgName').value.trim(),
        segment: document.getElementById('editNetworkSegment').value.trim(),
        dhcp: document.getElementById('editDhcp').checked,
        description: document.getElementById('editDescription').value.trim()
    };

    const clusterField = document.getElementById('editClusterName');
    const clusterName = clusterField.value.trim();

    try {
        const updateBtn = form.querySelector('button[type="submit"]');
        updateBtn.disabled = true;
        updateBtn.textContent = 'Updating...';

        await fetchAPI(`/segments/${segmentId}/clusters`, {
            method: 'PUT',
            body: JSON.stringify({ cluster_names: clusterName })
        });

        await fetchAPI(`/segments/${segmentId}`, {
            method: 'PUT',
            body: JSON.stringify(segmentData)
        });

        closeEditModal();
        showSuccess('Segment updated successfully');
        await Promise.all([loadSegments(), loadStats()]);
    } catch (error) {
        console.error('Failed to update segment:', error);

        if (error.detail && error.detail.error === 'vlan_id_immutable') {
            showVlanIdImmutableError(error.detail);
        } else {
            showError('Failed to update segment: ' + error.message);
        }
    } finally {
        const updateBtn = form.querySelector('button[type="submit"]');
        if (updateBtn) {
            updateBtn.disabled = false;
            updateBtn.textContent = 'Update Segment';
        }
    }
}

function closeEditModal() {
    const modal = document.getElementById('editModal');
    if (modal) modal.remove();
}

// Close modal when clicking outside
document.addEventListener('click', (e) => {
    const modal = document.getElementById('editModal');
    if (modal && e.target === modal) closeEditModal();
});

// Theme management
function initTheme() {
    const themeToggle = document.getElementById('themeToggle');
    const themeIcon = document.getElementById('themeIcon');
    const themeText = document.getElementById('themeText');

    applyTheme(isDarkMode);

    themeToggle.addEventListener('click', () => {
        isDarkMode = !isDarkMode;
        applyTheme(isDarkMode);
        localStorage.setItem('darkMode', isDarkMode.toString());
    });
}

function applyTheme(darkMode) {
    const themeIcon = document.getElementById('themeIcon');
    const themeText = document.getElementById('themeText');

    if (darkMode) {
        document.documentElement.setAttribute('data-theme', 'dark');
        themeIcon.textContent = '☀️';
        themeText.textContent = 'Light';
    } else {
        document.documentElement.removeAttribute('data-theme');
        themeIcon.textContent = '🌙';
        themeText.textContent = 'Dark';
    }
}
