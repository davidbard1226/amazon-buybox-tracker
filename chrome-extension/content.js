// Amazon Buybox Tracker - Content Script
// This script runs directly on Amazon product pages and extracts buybox data from the DOM
// 0% bot detection because it's running in your real browser session!

console.log('🚀 Amazon Buybox Tracker Extension Loaded');

// Listen for messages from popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'scrapeProduct') {
    console.log('📊 Starting product scrape...');
    const data = scrapeProductPage();
    sendResponse({ success: true, data: data });
  }
  return true; // Keep channel open for async response
});

// Main scraping function - extracts all buybox data from the current page
function scrapeProductPage() {
  const result = {
    asin: extractASIN(),
    title: extractTitle(),
    price: extractPrice(),
    seller: extractSeller(),
    currency: extractCurrency(),
    rating: extractRating(),
    reviewCount: extractReviewCount(),
    availability: extractAvailability(),
    imageUrl: extractImageUrl(),
    marketplace: window.location.hostname,
    scrapedAt: new Date().toISOString()
  };

  // Determine buybox status
  result.isAmazon = isAmazonSeller(result.seller);
  result.buyboxStatus = determineBuyboxStatus(result.seller);

  console.log('✅ Scrape complete:', result);
  return result;
}

// Extract ASIN from URL or page
function extractASIN() {
  // Try URL first: /dp/B01ARH3Q5G or /gp/product/B01ARH3Q5G
  const urlMatch = window.location.pathname.match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})/);
  if (urlMatch) return urlMatch[1];

  // Try canonical link
  const canonical = document.querySelector('link[rel="canonical"]');
  if (canonical) {
    const canonicalMatch = canonical.href.match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})/);
    if (canonicalMatch) return canonicalMatch[1];
  }

  // Try hidden input
  const asinInput = document.querySelector('input[name="ASIN"]');
  if (asinInput) return asinInput.value;

  return null;
}

// Extract product title
function extractTitle() {
  const selectors = [
    '#productTitle',
    '#title',
    'h1.product-title',
    'h1 span#productTitle'
  ];

  for (const selector of selectors) {
    const el = document.querySelector(selector);
    if (el) return el.textContent.trim();
  }
  return null;
}

// Extract buybox price
function extractPrice() {
  const selectors = [
    '.a-price.aok-align-center .a-offscreen',
    '#priceblock_ourprice',
    '#priceblock_dealprice',
    '.a-price .a-offscreen',
    'span.a-price-whole',
    '#corePrice_feature_div .a-offscreen'
  ];

  for (const selector of selectors) {
    const el = document.querySelector(selector);
    if (el) {
      let priceText = el.textContent.trim();
      // Extract numeric value: "R1,660.00" -> 1660.00
      const numMatch = priceText.match(/[\d,]+\.?\d*/);
      if (numMatch) {
        return parseFloat(numMatch[0].replace(/,/g, ''));
      }
    }
  }
  return null;
}

// Extract seller name
function extractSeller() {
  const selectors = [
    '#sellerProfileTriggerId',
    'a#sellerProfileTriggerId',
    '#merchant-info',
    'div#merchant-info a',
    'a[href*="seller"]'
  ];

  for (const selector of selectors) {
    const el = document.querySelector(selector);
    if (el) {
      let sellerText = el.textContent.trim();
      // Clean up common patterns
      sellerText = sellerText.replace(/^Sold by:?\s*/i, '');
      sellerText = sellerText.replace(/^Ships from and sold by:?\s*/i, '');
      return sellerText;
    }
  }

  // Check for Amazon.co.za specifically
  const merchantInfo = document.querySelector('#merchant-info');
  if (merchantInfo && /amazon/i.test(merchantInfo.textContent)) {
    return 'Amazon.co.za';
  }

  return 'Unknown';
}

// Extract currency
function extractCurrency() {
  const priceEl = document.querySelector('.a-price-symbol');
  if (priceEl) {
    const symbol = priceEl.textContent.trim();
    const currencyMap = {
      'R': 'ZAR',
      '$': 'USD',
      '£': 'GBP',
      '€': 'EUR',
      '¥': 'JPY',
      'C$': 'CAD',
      'A$': 'AUD'
    };
    return currencyMap[symbol] || symbol;
  }

  // Fallback based on domain
  const domainMap = {
    'amazon.co.za': 'ZAR',
    'amazon.com': 'USD',
    'amazon.co.uk': 'GBP',
    'amazon.de': 'EUR',
    'amazon.fr': 'EUR',
    'amazon.it': 'EUR',
    'amazon.es': 'EUR',
    'amazon.co.jp': 'JPY',
    'amazon.ca': 'CAD',
    'amazon.com.au': 'AUD'
  };
  return domainMap[window.location.hostname] || 'USD';
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
    const reviewText = reviewEl.textContent.trim();
    // Extract number: "25 ratings" or "(25)" -> 25
    const cleaned = reviewText.replace(/[(),]/g, '').trim();
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
    return imgEl.src || imgEl.getAttribute('data-old-hires') || imgEl.getAttribute('data-a-dynamic-image');
  }
  return null;
}

// Check if seller is Amazon
function isAmazonSeller(seller) {
  if (!seller) return false;
  return /amazon/i.test(seller);
}

// Determine buybox status
function determineBuyboxStatus(seller) {
  if (!seller || seller === 'Unknown') return 'unknown';
  if (isAmazonSeller(seller)) return 'amazon';
  
  // You can customize this with your seller name
  // For now, assume non-Amazon = losing
  return 'losing';
}

// Add visual indicator when extension is active
function showExtensionIndicator() {
  const indicator = document.createElement('div');
  indicator.id = 'buybox-tracker-indicator';
  indicator.innerHTML = '🎯 Buybox Tracker Active';
  indicator.style.cssText = `
    position: fixed;
    bottom: 20px;
    right: 20px;
    background: #FF9900;
    color: white;
    padding: 10px 15px;
    border-radius: 5px;
    font-family: Arial, sans-serif;
    font-size: 12px;
    font-weight: bold;
    z-index: 999999;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    opacity: 0;
    transition: opacity 0.3s;
  `;
  document.body.appendChild(indicator);
  
  // Fade in
  setTimeout(() => indicator.style.opacity = '1', 100);
  
  // Fade out after 3 seconds
  setTimeout(() => {
    indicator.style.opacity = '0';
    setTimeout(() => indicator.remove(), 300);
  }, 3000);
}

// Show indicator when page loads
if (window.location.pathname.match(/\/(?:dp|gp\/product)\//)) {
  showExtensionIndicator();
}
