// Amazon Buybox Tracker - Background Service Worker v1.2.0
// Handles API calls, offer-listing fallback, and bulk ASIN processing

console.log('🔧 Amazon Buybox Tracker Background Service Started v1.2.0');

// ─── Message Router (internal + external from dashboard) ─────────────────────
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  console.log('📨 Background received:', request.action);
  handleMessage(request, sender, sendResponse);
  return true;
});

chrome.runtime.onMessageExternal.addListener((request, sender, sendResponse) => {
  console.log('📨 External message from dashboard:', request.action);
  handleMessage(request, sender, sendResponse);
  return true;
});

function handleMessage(request, sender, sendResponse) {

  // Close the tab that sent this message (window.close() is blocked cross-origin)
  if (request.action === 'closeTab') {
    if (sender.tab && sender.tab.id) {
      chrome.tabs.remove(sender.tab.id, () => {
        console.log('✅ Closed auto-scrape tab:', sender.tab.id);
      });
    }
    sendResponse({ success: true });
    return true;
  }

  if (request.action === 'sendToBackend') {
    handleSendToBackend(request.data)
      .then(response => sendResponse({ success: true, response }))
      .catch(error => sendResponse({ success: false, error: error.message }));
    return true;
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
    }, () => sendResponse({ success: true }));
    return true;
  }

  if (request.action === 'bulkScrapeASINs') {
    handleBulkASINs(request.asins, request.marketplace)
      .then(result => sendResponse({ success: true, result }))
      .catch(error => sendResponse({ success: false, error: error.message }));
    return true;
  }

  // Dashboard asks extension to auto-upload a price file to Seller Central
  if (request.action === 'autoUploadPriceFile') {
    handleAutoUpload(request.content, request.fileName, request.skuCount)
      .then(result => sendResponse({ success: true, result }))
      .catch(error => sendResponse({ success: false, error: error.message }));
    return true;
  }

  // Dashboard asks extension to scrape a specific ASIN URL
  if (request.action === 'scrapeAsinUrl') {
    scrapeAsinInTab(request.asin, request.marketplace)
      .then(result => sendResponse({ success: true, result }))
      .catch(error => sendResponse({ success: false, error: error.message }));
    return true;
  }
}

// ─── Get cleaned backend URL ─────────────────────────────────────────────────
async function getBackendUrl() {
  const settings = await chrome.storage.sync.get(['backendUrl']);
  const url = (settings.backendUrl || '').trim().replace(/\/+$/, ''); // strip trailing slash
  if (!url) throw new Error('Backend URL not configured. Go to Settings tab and enter your Render.com URL.');
  return url;
}

// ─── Main: Send scraped data to backend (with offer-listing fallback) ─────────
async function handleSendToBackend(productData) {
  const backendUrl = await getBackendUrl();

  // If content.js flagged that no buybox was found on the main page,
  // fetch the offer-listing page from background (bypasses CORS)
  if (productData.needs_offer_listing && productData.asin) {
    console.log('🔍 No buybox on main page, fetching offer-listing for:', productData.asin);
    const offerData = await fetchOfferListing(productData.asin, productData.marketplace || 'amazon.co.za');
    if (offerData) {
      if (!productData.price && offerData.price) productData.price = offerData.price;
      if ((!productData.seller || productData.seller === 'Unknown') && offerData.seller) {
        productData.seller = offerData.seller;
      }
      if (!productData.currency && offerData.currency) productData.currency = offerData.currency;
      // Recompute buybox_status with updated seller
      const settings = await chrome.storage.sync.get(['mySellerName']);
      productData.buybox_status = computeStatus(productData.seller, settings.mySellerName || '');
      productData.is_amazon = /amazon/i.test(productData.seller || '');
      console.log('✅ Offer-listing data merged:', offerData);
    }
    // Clear the flag so popup shows resolved state
    productData.needs_offer_listing = false;
  }

  // Remove internal flag before sending
  delete productData.needs_offer_listing;

  return await sendToBackendAPI(productData, backendUrl);
}

// ─── Fetch offer-listing page (background has full network access) ────────────
async function fetchOfferListing(asin, marketplace) {
  // Try both offer-listing URL formats
  const urls = [
    `https://www.${marketplace}/gp/offer-listing/${asin}?condition=New`,
    `https://www.${marketplace}/gp/offer-listing/${asin}`,
  ];

  for (const url of urls) {
    console.log('📄 Fetching offer-listing:', url);
    try {
      const response = await fetch(url, {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
          'Accept-Language': 'en-GB,en-US;q=0.9,en;q=0.8',
          'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
          'Cache-Control': 'no-cache',
        }
      });

      if (!response.ok) {
        console.warn('⚠️ Offer-listing page returned:', response.status);
        continue;
      }

      const html = await response.text();
      const result = parseOfferListingHtml(html, marketplace);
      if (result && (result.price || result.seller)) {
        console.log('✅ Offer-listing parsed:', result);
        return result;
      }
    } catch (err) {
      console.error('❌ Offer-listing fetch error:', err);
    }
  }
  return null;
}

// ─── Parse offer-listing HTML using REGEX only (DOMParser not available in service workers) ──
function parseOfferListingHtml(html, marketplace) {
  let price = null;
  let seller = null;

  // === PRICE EXTRACTION (regex on raw HTML) ===

  // Method 1: a-offscreen spans contain the full price text e.g. "R1 660,00" or "$12.99"
  // <span class="a-offscreen">R1 660,00</span>
  const offscreenMatches = html.matchAll(/class="a-offscreen">([^<]{1,30})<\/span>/g);
  for (const m of offscreenMatches) {
    const val = parseOfferPrice(m[1].trim());
    if (val && val > 0) { price = val; break; }
  }

  // Method 2: a-price-whole + a-price-fraction
  // <span class="a-price-whole">1<span...>  <span class="a-price-fraction">66</span>
  if (!price) {
    const wholeMatch = html.match(/class="a-price-whole">\s*([\d\s,]+)/);
    const fracMatch  = html.match(/class="a-price-fraction">\s*(\d+)/);
    if (wholeMatch) {
      const w = wholeMatch[1].replace(/[^\d]/g, '');
      const f = fracMatch ? fracMatch[1].replace(/[^\d]/g, '') : '00';
      const val = parseFloat(`${w}.${f || '00'}`);
      if (!isNaN(val) && val > 0) price = val;
    }
  }

  // Method 3: Any currency symbol followed by number in tag content
  if (!price) {
    const currencyRe = />([R£$€]\s?[\d\s]{1,7}[,.][\d]{2})</g;
    const matches = html.matchAll(currencyRe);
    for (const m of matches) {
      const val = parseOfferPrice(m[1].trim());
      if (val && val > 0) { price = val; break; }
    }
  }

  // === SELLER EXTRACTION (regex on raw HTML) ===

  // Method 1: olpSellerName class - classic offer-listing layout
  // <h3 class="a-spacing-none olpSellerName"><span ...>SellerName</span></h3>
  // or with a link: <a ...>SellerName</a>
  const olpMatch = html.match(/class="[^"]*olpSellerName[^"]*"[^>]*>([\s\S]{0,300}?)<\/(?:h3|div|span)>/i);
  if (olpMatch) {
    // Strip inner tags to get text
    const innerText = olpMatch[1].replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
    if (innerText && innerText.length > 1 && innerText.length < 100) {
      seller = /amazon/i.test(innerText) ? 'Amazon.co.za' : innerText;
    }
  }

  // Method 2: data-seller-name attribute
  if (!seller) {
    const dsMatch = html.match(/data-seller-name="([^"]{2,80})"/i);
    if (dsMatch) seller = dsMatch[1].trim();
  }

  // Method 3a: aria-label on seller anchor (offer-listing page exact pattern)
  // <a aria-label="Bonolo Online. Opens a new page" href="/gp/aag/main?...seller=...">Bonolo Online</a>
  if (!seller) {
    const ariaLabelRe = /aria-label="([^"]{2,80}?)\.\s*Opens a new page"[^>]*href="[^"]*(?:seller=|\/gp\/aag\/)[^"]*"/gi;
    const alMatches = html.matchAll(ariaLabelRe);
    for (const m of alMatches) {
      const t = m[1].trim();
      if (t && t.length > 1 && !/see all|compare|offers/i.test(t)) {
        seller = /amazon/i.test(t) ? 'Amazon.co.za' : t;
        break;
      }
    }
  }

  // Method 3b: /gp/aag/main link text (offer-listing seller name link)
  // <a href="/gp/aag/main?...seller=XXXX...">Bonolo Online </a>
  if (!seller) {
    const aagRe = /href="[^"]*\/gp\/aag\/main[^"]*"[^>]*>\s*([^<]{2,80}?)\s*<\/a>/gi;
    const aagMatches = html.matchAll(aagRe);
    for (const m of aagMatches) {
      const t = m[1].trim();
      if (t && t.length > 1 && !/see all|compare|offers|amazon/i.test(t)) {
        seller = t;
        break;
      }
    }
  }

  // Method 3c: seller profile link text - generic seller= or /sp? patterns
  // <a href="...seller=XXXX...">SellerName</a>
  if (!seller) {
    const sellerLinkRe = /href="[^"]*(?:seller=|\/sp\?)[^"]*"[^>]*>\s*([^<]{2,80}?)\s*<\/a>/gi;
    const slMatches = html.matchAll(sellerLinkRe);
    for (const m of slMatches) {
      const t = m[1].trim();
      if (t && t.length > 1 && !/see all|compare|offers/i.test(t)) {
        seller = /amazon/i.test(t) ? 'Amazon.co.za' : t;
        break;
      }
    }
  }

  // Method 4: "Sold by X" text pattern (common in new layouts)
  if (!seller) {
    // Match: "Sold by SomeSeller" not followed immediately by more HTML tags
    const soldByRe = /Sold by[:\s]+<[^>]*>([^<]{2,80})<\/[a-z]+>/gi;
    const sbMatch = soldByRe.exec(html);
    if (sbMatch) {
      const name = sbMatch[1].trim();
      if (name && name.length > 1) seller = /amazon/i.test(name) ? 'Amazon.co.za' : name;
    }
  }

  // Method 5: "Sold by X" in plain text (no surrounding tag)
  if (!seller) {
    const plainSoldBy = html.match(/Sold by[:\s]+([A-Za-z0-9 &'.,-]{2,60})(?:<|\n|\.com|$)/i);
    if (plainSoldBy) {
      const name = plainSoldBy[1].trim().replace(/\.$/, '');
      if (name && name.length > 1) seller = /amazon/i.test(name) ? 'Amazon.co.za' : name;
    }
  }

  // Method 6: fulfillment / Amazon sold-by patterns
  if (!seller) {
    if (/sold by amazon\.co\.za|fulfilled by amazon|ships from and sold by amazon/i.test(html)) {
      seller = 'Amazon.co.za';
    }
  }

  // Method 7: aria-label on offer container
  if (!seller) {
    const ariaMatch = html.match(/aria-label="Sold by ([^"]{2,80})"/i);
    if (ariaMatch) seller = /amazon/i.test(ariaMatch[1]) ? 'Amazon.co.za' : ariaMatch[1].trim();
  }

  // Detect currency from marketplace
  const currency = marketplace.includes('amazon.co.za') ? 'ZAR'
    : marketplace.includes('amazon.co.uk') ? 'GBP'
    : marketplace.includes('amazon.de') || marketplace.includes('amazon.fr') ? 'EUR'
    : 'USD';

  console.log(`🔍 Offer-listing parse result — Price: ${price}, Seller: ${seller}`);
  return { price, seller, currency };
}

// ─── Parse price string from offer-listing ────────────────────────────────────
function parseOfferPrice(raw) {
  if (!raw) return null;
  // Remove currency symbols and non-breaking spaces
  let s = raw.replace(/[R£$€¥\u00a0\u202f]/g, '').trim();
  // ZAR: "1 660,00" (space thousands, comma decimal)
  if (s.includes(',') && !s.includes('.')) {
    s = s.replace(/\s/g, '').replace(',', '.');
  } else {
    s = s.replace(/[,\s]/g, '');
  }
  const val = parseFloat(s);
  return (!isNaN(val) && val > 0) ? val : null;
}

// ─── Compute buybox status ────────────────────────────────────────────────────
function computeStatus(seller, mySellerName) {
  if (!seller || seller === 'Unknown') return 'unknown';
  if (/amazon/i.test(seller)) return 'amazon';
  if (mySellerName && seller.toLowerCase().includes(mySellerName.toLowerCase())) return 'winning';
  return 'losing';
}

// ─── Send data to backend API ─────────────────────────────────────────────────
async function sendToBackendAPI(productData, backendUrl) {
  const url = `${backendUrl}/api/extension/scrape`;
  console.log('📤 Sending to backend:', url, productData);

  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(productData)
  });

  if (!response.ok) {
    const text = await response.text().catch(() => response.statusText);
    throw new Error(`Backend returned ${response.status}: ${text}`);
  }

  const result = await response.json();
  console.log('✅ Backend response:', result);
  return result;
}

// ─── Scrape a specific ASIN by opening it in a background tab ────────────────
// Used when the dashboard asks to refresh an ASIN via the extension
async function scrapeAsinInTab(asin, marketplace) {
  marketplace = (marketplace || 'amazon.co.za').replace('www.', '');
  const url = `https://www.${marketplace}/dp/${asin}`;
  const settings = await chrome.storage.sync.get(['mySellerName', 'backendUrl']);

  return new Promise((resolve, reject) => {
    // Create a background tab
    chrome.tabs.create({ url, active: false }, async (tab) => {
      const tabId = tab.id;

      // Wait for the tab to finish loading
      const onUpdated = (updatedTabId, info) => {
        if (updatedTabId !== tabId || info.status !== 'complete') return;
        chrome.tabs.onUpdated.removeListener(onUpdated);

        // Small delay to let JS render
        setTimeout(async () => {
          try {
            // Inject content script and scrape
            const results = await chrome.scripting.executeScript({
              target: { tabId },
              func: (mySellerName) => {
                // Inline version of scrapeProductPage from content.js
                function extractASIN() {
                  const m = window.location.pathname.match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})/);
                  return m ? m[1] : null;
                }
                function extractTitle() {
                  const el = document.querySelector('#productTitle, #title');
                  return el ? el.textContent.trim() : null;
                }
                function extractSeller() {
                  const link = document.querySelector('a#sellerProfileTriggerId');
                  if (link && link.textContent.trim()) return link.textContent.trim();
                  const merchant = document.querySelector('#merchant-info');
                  if (merchant) {
                    const a = merchant.querySelector('a');
                    if (a) return a.textContent.trim();
                    if (/amazon/i.test(merchant.textContent)) return 'Amazon.co.za';
                  }
                  const tabular = document.querySelector('#tabular-buybox');
                  if (tabular) {
                    for (const row of tabular.querySelectorAll('.tabular-buybox-text')) {
                      const label = row.querySelector('.a-color-secondary');
                      const val = row.querySelector('.a-color-base');
                      if (label && val && /sold by/i.test(label.textContent)) return val.textContent.trim();
                    }
                  }
                  for (const span of document.querySelectorAll('.offer-display-feature-text-message')) {
                    const t = span.textContent.trim();
                    if (t) return /amazon/i.test(t) ? 'Amazon.co.za' : t;
                  }
                  const bodyText = document.body.innerText;
                  const m = bodyText.match(/Sold by[:\s]+([^\n\r\.]{2,60}?)(?:\s*\.|Ships|\n|$)/i);
                  if (m) { const n = m[1].trim(); return /amazon/i.test(n) ? 'Amazon.co.za' : n; }
                  if (/sent from and sold by amazon|ships from and sold by amazon/i.test(bodyText)) return 'Amazon.co.za';
                  return 'Unknown';
                }
                function extractPrice() {
                  const selectors = [
                    '#corePriceDisplay_desktop_feature_div .a-offscreen',
                    '#corePrice_feature_div .a-offscreen',
                    '.a-price.aok-align-center .a-offscreen',
                    '#priceblock_ourprice',
                    '#price_inside_buybox',
                    '.priceToPay .a-offscreen',
                    '.a-price .a-offscreen',
                  ];
                  for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (!el) continue;
                    let t = el.textContent.trim().replace(/[R£$€¥\u00a0\u202f]/g, '').trim();
                    if (t.includes(',') && !t.includes('.')) t = t.replace(/\s/g,'').replace(',','.');
                    else t = t.replace(/[,\s]/g,'');
                    const v = parseFloat(t);
                    if (!isNaN(v) && v > 0) return v;
                  }
                  return null;
                }
                function extractCurrency() {
                  const sym = document.querySelector('.a-price-symbol');
                  if (sym) {
                    const map = {'R':'ZAR','$':'USD','£':'GBP','€':'EUR'};
                    return map[sym.textContent.trim()] || sym.textContent.trim();
                  }
                  const host = window.location.hostname.replace('www.','');
                  return {'amazon.co.za':'ZAR','amazon.co.uk':'GBP','amazon.de':'EUR'}[host] || 'USD';
                }
                function extractRating() {
                  const el = document.querySelector('span[data-hook="rating-out-of-text"], #acrPopover');
                  if (el) { const m = (el.getAttribute('title')||el.textContent).match(/(\d+\.?\d*)/); return m ? parseFloat(m[1]) : null; }
                  return null;
                }
                function extractReviewCount() {
                  const el = document.querySelector('#acrCustomerReviewText, [data-hook="total-review-count"]');
                  if (el) { const m = el.textContent.trim().replace(/[(),]/g,'').match(/(\d+)/); return m ? parseInt(m[1]) : null; }
                  return null;
                }
                function extractAvailability() {
                  const el = document.querySelector('#availability span');
                  if (!el) return 'Unknown';
                  const t = el.textContent.trim().toLowerCase();
                  if (t.includes('in stock')) return 'In stock';
                  if (t.includes('out of stock')) return 'Out of stock';
                  return t;
                }
                function extractImageUrl() {
                  const img = document.querySelector('#landingImage, #imgBlkFront');
                  return img ? (img.src || null) : null;
                }

                const seller = extractSeller();
                const price  = extractPrice();
                const noBuybox = (!price && seller === 'Unknown') || seller === 'Unknown';
                return {
                  asin: extractASIN(),
                  title: extractTitle(),
                  price,
                  seller,
                  currency: extractCurrency(),
                  rating: extractRating(),
                  review_count: extractReviewCount(),
                  availability: extractAvailability(),
                  image_url: extractImageUrl(),
                  marketplace: window.location.hostname.replace('www.', ''),
                  scraped_at: new Date().toISOString(),
                  is_amazon: /amazon/i.test(seller),
                  buybox_status: /amazon/i.test(seller) ? 'amazon'
                    : (mySellerName && seller.toLowerCase().includes(mySellerName.toLowerCase())) ? 'winning'
                    : seller !== 'Unknown' ? 'losing' : 'unknown',
                  needs_offer_listing: noBuybox
                };
              },
              args: [settings.mySellerName || '']
            });

            chrome.tabs.remove(tabId);
            const data = results[0]?.result;
            if (!data) return reject(new Error('No data scraped from tab'));
            resolve(data);
          } catch (err) {
            chrome.tabs.remove(tabId).catch(() => {});
            reject(err);
          }
        }, 2000);
      };

      chrome.tabs.onUpdated.addListener(onUpdated);

      // Timeout safety
      setTimeout(() => {
        chrome.tabs.onUpdated.removeListener(onUpdated);
        chrome.tabs.remove(tabId).catch(() => {});
        reject(new Error('Tab scrape timed out after 30s'));
      }, 30000);
    });
  });
}

// ─── Auto-upload price file to Seller Central ────────────────────────────────
async function handleAutoUpload(content, fileName, skuCount) {
  await chrome.storage.local.set({
    pendingUploadContent: content,
    pendingUploadName: fileName || 'amazon_reprice.txt',
    pendingUploadTimestamp: Date.now()
  });

  return new Promise((resolve, reject) => {
    // Open tab ACTIVE so user can see it
    chrome.tabs.create({
      url: 'https://sellercentral.amazon.co.za/product-search/bulk',
      active: true
    }, (tab) => {
      const onUpdated = (tabId, info) => {
        if (tabId !== tab.id || info.status !== 'complete') return;
        chrome.tabs.onUpdated.removeListener(onUpdated);
        // Wait 4s for page to fully render
        setTimeout(async () => {
          try {
            await chrome.scripting.executeScript({
              target: { tabId: tab.id },
              func: sellerCentralAutoUpload
            });
            resolve({ tabId: tab.id });
          } catch (err) {
            reject(new Error('Script inject failed: ' + err.message));
          }
        }, 4000);
      };
      chrome.tabs.onUpdated.addListener(onUpdated);
      setTimeout(() => {
        chrome.tabs.onUpdated.removeListener(onUpdated);
        resolve({ message: 'Timeout — tab opened' });
      }, 30000);
    });
  });
}

// Injected into Seller Central upload page — handles the full upload flow
async function sellerCentralAutoUpload() {
  const stored = await chrome.storage.local.get(['pendingUploadContent', 'pendingUploadName']);
  if (!stored.pendingUploadContent) { console.warn('No pending upload found'); return; }

  const content  = stored.pendingUploadContent;
  const fileName = stored.pendingUploadName || 'amazon_reprice.txt';
  const wait     = ms => new Promise(r => setTimeout(r, ms));

  // Big visible banner at top of page
  const banner = document.createElement('div');
  banner.style.cssText = `
    position:fixed;top:0;left:0;right:0;
    background:#f97316;color:#fff;
    padding:18px 24px;font-size:16px;font-weight:bold;
    z-index:99999;text-align:center;
    box-shadow:0 4px 12px rgba(0,0,0,0.4);
    font-family:Arial,sans-serif;
  `;
  const setStatus = (msg, color) => {
    banner.style.background = color || '#f97316';
    banner.innerHTML = '🤖 Buybox Tracker Auto-Upload: ' + msg;
    console.log('🤖', msg);
  };

  document.body.prepend(banner);
  setStatus('Step 1 — Making sure Spreadsheet tab is selected...');

  // Step 1: Click Spreadsheet tab if not already selected
  await wait(500);
  const tabs = document.querySelectorAll('button, a, span, div');
  for (const el of tabs) {
    if (el.textContent.trim() === 'Spreadsheet' && el.offsetParent !== null) {
      el.click();
      break;
    }
  }
  await wait(1500);

  // Step 2: Find and attach the file
  setStatus('Step 2 — Attaching price file...');
  await wait(500);

  // Find the file input — it's hidden inside shadow DOM of kat-button#select-file
  let fileInput = null;
  // Check regular inputs first (skip image input)
  for (const inp of document.querySelectorAll('input[type="file"]')) {
    if (inp.id !== 'imageFileInput') { fileInput = inp; break; }
  }
  // If not found, look inside shadow roots
  if (!fileInput) {
    for (const el of document.querySelectorAll('*')) {
      if (el.shadowRoot) {
        const inp = el.shadowRoot.querySelector('input[type="file"]');
        if (inp && inp.id !== 'imageFileInput') { fileInput = inp; break; }
      }
    }
  }

  if (!fileInput) {
    setStatus('❌ Could not find file input. Please attach the file manually.', '#ef4444');
    return;
  }

  const blob = new Blob([content], { type: 'text/plain' });
  const file = new File([blob], fileName, { type: 'text/plain' });
  const dt   = new DataTransfer();
  dt.items.add(file);
  fileInput.files = dt.files;
  fileInput.dispatchEvent(new Event('change', { bubbles: true }));
  fileInput.dispatchEvent(new Event('input',  { bubbles: true }));

  setStatus(`Step 3 — File "${fileName}" attached. Waiting for Amazon to process...`);
  await wait(4000); // Give Amazon time to detect file and enable Submit button

  // Step 4: Click Submit products button — retry up to 5 times with 2s gaps
  setStatus('Step 4 — Clicking Submit products...');
  let submitted = false;
  for (let attempt = 0; attempt < 5; attempt++) {
    for (const btn of document.querySelectorAll('button')) {
      if (/submit products/i.test(btn.textContent) && !btn.disabled) {
        btn.click();
        submitted = true;
        break;
      }
    }
    if (submitted) break;
    setStatus(`Step 4 — Waiting for Submit button to become active... (${attempt + 1}/5)`);
    await wait(2000);
  }

  if (submitted) {
    setStatus('✅ Done! Price file submitted. Amazon updates prices in 15-30 minutes.', '#10b981');
    chrome.storage.local.remove(['pendingUploadContent', 'pendingUploadName', 'pendingUploadTimestamp']);
  } else {
    setStatus('⚠️ File attached — Submit button not ready yet. Click "Submit products" to finish.', '#d97706');
  }

  setTimeout(() => banner.remove(), 30000);
}

// ─── Bulk ASIN handler ────────────────────────────────────────────────────────
async function handleBulkASINs(asins, marketplace) {
  const backendUrl = await getBackendUrl();
  const url = `${backendUrl}/api/buybox/bulk-start`;
  console.log(`📦 Bulk submitting ${asins.length} ASINs to:`, url);

  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ asins, marketplace: marketplace || 'amazon.co.za' })
  });

  if (!response.ok) {
    const text = await response.text().catch(() => response.statusText);
    throw new Error(`Bulk start failed ${response.status}: ${text}`);
  }

  return await response.json();
}

// ─── Extension install / update ───────────────────────────────────────────────
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === 'install') {
    console.log('🎉 Extension installed!');
    chrome.storage.sync.set({ backendUrl: '', mySellerName: '' });
    chrome.tabs.create({ url: 'popup.html' });
  } else if (details.reason === 'update') {
    console.log('🔄 Extension updated to:', chrome.runtime.getManifest().version);
  }
});
