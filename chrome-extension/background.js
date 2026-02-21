// Amazon Buybox Tracker - Background Service Worker
// Handles communication between content script, popup, and backend API

console.log('🔧 Amazon Buybox Tracker Background Service Started');

// Listen for messages from popup and content scripts
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  console.log('📨 Background received message:', request.action);
  
  if (request.action === 'sendToBackend') {
    sendToBackendAPI(request.data)
      .then(response => sendResponse({ success: true, response: response }))
      .catch(error => sendResponse({ success: false, error: error.message }));
    return true; // Keep channel open for async
  }
  
  if (request.action === 'getSettings') {
    chrome.storage.sync.get(['backendUrl', 'mySellerName'], (items) => {
      sendResponse({ 
        backendUrl: items.backendUrl || '', 
        mySellerName: items.mySellerName || '' 
      });
    });
    return true;
  }
  
  if (request.action === 'saveSettings') {
    chrome.storage.sync.set({
      backendUrl: request.backendUrl,
      mySellerName: request.mySellerName
    }, () => {
      sendResponse({ success: true });
    });
    return true;
  }
});

// Send scraped data to backend API
async function sendToBackendAPI(productData) {
  try {
    const settings = await chrome.storage.sync.get(['backendUrl']);
    const backendUrl = settings.backendUrl;
    
    if (!backendUrl) {
      throw new Error('Backend URL not configured. Please set it in extension settings.');
    }
    
    const url = `${backendUrl}/api/extension/scrape`;
    
    console.log('📤 Sending to backend:', url);
    
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(productData)
    });
    
    if (!response.ok) {
      throw new Error(`Backend returned ${response.status}: ${response.statusText}`);
    }
    
    const result = await response.json();
    console.log('✅ Backend response:', result);
    return result;
    
  } catch (error) {
    console.error('❌ Error sending to backend:', error);
    throw error;
  }
}

// Handle extension icon click
chrome.action.onClicked.addListener((tab) => {
  console.log('🖱️ Extension icon clicked on tab:', tab.url);
});

// Initialize extension on install
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === 'install') {
    console.log('🎉 Extension installed for the first time!');
    
    // Set default settings
    chrome.storage.sync.set({
      backendUrl: '',
      mySellerName: ''
    });
    
    // Open welcome page or instructions
    chrome.tabs.create({
      url: 'popup.html'
    });
  } else if (details.reason === 'update') {
    console.log('🔄 Extension updated to version:', chrome.runtime.getManifest().version);
  }
});
