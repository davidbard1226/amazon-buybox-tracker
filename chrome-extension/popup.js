// Amazon Buybox Tracker - Popup Controller

document.addEventListener('DOMContentLoaded', init);

let currentTab = 'scrape';

function init() {
  console.log('🎨 Popup initialized');
  
  // Load settings
  loadSettings();
  
  // Tab switching
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });
  
  // Scrape button
  document.getElementById('scrapeBtn').addEventListener('click', scrapeCurrentPage);
  
  // Settings buttons
  document.getElementById('saveSettingsBtn').addEventListener('click', saveSettings);
  document.getElementById('testConnectionBtn').addEventListener('click', testConnection);
  
  // Check if we're on an Amazon product page
  checkAmazonPage();
}

function switchTab(tabName) {
  currentTab = tabName;
  
  // Update tab buttons
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });
  
  // Update tab content
  document.querySelectorAll('.tab-content').forEach(content => {
    content.classList.toggle('active', content.id === tabName + 'Tab');
  });
}

async function checkAmazonPage() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  
  if (!tab.url.includes('amazon.')) {
    showStatus('⚠️ Please navigate to an Amazon product page', 'warning');
    document.getElementById('scrapeBtn').disabled = true;
  } else {
    showStatus('✅ Ready to scrape!', 'success');
    document.getElementById('scrapeBtn').disabled = false;
  }
}

async function scrapeCurrentPage() {
  showStatus('📊 Scraping product data...', 'info');
  document.getElementById('scrapeBtn').disabled = true;
  
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    
    // Inject and execute content script
    const response = await chrome.tabs.sendMessage(tab.id, { action: 'scrapeProduct' });
    
    if (response.success) {
      const productData = response.data;
      
      // Display scraped data
      displayScrapedData(productData);
      
      // Send to backend
      showStatus('📤 Sending to backend...', 'info');
      const backendResponse = await chrome.runtime.sendMessage({
        action: 'sendToBackend',
        data: productData
      });
      
      if (backendResponse.success) {
        showStatus('✅ Product saved to dashboard!', 'success');
      } else {
        showStatus('❌ Failed to save: ' + backendResponse.error, 'error');
      }
    }
    
  } catch (error) {
    console.error('Scrape error:', error);
    showStatus('❌ Error: ' + error.message, 'error');
  } finally {
    document.getElementById('scrapeBtn').disabled = false;
  }
}

function displayScrapedData(data) {
  const resultDiv = document.getElementById('scrapeResult');
  resultDiv.innerHTML = `
    <div class="result-card">
      ${data.imageUrl ? `<img src="${data.imageUrl}" alt="Product" class="result-img">` : ''}
      <div class="result-info">
        <h3>${data.title || 'Unknown Product'}</h3>
        <p><strong>ASIN:</strong> ${data.asin || 'N/A'}</p>
        <p><strong>Price:</strong> ${data.currency} ${data.price ? data.price.toFixed(2) : 'N/A'}</p>
        <p><strong>Seller:</strong> ${data.seller || 'Unknown'}</p>
        <p><strong>Rating:</strong> ${data.rating ? data.rating + ' ⭐' : 'N/A'} (${data.reviewCount || 0} reviews)</p>
        <p><strong>Status:</strong> <span class="status-${data.buyboxStatus}">${data.buyboxStatus}</span></p>
      </div>
    </div>
  `;
  resultDiv.style.display = 'block';
}

function showStatus(message, type = 'info') {
  const statusDiv = document.getElementById('status');
  statusDiv.textContent = message;
  statusDiv.className = 'status ' + type;
  statusDiv.style.display = 'block';
  
  // Auto-hide after 5 seconds unless it's an error
  if (type !== 'error') {
    setTimeout(() => {
      statusDiv.style.display = 'none';
    }, 5000);
  }
}

async function loadSettings() {
  const response = await chrome.runtime.sendMessage({ action: 'getSettings' });
  
  document.getElementById('backendUrl').value = response.backendUrl || '';
  document.getElementById('mySellerName').value = response.mySellerName || '';
}

async function saveSettings() {
  const backendUrl = document.getElementById('backendUrl').value.trim();
  const mySellerName = document.getElementById('mySellerName').value.trim();
  
  if (!backendUrl) {
    showStatus('❌ Please enter a backend URL', 'error');
    return;
  }
  
  await chrome.runtime.sendMessage({
    action: 'saveSettings',
    backendUrl: backendUrl,
    mySellerName: mySellerName
  });
  
  showStatus('✅ Settings saved!', 'success');
}

async function testConnection() {
  const backendUrl = document.getElementById('backendUrl').value.trim();
  
  if (!backendUrl) {
    showStatus('❌ Please enter a backend URL first', 'error');
    return;
  }
  
  showStatus('🔄 Testing connection...', 'info');
  
  try {
    const response = await fetch(`${backendUrl}/api/health`);
    
    if (response.ok) {
      const data = await response.json();
      showStatus('✅ Connection successful! Backend is running.', 'success');
    } else {
      showStatus('⚠️ Backend responded but with error: ' + response.status, 'warning');
    }
  } catch (error) {
    showStatus('❌ Connection failed: ' + error.message, 'error');
  }
}
