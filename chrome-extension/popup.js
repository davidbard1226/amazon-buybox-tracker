// Amazon Buybox Tracker - Popup Controller v1.1.0

document.addEventListener('DOMContentLoaded', init);

function init() {
  console.log('🎨 Popup initialized v1.1.0');

  loadSettings();

  // Tab switching
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  // Scrape tab
  document.getElementById('scrapeBtn').addEventListener('click', scrapeCurrentPage);
  document.getElementById('openDashboardBtn').addEventListener('click', openDashboard);

  // Bulk tab
  document.getElementById('bulkInput').addEventListener('input', updateBulkCount);
  document.getElementById('bulkSubmitBtn').addEventListener('click', submitBulkASINs);
  document.getElementById('bulkClearBtn').addEventListener('click', () => {
    document.getElementById('bulkInput').value = '';
    document.getElementById('bulkCount').textContent = '0 ASINs detected';
    document.getElementById('bulkResult').style.display = 'none';
  });

  // Settings tab
  document.getElementById('saveSettingsBtn').addEventListener('click', saveSettings);
  document.getElementById('testConnectionBtn').addEventListener('click', testConnection);

  checkAmazonPage();
}

// ─── Tab switching ────────────────────────────────────────────────────────────
function switchTab(tabName) {
  document.querySelectorAll('.tab-btn').forEach(btn =>
    btn.classList.toggle('active', btn.dataset.tab === tabName));
  document.querySelectorAll('.tab-content').forEach(content =>
    content.classList.toggle('active', content.id === tabName + 'Tab'));
}

// ─── Check if on Amazon page ──────────────────────────────────────────────────
async function checkAmazonPage() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const isAmazon = tab.url && tab.url.includes('amazon.');
    const isProductPage = tab.url && /\/dp\/[A-Z0-9]{10}/i.test(tab.url);

    if (!isAmazon) {
      showStatus('⚠️ Navigate to an Amazon product page to scrape', 'warning');
      document.getElementById('scrapeBtn').disabled = true;
    } else if (!isProductPage) {
      showStatus('ℹ️ Navigate to a specific product page (/dp/ASIN)', 'info');
      document.getElementById('scrapeBtn').disabled = false;
    } else {
      showStatus('✅ Amazon product page detected — ready to scrape!', 'success');
      document.getElementById('scrapeBtn').disabled = false;
    }
  } catch (e) {
    console.warn('checkAmazonPage error:', e);
  }
}

// ─── Scrape current page ──────────────────────────────────────────────────────
async function scrapeCurrentPage() {
  showStatus('📊 Scraping product data...', 'info');
  document.getElementById('scrapeBtn').disabled = true;

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    // Send message to content script
    let response;
    try {
      response = await chrome.tabs.sendMessage(tab.id, { action: 'scrapeProduct' });
    } catch (e) {
      // Content script may not be injected yet — inject it manually
      await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['content.js'] });
      await new Promise(r => setTimeout(r, 500));
      response = await chrome.tabs.sendMessage(tab.id, { action: 'scrapeProduct' });
    }

    if (!response || !response.success) {
      throw new Error('Content script did not return data');
    }

    const productData = response.data;
    displayScrapedData(productData);

    // Send to backend (background handles offer-listing fallback)
    showStatus('📤 Sending to backend...', 'info');
    const backendResponse = await chrome.runtime.sendMessage({
      action: 'sendToBackend',
      data: productData
    });

    if (backendResponse.success) {
      showStatus('✅ Saved to dashboard! ' + (productData.asin || ''), 'success');
    } else {
      showStatus('❌ Failed to send: ' + backendResponse.error, 'error');
    }

  } catch (error) {
    console.error('Scrape error:', error);
    showStatus('❌ ' + error.message, 'error');
  } finally {
    document.getElementById('scrapeBtn').disabled = false;
  }
}

// ─── Display scraped result in popup ─────────────────────────────────────────
function displayScrapedData(data) {
  const resultDiv = document.getElementById('scrapeResult');
  const statusEmoji = { winning: '🟢', losing: '🔴', amazon: '🟡', unknown: '⚪' }[data.buybox_status] || '⚪';
  // Only show offer-listing note if seller is still unknown after resolution
  const offerNote = (data.needs_offer_listing && (!data.seller || data.seller === 'Unknown'))
    ? '<p style="color:#856404;font-size:11px;">⚠️ No buybox on main page — fetching offer-listing...</p>'
    : '';

  resultDiv.innerHTML = `
    <div class="result-card">
      ${data.image_url ? `<img src="${data.image_url}" alt="Product" class="result-img">` : ''}
      <div class="result-info">
        <h3>${(data.title || 'Unknown Product').substring(0, 60)}${data.title && data.title.length > 60 ? '…' : ''}</h3>
        <p><strong>ASIN:</strong> ${data.asin || 'N/A'}</p>
        <p><strong>Price:</strong> ${data.currency || 'ZAR'} ${data.price != null ? Number(data.price).toFixed(2) : 'N/A'}</p>
        <p><strong>Seller:</strong> ${data.seller || 'Unknown'}</p>
        <p><strong>Rating:</strong> ${data.rating ? data.rating + ' ⭐' : 'N/A'} (${data.review_count || 0} reviews)</p>
        <p><strong>Buybox:</strong> <span class="status-${data.buybox_status}">${statusEmoji} ${data.buybox_status || 'unknown'}</span></p>
        ${offerNote}
      </div>
    </div>
  `;
  resultDiv.style.display = 'block';
}

// ─── Open dashboard ───────────────────────────────────────────────────────────
async function openDashboard() {
  const stored = await chrome.storage.sync.get(['backendUrl']);
  const url = (stored.backendUrl || '').trim().replace(/\/+$/, '');
  if (!url) {
    showStatus('❌ Set your backend URL in Settings first', 'error');
    switchTab('settings');
    return;
  }
  chrome.tabs.create({ url });
}

// ─── Parse ASINs / URLs from bulk textarea ────────────────────────────────────
function parseASINsFromText(text) {
  const asinPattern = /[A-Z0-9]{10}/g;
  const lines = text.split(/[\n,;]+/).map(l => l.trim()).filter(Boolean);
  const asins = new Set();

  for (const line of lines) {
    // Try to extract ASIN from URL
    const urlMatch = line.match(/\/dp\/([A-Z0-9]{10})/i);
    if (urlMatch) {
      asins.add(urlMatch[1].toUpperCase());
      continue;
    }
    // Try bare ASIN
    const asinMatch = line.match(/^([A-Z0-9]{10})$/i);
    if (asinMatch) {
      asins.add(asinMatch[1].toUpperCase());
      continue;
    }
    // Search anywhere in the line
    const found = line.toUpperCase().match(asinPattern);
    if (found) found.forEach(a => asins.add(a));
  }

  return [...asins];
}

// ─── Update bulk count as user types ─────────────────────────────────────────
function updateBulkCount() {
  const text = document.getElementById('bulkInput').value;
  const asins = parseASINsFromText(text);
  document.getElementById('bulkCount').textContent =
    asins.length > 0 ? `${asins.length} ASIN${asins.length > 1 ? 's' : ''} detected` : '0 ASINs detected';
}

// ─── Submit bulk ASINs to backend ─────────────────────────────────────────────
async function submitBulkASINs() {
  const text = document.getElementById('bulkInput').value.trim();
  if (!text) {
    showStatus('❌ Please paste some ASINs or URLs first', 'error');
    return;
  }

  const asins = parseASINsFromText(text);
  if (!asins.length) {
    showStatus('❌ No valid ASINs found. ASINs are 10-character codes like B01ARGZ8N0', 'error');
    return;
  }

  document.getElementById('bulkSubmitBtn').disabled = true;
  showStatus(`🚀 Submitting ${asins.length} ASINs to backend...`, 'info');

  try {
    const response = await chrome.runtime.sendMessage({
      action: 'bulkScrapeASINs',
      asins: asins,
      marketplace: 'amazon.co.za'
    });

    const resultDiv = document.getElementById('bulkResult');

    if (response.success) {
      const r = response.result;
      showStatus(`✅ Job started! ${r.total || asins.length} ASINs queued for scraping.`, 'success');
      resultDiv.innerHTML = `
        <div style="font-size:13px; line-height:1.8;">
          <p>✅ <strong>Job ID:</strong> <code style="font-size:11px;">${r.job_id || 'N/A'}</code></p>
          <p>📦 <strong>ASINs queued:</strong> ${r.total || asins.length}</p>
          <p>⏳ <strong>Status:</strong> ${r.status || 'queued'}</p>
          <p style="color:#666;font-size:11px;">Check your dashboard — products will appear as they are scraped.</p>
          <button id="viewDashAfterBulk" class="btn btn-secondary" style="margin-top:8px;font-size:12px;padding:6px 12px;">
            🖥️ Open Dashboard
          </button>
        </div>
      `;
      resultDiv.style.display = 'block';
      document.getElementById('viewDashAfterBulk').addEventListener('click', openDashboard);
    } else {
      showStatus('❌ Bulk submit failed: ' + response.error, 'error');
      resultDiv.innerHTML = `<p style="color:#721c24;font-size:13px;">❌ ${response.error}</p>`;
      resultDiv.style.display = 'block';
    }

  } catch (error) {
    console.error('Bulk submit error:', error);
    showStatus('❌ ' + error.message, 'error');
  } finally {
    document.getElementById('bulkSubmitBtn').disabled = false;
  }
}

// ─── Status bar ───────────────────────────────────────────────────────────────
function showStatus(message, type = 'info') {
  const statusDiv = document.getElementById('status');
  statusDiv.textContent = message;
  statusDiv.className = 'status ' + type;
  statusDiv.style.display = 'block';
  if (type !== 'error') {
    setTimeout(() => { statusDiv.style.display = 'none'; }, 6000);
  }
}

// ─── Load settings from storage ───────────────────────────────────────────────
async function loadSettings() {
  const response = await chrome.runtime.sendMessage({ action: 'getSettings' });
  document.getElementById('backendUrl').value = response.backendUrl || '';
  document.getElementById('mySellerName').value = response.mySellerName || '';
}

// ─── Save settings ────────────────────────────────────────────────────────────
async function saveSettings() {
  const backendUrl = document.getElementById('backendUrl').value.trim().replace(/\/+$/, '');
  const mySellerName = document.getElementById('mySellerName').value.trim();

  if (!backendUrl) {
    showStatus('❌ Please enter your Render.com backend URL', 'error');
    return;
  }

  await chrome.runtime.sendMessage({
    action: 'saveSettings',
    backendUrl,
    mySellerName
  });

  showStatus('✅ Settings saved!', 'success');
}

// ─── Test connection ──────────────────────────────────────────────────────────
async function testConnection() {
  const backendUrl = document.getElementById('backendUrl').value.trim().replace(/\/+$/, '');

  if (!backendUrl) {
    showStatus('❌ Please enter a backend URL first', 'error');
    return;
  }

  showStatus('🔄 Testing connection...', 'info');

  try {
    const response = await fetch(`${backendUrl}/api/health`);
    if (response.ok) {
      const data = await response.json();
      showStatus(`✅ Connected! Tracking ${data.tracked_asins || 0} ASINs. DB: ${data.database}`, 'success');
    } else {
      showStatus('⚠️ Backend responded with error: ' + response.status, 'warning');
    }
  } catch (error) {
    showStatus('❌ Connection failed: ' + error.message + ' — check your URL', 'error');
  }
}
