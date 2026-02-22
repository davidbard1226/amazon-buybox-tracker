// Amazon Buybox Tracker - Content Script v1.1.0
// Runs in your real browser - 0% bot detection!

console.log('🚀 Amazon Buybox Tracker Extension Loaded v1.1.0');

// ── Auto-scrape when opened via dashboard refresh (auto_scrape=1) ──
(function checkAutoScrape() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('auto_scrape') !== '1') return;

  // Prevent double-scrape if page reloads (e.g. Amazon redirect)
  if (sessionStorage.getItem('_buybox_scraped')) return;

  const runAutoScrape = () => {
    chrome.storage.sync.get(['mySellerName', 'backendUrl'], async (items) => {
      const mySellerName = items.mySellerName || '';
      const backendUrl = (items.backendUrl || '').replace(/\/+$/, '');
      if (!backendUrl) {
        chrome.runtime.sendMessage({ action: 'closeTab' });
        return;
      }

      // Mark as scraped to prevent re-scrape on reload
      sessionStorage.setItem('_buybox_scraped', '1');

      try {
        // First attempt — page should be mostly rendered
        let data = scrapeProductPage(mySellerName);
        console.log('🔍 Auto-scrape attempt 1:', data.seller, data.price);

        // If seller unknown, wait extra 2s for JS rendering then retry
        if (!data.seller || data.seller === 'Unknown') {
          await new Promise(r => setTimeout(r, 2000));
          data = scrapeProductPage(mySellerName);
          console.log('🔍 Auto-scrape attempt 2 (after extra wait):', data.seller, data.price);
        }

        // If still unknown, try clicking AOD panel and wait for it to render
        if (!data.seller || data.seller === 'Unknown') {
          const clicked = await openAODPanel();
          if (clicked) {
            await new Promise(r => setTimeout(r, 4000)); // wait for AOD panel to fully render
            data = scrapeProductPage(mySellerName);
            console.log('🔍 Auto-scrape attempt 3 (after AOD panel):', data.seller, data.price);
          }
        }

        // Push to backend — wait for response before closing tab
        const resp = await fetch(backendUrl + '/api/extension/scrape', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });

        if (!resp.ok) {
          const errText = await resp.text().catch(() => resp.statusText);
          console.error('❌ Backend POST failed:', resp.status, errText);
        } else {
          console.log('✅ Auto-scrape complete for', data.asin, '— seller:', data.seller, 'price:', data.price);
        }
      } catch (e) {
        console.error('❌ Auto-scrape error:', e);
      } finally {
        // Wait 1s after POST completes to ensure backend has processed it before tab closes
        setTimeout(() => chrome.runtime.sendMessage({ action: 'closeTab' }), 1000);
      }
    });
  };

  // Wait for full page load + extra time for JS-rendered content (buybox renders late)
  if (document.readyState === 'complete') {
    setTimeout(runAutoScrape, 3000);
  } else {
    window.addEventListener('load', () => setTimeout(runAutoScrape, 3000));
  }
})();

// Listen for messages from popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'scrapeProduct') {
    console.log('📊 Starting product scrape...');
    chrome.storage.sync.get(['mySellerName'], async (items) => {
      const mySellerName = items.mySellerName || '';
      // First try scraping without AOD panel
      let data = scrapeProductPage(mySellerName);

      // If seller unknown, try clicking "See All Buying Options" to open AOD panel
      if (data.seller === 'Unknown') {
        console.log('🔍 Seller unknown - trying to open AOD panel...');
        const opened = await openAODPanel();
        if (opened) {
          // Wait for panel to render then re-scrape
          await sleep(1500);
          data = scrapeProductPage(mySellerName);
          console.log('📊 After AOD panel:', data.seller);
        }
      }

      sendResponse({ success: true, data: data });
    });
    return true;
  }
  return true;
});

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// Click "See All Buying Options" button to open the AOD panel
async function openAODPanel() {
  // All known selectors for the "See All Buying Options" / "New offers" button
  const btnSelectors = [
    '#aod-ingress-link',
    'a[data-csa-c-slot-id="aod-ingress-link"]',
    '#buybox a[href*="offer-listing"]',
    '#buybox-see-all-buying-choices',
    'a[href*="offer-listing"]',
    '#moreBuyingChoices_feature_div a',
    '#olp_feature_div a',
    '.a-declarative[data-action="a-modal"] a',
    '#aod-ingress',
    '[data-action="show-all-offers-display"] a',
    'a[href*="aod=1"]',
  ];

  for (const sel of btnSelectors) {
    const btn = document.querySelector(sel);
    if (btn) {
      console.log('✅ Found AOD trigger:', sel);
      btn.click();
      return true;
    }
  }

  // Try finding by text content
  const allLinks = document.querySelectorAll('a, button, span[role="button"]');
  for (const el of allLinks) {
    const t = el.textContent.trim();
    if (/see all buying options|new offers|all offers|buying options/i.test(t)) {
      console.log('✅ Found AOD trigger by text:', t);
      el.click();
      return true;
    }
  }

  console.log('⚠️ No AOD trigger button found');
  return false;
}

// Main scraping function
function scrapeProductPage(mySellerName) {
  const seller = extractSeller();
  const price = extractPrice();
  const isAmazon = isAmazonSeller(seller);
  const buyboxStatus = determineBuyboxStatus(seller, mySellerName);

  // Only trigger offer-listing background fetch if seller AND price both unknown
  // (AOD click already attempted before this point if seller was unknown)
  const noBuybox = seller === 'Unknown' && !price;

  const result = {
    asin: extractASIN(),
    title: extractTitle(),
    price: price,
    seller: seller,
    currency: extractCurrency(),
    rating: extractRating(),
    review_count: extractReviewCount(),
    availability: extractAvailability(),
    image_url: extractImageUrl(),
    marketplace: window.location.hostname.replace('www.', ''),
    scraped_at: new Date().toISOString(),
    is_amazon: isAmazon,
    buybox_status: buyboxStatus,
    needs_offer_listing: noBuybox  // signal to background.js to fetch offer-listing
  };

  console.log('✅ Scrape complete:', result);
  return result;
}

// Extract ASIN from URL or page
function extractASIN() {
  const urlMatch = window.location.pathname.match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})/);
  if (urlMatch) return urlMatch[1];

  const canonical = document.querySelector('link[rel="canonical"]');
  if (canonical) {
    const m = canonical.href.match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})/);
    if (m) return m[1];
  }

  const asinInput = document.querySelector('input[name="ASIN"]');
  if (asinInput) return asinInput.value;

  return null;
}

// Extract product title
function extractTitle() {
  const selectors = ['#productTitle', '#title', 'h1.product-title', 'h1 span#productTitle'];
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el) return el.textContent.trim();
  }
  return null;
}

// Extract buybox price - handles ZAR (R1 660,00), USD ($12.99), GBP (£53.48)
function extractPrice() {
  const selectors = [
    '#corePriceDisplay_desktop_feature_div .a-offscreen',
    '#corePrice_feature_div .a-offscreen',
    '.a-price.aok-align-center .a-offscreen',
    '#priceblock_ourprice',
    '#priceblock_dealprice',
    '#price_inside_buybox',
    '.priceToPay .a-offscreen',
    '.a-price .a-offscreen',
    'span.a-price-whole'
  ];

  for (const selector of selectors) {
    const el = document.querySelector(selector);
    if (el) {
      let priceText = el.textContent.trim();
      if (!priceText) continue;
      priceText = priceText.replace(/[R£$€¥]/g, '').replace(/\u00a0|\u202f/g, '').trim();
      // ZAR: "1 660,00" (space thousands, comma decimal)
      if (priceText.includes(',') && !priceText.includes('.')) {
        priceText = priceText.replace(/\s/g, '').replace(',', '.');
      } else {
        priceText = priceText.replace(/,/g, '').replace(/\s/g, '');
      }
      const val = parseFloat(priceText);
      if (!isNaN(val) && val > 0) return val;
    }
  }
  return null;
}

// Extract seller name - covers all Amazon layouts including new ZA layout
function extractSeller() {

  // 0. AOD (All Offers Display) panel - exact selector from page inspection
  // #aod-offer-soldBy > div > div > div.a-fixed-left-grid-col.a-col-right > a
  const aodSeller = document.querySelector('#aod-offer-soldBy a, #aod-offer-soldBy .a-col-right a');
  if (aodSeller) {
    const aria = (aodSeller.getAttribute('aria-label') || '').replace(/\.\s*Opens a new page.*$/i, '').trim();
    const t = aria || aodSeller.textContent.trim();
    if (t && t.length > 1 && t.length < 100) return /amazon/i.test(t) ? 'Amazon.co.za' : t;
  }

  // 0b. AOD pinned offer seller (when AOD panel is open)
  const aodPinned = document.querySelector('#aod-pinned-offer-soldBy a, #aod-offer-list .a-col-right a');
  if (aodPinned) {
    const t = aodPinned.textContent.trim();
    if (t && t.length > 1 && t.length < 100) return /amazon/i.test(t) ? 'Amazon.co.za' : t;
  }

  // 1. Most reliable: sellerProfileTriggerId link (3rd party seller link)
  const sellerLink = document.querySelector('a#sellerProfileTriggerId');
  if (sellerLink) {
    const t = sellerLink.textContent.trim();
    if (t) return t;
  }

  // 2. NEW ZA LAYOUT: "Sold by" label + seller in adjacent spans
  // Amazon renders "Sold byBonolo Online" as two adjacent spans inside a div.
  // We scan ALL spans/divs for one that contains exactly "Sold by" and grab the next sibling text.
  const allSpans = document.querySelectorAll('span, div');
  for (const el of allSpans) {
    // Must be a leaf-ish node whose own text is exactly "Sold by"
    const ownText = el.childNodes.length === 1 && el.childNodes[0].nodeType === 3
      ? el.childNodes[0].textContent.trim()
      : el.textContent.trim();
    if (ownText === 'Sold by') {
      // Check next sibling element
      let next = el.nextElementSibling;
      if (next) {
        const t = next.textContent.trim();
        if (t && t.length > 1 && t.length < 100) {
          return /amazon/i.test(t) ? 'Amazon.co.za' : t;
        }
      }
      // Check parent's full text minus "Sold by" label
      const parent = el.parentElement;
      if (parent) {
        const parentText = parent.textContent.trim();
        const after = parentText.replace(/^Sold by\s*/i, '').trim();
        if (after && after.length > 1 && after.length < 100) {
          return /amazon/i.test(after) ? 'Amazon.co.za' : after;
        }
      }
    }
  }

  // 3. Seller anchor — ONLY /gp/aag/main links (seller profile page, not delivery links)
  // Exact pattern: aria-label="SellerName. Opens a new page" href="/gp/aag/main?..."
  const aagAnchors = document.querySelectorAll('a[href*="/gp/aag/main"]');
  for (const a of aagAnchors) {
    // aria-label is the most reliable: "Bonolo Online. Opens a new page"
    const aria = (a.getAttribute('aria-label') || '').replace(/\.\s*Opens a new page.*$/i, '').trim();
    if (aria && aria.length > 1 && aria.length < 100 && !/see all|compare|offer|detail|delivery/i.test(aria)) {
      return /amazon/i.test(aria) ? 'Amazon.co.za' : aria;
    }
    // Fallback: link text — but only if it looks like a seller name (not a sentence)
    const txt = a.textContent.trim();
    if (txt && txt.length > 1 && txt.length < 60 && !/see all|compare|offer|detail|delivery|about|costs|method/i.test(txt)) {
      return /amazon/i.test(txt) ? 'Amazon.co.za' : txt;
    }
  }

  // 3b. /sp? seller profile links (used on some Amazon layouts)
  const sellerAnchors = document.querySelectorAll('a[href*="/sp?"]');
  for (const a of sellerAnchors) {
    const aria = (a.getAttribute('aria-label') || '').replace(/\.\s*Opens a new page.*$/i, '').trim();
    const t = aria || a.textContent.trim();
    if (t && t.length > 1 && t.length < 60 && !/see all|compare|detail|delivery/i.test(t)) {
      return /amazon/i.test(t) ? 'Amazon.co.za' : t;
    }
  }

  // 4. merchant-info div
  const merchantInfo = document.querySelector('#merchant-info');
  if (merchantInfo) {
    const a = merchantInfo.querySelector('a');
    if (a && a.textContent.trim()) return a.textContent.trim();
    const txt = merchantInfo.textContent.trim();
    if (/amazon/i.test(txt)) return 'Amazon.co.za';
  }

  // 5. Tabular buybox "Sold by" row
  const tabularBuybox = document.querySelector('#tabular-buybox');
  if (tabularBuybox) {
    const rows = tabularBuybox.querySelectorAll('.tabular-buybox-text');
    for (const row of rows) {
      const label = row.querySelector('.a-color-secondary');
      const val = row.querySelector('.a-color-base');
      if (label && val && /sold by/i.test(label.textContent)) {
        return val.textContent.trim();
      }
    }
  }

  // 6. offer-display-feature-text-message spans
  const offerSpans = document.querySelectorAll('.offer-display-feature-text-message');
  for (const span of offerSpans) {
    const t = span.textContent.trim();
    if (t) return /amazon/i.test(t) ? 'Amazon.co.za' : t;
  }

  // 7. Full page innerText scan — "Sold by X" with optional colon/space
  // Also handles "Sold byX" (no space) by using \s* instead of \s+
  const bodyText = document.body.innerText;
  const soldByMatch = bodyText.match(/Sold by\s*([^\n\r]{2,80}?)(?:\n|Seller rating|Ships|Delivered|$)/i);
  if (soldByMatch) {
    const name = soldByMatch[1].trim().replace(/\s*\(.*$/, ''); // strip trailing "(16 ratings)"
    if (name && name.length > 1 && name.length < 100) {
      return /amazon/i.test(name) ? 'Amazon.co.za' : name;
    }
  }

  // 8. Shipped and sold by Amazon
  if (/sent from and sold by amazon|ships from and sold by amazon/i.test(bodyText)) {
    return 'Amazon.co.za';
  }

  return 'Unknown';
}

// Extract currency
function extractCurrency() {
  const priceEl = document.querySelector('.a-price-symbol');
  if (priceEl) {
    const symbol = priceEl.textContent.trim();
    const currencyMap = { 'R': 'ZAR', '$': 'USD', '£': 'GBP', '€': 'EUR', '¥': 'JPY', 'C$': 'CAD', 'A$': 'AUD' };
    return currencyMap[symbol] || symbol;
  }
  const domainMap = {
    'amazon.co.za': 'ZAR', 'amazon.com': 'USD', 'amazon.co.uk': 'GBP',
    'amazon.de': 'EUR', 'amazon.fr': 'EUR', 'amazon.it': 'EUR',
    'amazon.es': 'EUR', 'amazon.co.jp': 'JPY', 'amazon.ca': 'CAD', 'amazon.com.au': 'AUD'
  };
  return domainMap[window.location.hostname.replace('www.', '')] || 'USD';
}

// Extract rating
function extractRating() {
  const ratingEl = document.querySelector('span[data-hook="rating-out-of-text"], #acrPopover');
  if (ratingEl) {
    const ratingText = ratingEl.getAttribute('title') || ratingEl.textContent;
    const match = ratingText.match(/(\d+\.?\d*)/);
    if (match) return parseFloat(match[1]);
  }
  return null;
}

// Extract review count
function extractReviewCount() {
  const reviewEl = document.querySelector('#acrCustomerReviewText, [data-hook="total-review-count"]');
  if (reviewEl) {
    const cleaned = reviewEl.textContent.trim().replace(/[(),]/g, '').trim();
    const match = cleaned.match(/(\d+)/);
    if (match) return parseInt(match[1]);
  }
  return null;
}

// Extract availability
function extractAvailability() {
  const availEl = document.querySelector('#availability span, #availability .a-declarative');
  if (availEl) {
    const text = availEl.textContent.trim().toLowerCase();
    if (text.includes('in stock')) return 'In stock';
    if (text.includes('out of stock')) return 'Out of stock';
    if (text.includes('temporarily')) return 'Temporarily unavailable';
    return text;
  }
  return 'Unknown';
}

// Extract product image
function extractImageUrl() {
  const imgEl = document.querySelector('#landingImage, #imgBlkFront, .a-dynamic-image');
  if (imgEl) {
    return imgEl.src || imgEl.getAttribute('data-old-hires') || null;
  }
  return null;
}

// Check if seller is Amazon
function isAmazonSeller(seller) {
  if (!seller) return false;
  return /amazon/i.test(seller);
}

// Determine buybox status
function determineBuyboxStatus(seller, mySellerName) {
  if (!seller || seller === 'Unknown') return 'unknown';
  if (isAmazonSeller(seller)) return 'amazon';
  if (mySellerName && seller.toLowerCase().includes(mySellerName.toLowerCase())) return 'winning';
  return 'losing';
}

// Visual indicator when extension is active
function showExtensionIndicator() {
  const indicator = document.createElement('div');
  indicator.id = 'buybox-tracker-indicator';
  indicator.innerHTML = '🎯 Buybox Tracker Active';
  indicator.style.cssText = `
    position: fixed; bottom: 20px; right: 20px;
    background: #FF9900; color: white;
    padding: 10px 15px; border-radius: 5px;
    font-family: Arial, sans-serif; font-size: 12px; font-weight: bold;
    z-index: 999999; box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    opacity: 0; transition: opacity 0.3s;
  `;
  document.body.appendChild(indicator);
  setTimeout(() => indicator.style.opacity = '1', 100);
  setTimeout(() => {
    indicator.style.opacity = '0';
    setTimeout(() => indicator.remove(), 300);
  }, 3000);
}

if (window.location.pathname.match(/\/(?:dp|gp\/product)\//)) {
  showExtensionIndicator();
}
