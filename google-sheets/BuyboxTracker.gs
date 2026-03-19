// ============================================================
// BONOLO BUYBOX TRACKER — Google Apps Script
// ============================================================
// SETUP (one-time, 2 minutes):
// 1. Open your Google Sheet
// 2. Click Extensions → Apps Script
// 3. Delete any existing code, paste this entire file
// 4. Click 💾 Save, then run setupSheet() once from the menu
// 5. Reload the sheet — menu "🛒 Buybox Tracker" will appear
// ============================================================

var BACKEND_URL   = "https://amazon-buybox-tracker.onrender.com";
var AMAZON_FEE    = 0.06;   // 6% Amazon ZA fee
var MIN_MARGIN    = 0.05;   // 5% minimum margin floor
var TARGET_MARGIN = 0.20;   // 20% target margin
var SHEET_NAME    = "Buybox Tracker";

// Column positions (1-based)
var C_SKU          = 1;
var C_ASIN         = 2;
var C_TITLE        = 3;
var C_MY_PRICE     = 4;
var C_COST         = 5;
var C_MIN_PRICE    = 6;
var C_MAX_PRICE    = 7;
var C_BUYBOX_PRICE = 8;
var C_BUYBOX_SELLER= 9;
var C_STATUS       = 10;
var C_PROFIT       = 11;
var C_MARGIN       = 12;
var C_SUPPLIER     = 13;
var C_STOCK        = 14;
var C_LAST_CHECKED = 15;
var C_ACTION       = 16;


// ── Menu ─────────────────────────────────────────────────────
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("🛒 Buybox Tracker")
    .addItem("🔄 Refresh All Buybox Data", "refreshAllBuybox")
    .addSeparator()
    .addItem("💰 Push ALL My Prices to Amazon", "pushAllPrices")
    .addItem("🤖 Auto-Reprice All (Beat Buybox by R1)", "autoRepriceAll")
    .addSeparator()
    .addItem("📊 Sync Costs from Google Sheet", "syncCostsFromBackend")
    .addItem("🔁 Sync Products from Backend", "syncProductsFromBackend")
    .addSeparator()
    .addItem("⚙️ Setup Sheet (first time only)", "setupSheet")
    .addToUi();
}

// ── Setup Sheet Structure ────────────────────────────────────
function setupSheet() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) sheet = ss.insertSheet(SHEET_NAME);

  sheet.clearFormats();
  sheet.setFrozenRows(1);

  // Set column widths
  sheet.setColumnWidth(C_SKU, 120);
  sheet.setColumnWidth(C_ASIN, 120);
  sheet.setColumnWidth(C_TITLE, 260);
  sheet.setColumnWidth(C_MY_PRICE, 100);
  sheet.setColumnWidth(C_COST, 90);
  sheet.setColumnWidth(C_MIN_PRICE, 100);
  sheet.setColumnWidth(C_MAX_PRICE, 100);
  sheet.setColumnWidth(C_BUYBOX_PRICE, 110);
  sheet.setColumnWidth(C_BUYBOX_SELLER, 160);
  sheet.setColumnWidth(C_STATUS, 110);
  sheet.setColumnWidth(C_PROFIT, 90);
  sheet.setColumnWidth(C_MARGIN, 80);
  sheet.setColumnWidth(C_SUPPLIER, 120);
  sheet.setColumnWidth(C_STOCK, 70);
  sheet.setColumnWidth(C_LAST_CHECKED, 140);
  sheet.setColumnWidth(C_ACTION, 160);

  // Write headers
  var headers = [
    "SKU", "ASIN", "Title", "My Price (R)", "Cost (R)",
    "Min Price (R)", "Max Price (R)", "Buybox Price (R)", "Buybox Seller",
    "Status", "Profit (R)", "Margin %", "Supplier", "Stock",
    "Last Checked", "Action"
  ];
  var headerRange = sheet.getRange(1, 1, 1, headers.length);
  headerRange.setValues([headers]);
  headerRange.setBackground("#1a1a2e");
  headerRange.setFontColor("#ffffff");
  headerRange.setFontWeight("bold");
  headerRange.setFontSize(10);

  SpreadsheetApp.getUi().alert("✅ Sheet setup complete! Now run '🔁 Sync Products from Backend' from the menu to load your products.");
}


// ── Sync Products from Backend ───────────────────────────────
function syncProductsFromBackend() {
  var ui = SpreadsheetApp.getUi();
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) { ui.alert("Run Setup Sheet first!"); return; }

  ui.alert("⏳ Fetching products from backend... Click OK and wait ~10 seconds.");

  try {
    var resp = UrlFetchApp.fetch(BACKEND_URL + "/api/buybox/tracked", {muteHttpExceptions: true});
    var data = JSON.parse(resp.getContentText());
    var products = data.asins || [];

    if (!products.length) { ui.alert("No products found in backend."); return; }

    // Clear existing data rows (keep header)
    var lastRow = sheet.getLastRow();
    if (lastRow > 1) sheet.getRange(2, 1, lastRow - 1, 16).clearContent();

    var rows = products.map(function(p) {
      var cost      = p.cost_price || 0;
      var myPrice   = p.my_price   || 0;
      var minPrice  = cost > 0 ? cost / (1 - AMAZON_FEE - MIN_MARGIN)    : "";
      var maxPrice  = cost > 0 ? cost / (1 - AMAZON_FEE - TARGET_MARGIN) : "";
      var profit    = (cost > 0 && myPrice > 0) ? (myPrice * (1 - AMAZON_FEE)) - cost : "";
      var margin    = (profit !== "" && myPrice > 0) ? (profit / myPrice) * 100 : "";

      return [
        p.sku            || "",
        p.asin           || "",
        p.title          || "",
        myPrice          || "",
        cost             || "",
        minPrice !== ""  ? Math.round(minPrice * 100) / 100 : "",
        maxPrice !== ""  ? Math.round(maxPrice * 100) / 100 : "",
        p.buybox_price   || "",
        p.buybox_seller  || "",
        p.buybox_status  || "",
        profit  !== ""   ? Math.round(profit * 100) / 100 : "",
        margin  !== ""   ? Math.round(margin * 10) / 10 : "",
        p.cost_supplier  || "",
        p.my_stock !== null ? p.my_stock : "",
        p.scraped_at     ? new Date(p.scraped_at).toLocaleString() : "",
        p.sku            ? "Push Price" : ""
      ];
    });

    sheet.getRange(2, 1, rows.length, 16).setValues(rows);
    applyConditionalFormatting(sheet, rows.length);
    ui.alert("✅ Loaded " + rows.length + " products from backend!");

  } catch(e) {
    ui.alert("❌ Error: " + e.message);
  }
}


// ── Refresh Buybox Data ──────────────────────────────────────
function refreshAllBuybox() {
  var ui  = SpreadsheetApp.getUi();
  var ss  = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) { ui.alert("Run Setup Sheet first!"); return; }

  try {
    var resp = UrlFetchApp.fetch(BACKEND_URL + "/api/buybox/tracked", {muteHttpExceptions: true});
    var data = JSON.parse(resp.getContentText());
    var products = data.asins || [];
    if (!products.length) { ui.alert("No products found."); return; }

    // Build lookup by ASIN
    var lookup = {};
    products.forEach(function(p) { lookup[p.asin] = p; });

    var lastRow = sheet.getLastRow();
    if (lastRow < 2) { ui.alert("No data rows. Run Sync Products first."); return; }

    var asins = sheet.getRange(2, C_ASIN, lastRow - 1, 1).getValues();
    var updated = 0;

    for (var i = 0; i < asins.length; i++) {
      var asin = asins[i][0];
      if (!asin) continue;
      var p = lookup[asin];
      if (!p) continue;
      var row = i + 2;

      var cost    = sheet.getRange(row, C_COST).getValue() || 0;
      var myPrice = sheet.getRange(row, C_MY_PRICE).getValue() || 0;
      var profit  = (cost > 0 && myPrice > 0) ? (myPrice * (1 - AMAZON_FEE)) - cost : "";
      var margin  = (profit !== "" && myPrice > 0) ? (profit / myPrice) * 100 : "";

      sheet.getRange(row, C_BUYBOX_PRICE).setValue(p.buybox_price || "");
      sheet.getRange(row, C_BUYBOX_SELLER).setValue(p.buybox_seller || "");
      sheet.getRange(row, C_STATUS).setValue(p.buybox_status || "");
      sheet.getRange(row, C_TITLE).setValue(p.title || "");
      sheet.getRange(row, C_PROFIT).setValue(profit !== "" ? Math.round(profit * 100) / 100 : "");
      sheet.getRange(row, C_MARGIN).setValue(margin !== "" ? Math.round(margin * 10) / 10 : "");
      sheet.getRange(row, C_LAST_CHECKED).setValue(new Date().toLocaleString());
      updated++;
    }

    applyConditionalFormatting(sheet, lastRow - 1);
    ui.alert("✅ Updated buybox data for " + updated + " products.");
  } catch(e) {
    ui.alert("❌ Error: " + e.message);
  }
}

// ── Sync Costs from Backend ───────────────────────────────────
function syncCostsFromBackend() {
  var ui = SpreadsheetApp.getUi();
  try {
    var resp = UrlFetchApp.fetch(BACKEND_URL + "/api/costs/sync-gsheet", {muteHttpExceptions: true});
    var d    = JSON.parse(resp.getContentText());
    ui.alert("✅ Cost sync done!\n\nUpdated: " + (d.updated || 0) + " products\nSKUs loaded: " + (d.sheet_skus_loaded || 0) + "\n\nNow run 🔁 Sync Products to reload the sheet.");
  } catch(e) {
    ui.alert("❌ Error: " + e.message);
  }
}


// ── Push Single Row Price to Amazon ──────────────────────────
// Called when user edits Column D (My Price) — auto-push prompt
function onEdit(e) {
  var sheet = e.range.getSheet();
  if (sheet.getName() !== SHEET_NAME) return;
  if (e.range.getColumn() !== C_MY_PRICE) return;
  var row = e.range.getRow();
  if (row < 2) return;

  var sku   = sheet.getRange(row, C_SKU).getValue();
  var asin  = sheet.getRange(row, C_ASIN).getValue();
  var price = e.range.getValue();

  if (!sku || !price || price <= 0) return;

  var ui = SpreadsheetApp.getUi();
  var result = ui.alert(
    "💰 Push Price to Amazon?",
    "SKU: " + sku + "\nNew Price: R" + price.toFixed(2) + "\n\nPush this price to Amazon Seller Central now?",
    ui.ButtonSet.YES_NO
  );
  if (result !== ui.Button.YES) return;
  pushSinglePrice(sku, asin, price, sheet, row);
}

function pushSinglePrice(sku, asin, price, sheet, row) {
  try {
    var payload = JSON.stringify({sku: sku, price: price, asin: asin});
    var opts = {
      method: "post",
      contentType: "application/json",
      payload: payload,
      muteHttpExceptions: true
    };
    var resp = UrlFetchApp.fetch(BACKEND_URL + "/api/amazon/push-price", opts);
    var d    = JSON.parse(resp.getContentText());
    if (d.ok) {
      sheet.getRange(row, C_ACTION).setValue("✅ Pushed R" + price.toFixed(2));
      sheet.getRange(row, C_ACTION).setBackground("#d4edda").setFontColor("#155724");
      recalcRow(sheet, row);
    } else {
      sheet.getRange(row, C_ACTION).setValue("❌ " + (d.message || "Failed"));
      sheet.getRange(row, C_ACTION).setBackground("#f8d7da").setFontColor("#721c24");
    }
  } catch(e) {
    sheet.getRange(row, C_ACTION).setValue("❌ Error: " + e.message);
  }
}

// ── Push ALL Prices to Amazon ─────────────────────────────────
function pushAllPrices() {
  var ui = SpreadsheetApp.getUi();
  var result = ui.alert("⚠️ Push ALL prices?", "This will push every row's My Price to Amazon. Continue?", ui.ButtonSet.YES_NO);
  if (result !== ui.Button.YES) return;

  var sheet   = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME);
  var lastRow = sheet.getLastRow();
  var ok = 0, failed = 0;

  for (var row = 2; row <= lastRow; row++) {
    var sku   = sheet.getRange(row, C_SKU).getValue();
    var asin  = sheet.getRange(row, C_ASIN).getValue();
    var price = sheet.getRange(row, C_MY_PRICE).getValue();
    if (!sku || !price || price <= 0) continue;

    try {
      var resp = UrlFetchApp.fetch(BACKEND_URL + "/api/amazon/push-price", {
        method: "post", contentType: "application/json",
        payload: JSON.stringify({sku: sku, price: price, asin: asin}),
        muteHttpExceptions: true
      });
      var d = JSON.parse(resp.getContentText());
      if (d.ok) {
        sheet.getRange(row, C_ACTION).setValue("✅ Pushed");
        sheet.getRange(row, C_ACTION).setBackground("#d4edda").setFontColor("#155724");
        ok++;
      } else {
        sheet.getRange(row, C_ACTION).setValue("❌ Failed");
        failed++;
      }
    } catch(err) { failed++; }
    Utilities.sleep(300); // small delay to avoid rate limits
  }
  ui.alert("✅ Push complete!\n\nPushed: " + ok + "\nFailed: " + failed);
}


// ── Auto-Reprice: Beat Buybox by R1 (never below Min Price) ──
function autoRepriceAll() {
  var ui = SpreadsheetApp.getUi();
  var result = ui.alert(
    "🤖 Auto-Reprice All?",
    "Sets your price to Buybox Price − R1.00\nWill NEVER go below Min Price (5% margin floor)\nWill NOT exceed Max Price (20% target)\n\nContinue?",
    ui.ButtonSet.YES_NO
  );
  if (result !== ui.Button.YES) return;

  var sheet   = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME);
  var lastRow = sheet.getLastRow();
  var repriced = 0, skipped = 0, atFloor = 0;

  for (var row = 2; row <= lastRow; row++) {
    var sku        = sheet.getRange(row, C_SKU).getValue();
    var asin       = sheet.getRange(row, C_ASIN).getValue();
    var cost       = sheet.getRange(row, C_COST).getValue() || 0;
    var bbPrice    = sheet.getRange(row, C_BUYBOX_PRICE).getValue() || 0;
    var status     = sheet.getRange(row, C_STATUS).getValue();

    if (!sku || !bbPrice || !cost) { skipped++; continue; }
    if (status === "winning") { skipped++; continue; } // already winning

    var minPrice = cost / (1 - AMAZON_FEE - MIN_MARGIN);
    var maxPrice = cost / (1 - AMAZON_FEE - TARGET_MARGIN);

    var newPrice = bbPrice - 1.00;

    // Apply floor/ceiling
    if (newPrice < minPrice) {
      newPrice = minPrice; // can't go lower
      atFloor++;
    }
    if (newPrice > maxPrice) newPrice = maxPrice;

    newPrice = Math.round(newPrice * 100) / 100;

    // Update sheet
    sheet.getRange(row, C_MY_PRICE).setValue(newPrice);
    sheet.getRange(row, C_MIN_PRICE).setValue(Math.round(minPrice * 100) / 100);
    sheet.getRange(row, C_MAX_PRICE).setValue(Math.round(maxPrice * 100) / 100);
    recalcRow(sheet, row);

    // Push to Amazon
    try {
      var resp = UrlFetchApp.fetch(BACKEND_URL + "/api/amazon/push-price", {
        method: "post", contentType: "application/json",
        payload: JSON.stringify({sku: sku, price: newPrice, asin: asin}),
        muteHttpExceptions: true
      });
      var d = JSON.parse(resp.getContentText());
      var actionMsg = d.ok ? ("🤖 R" + newPrice.toFixed(2)) : "❌ Push failed";
      sheet.getRange(row, C_ACTION).setValue(actionMsg);
      if (d.ok) sheet.getRange(row, C_ACTION).setBackground("#cfe2ff").setFontColor("#084298");
      else sheet.getRange(row, C_ACTION).setBackground("#f8d7da").setFontColor("#721c24");
    } catch(err) {
      sheet.getRange(row, C_ACTION).setValue("❌ " + err.message);
    }

    repriced++;
    Utilities.sleep(200);
  }

  applyConditionalFormatting(sheet, lastRow - 1);
  ui.alert(
    "🤖 Auto-Reprice Done!\n\n" +
    "✅ Repriced: " + repriced + "\n" +
    "⚠️ At price floor (5%): " + atFloor + "\n" +
    "⏭️ Skipped: " + skipped
  );
}

// ── Recalc profit/margin for a single row ────────────────────
function recalcRow(sheet, row) {
  var myPrice = sheet.getRange(row, C_MY_PRICE).getValue() || 0;
  var cost    = sheet.getRange(row, C_COST).getValue() || 0;
  if (myPrice > 0 && cost > 0) {
    var profit = (myPrice * (1 - AMAZON_FEE)) - cost;
    var margin = (profit / myPrice) * 100;
    sheet.getRange(row, C_PROFIT).setValue(Math.round(profit * 100) / 100);
    sheet.getRange(row, C_MARGIN).setValue(Math.round(margin * 10) / 10);
  }
  if (cost > 0) {
    sheet.getRange(row, C_MIN_PRICE).setValue(Math.round(cost / (1 - AMAZON_FEE - MIN_MARGIN) * 100) / 100);
    sheet.getRange(row, C_MAX_PRICE).setValue(Math.round(cost / (1 - AMAZON_FEE - TARGET_MARGIN) * 100) / 100);
  }
}


// ── Conditional Formatting (colours by status) ───────────────
function applyConditionalFormatting(sheet, numRows) {
  if (numRows < 1) return;
  var range = sheet.getRange(2, 1, numRows, 16);

  // Clear old rules
  sheet.clearConditionalFormatRules();
  var rules = [];

  // Winning → green row
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$J2="winning"')
    .setBackground("#d4edda").setFontColor("#155724")
    .setRanges([range]).build());

  // Losing → red row
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$J2="losing"')
    .setBackground("#f8d7da").setFontColor("#721c24")
    .setRanges([range]).build());

  // Amazon wins → blue row
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=$J2="amazon"')
    .setBackground("#cfe2ff").setFontColor("#084298")
    .setRanges([range]).build());

  // Negative profit → red in profit col
  var profitRange = sheet.getRange(2, C_PROFIT, numRows, 1);
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenNumberLessThan(0)
    .setFontColor("#dc3545")
    .setRanges([profitRange]).build());

  // My Price below Min Price → orange warning
  rules.push(SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=AND($D2>0,$F2>0,$D2<$F2)')
    .setBackground("#fff3cd").setFontColor("#856404")
    .setRanges([sheet.getRange(2, C_MY_PRICE, numRows, 1)]).build());

  sheet.setConditionalFormatRules(rules);

  // Format number columns as currency
  sheet.getRange(2, C_MY_PRICE,     numRows, 1).setNumberFormat("R#,##0.00");
  sheet.getRange(2, C_COST,         numRows, 1).setNumberFormat("R#,##0.00");
  sheet.getRange(2, C_MIN_PRICE,    numRows, 1).setNumberFormat("R#,##0.00");
  sheet.getRange(2, C_MAX_PRICE,    numRows, 1).setNumberFormat("R#,##0.00");
  sheet.getRange(2, C_BUYBOX_PRICE, numRows, 1).setNumberFormat("R#,##0.00");
  sheet.getRange(2, C_PROFIT,       numRows, 1).setNumberFormat("R#,##0.00");
  sheet.getRange(2, C_MARGIN,       numRows, 1).setNumberFormat("0.0\"%\"");
}

// ── Hourly Auto-Refresh Trigger Setup ───────────────────────
// Run this once manually from the Apps Script editor to enable hourly auto-refresh
function setupHourlyTrigger() {
  // Remove existing triggers first
  var triggers = ScriptApp.getProjectTriggers();
  for (var i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === "refreshAllBuybox") {
      ScriptApp.deleteTrigger(triggers[i]);
    }
  }
  // Create new hourly trigger
  ScriptApp.newTrigger("refreshAllBuybox")
    .timeBased()
    .everyHours(1)
    .create();
  SpreadsheetApp.getUi().alert("✅ Hourly auto-refresh enabled! Buybox data will update every hour automatically.");
}

function removeHourlyTrigger() {
  var triggers = ScriptApp.getProjectTriggers();
  var removed = 0;
  for (var i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === "refreshAllBuybox") {
      ScriptApp.deleteTrigger(triggers[i]);
      removed++;
    }
  }
  SpreadsheetApp.getUi().alert("✅ Removed " + removed + " auto-refresh trigger(s).");
}

// ── doPost — Backend pushes buybox data to this sheet ────────
// Deploy this script as a Web App (Execute as: Me, Who has access: Anyone)
// Then set GSHEET_WEBAPP_URL env var on Render to the deployment URL
function doPost(e) {
  try {
    var payload = JSON.parse(e.postData.contents);
    var products = payload.products || [];
    if (!products.length) return jsonResponse({ok: true, updated: 0});

    var ss    = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = ss.getSheetByName(SHEET_NAME);
    if (!sheet) return jsonResponse({ok: false, error: "Sheet not found"});

    // Build SKU → row index lookup from existing data
    var lastRow = sheet.getLastRow();
    var skuMap  = {};
    if (lastRow > 1) {
      var skuData = sheet.getRange(2, C_SKU, lastRow - 1, 1).getValues();
      for (var i = 0; i < skuData.length; i++) {
        if (skuData[i][0]) skuMap[String(skuData[i][0]).toLowerCase()] = i + 2;
      }
    }

    var updated = 0;
    var added   = 0;

    for (var j = 0; j < products.length; j++) {
      var p       = products[j];
      var cost    = p.cost_price  || 0;
      var myPrice = p.my_price    || 0;
      var profit  = (cost > 0 && myPrice > 0) ? Math.round((myPrice * (1 - AMAZON_FEE) - cost) * 100) / 100 : "";
      var margin  = (profit !== "" && myPrice > 0) ? Math.round((profit / myPrice) * 1000) / 10 : "";
      var minP    = cost > 0 ? Math.round(cost / (1 - AMAZON_FEE - MIN_MARGIN))    : "";
      var maxP    = cost > 0 ? Math.round(cost / (1 - AMAZON_FEE - TARGET_MARGIN)) : "";

      var row = [
        p.sku           || "",
        p.asin          || "",
        p.title         || "",
        myPrice         || "",
        cost            || "",
        minP,
        maxP,
        p.buybox_price  || "",
        p.buybox_seller || "",
        p.buybox_status || "",
        profit,
        margin,
        p.cost_supplier || "",
        p.my_stock !== null && p.my_stock !== undefined ? p.my_stock : "",
        p.scraped_at ? new Date(p.scraped_at).toLocaleString() : "",
        p.sku ? "Push Price" : ""
      ];

      var skuKey = p.sku ? p.sku.toLowerCase() : null;
      if (skuKey && skuMap[skuKey]) {
        // Update existing row
        sheet.getRange(skuMap[skuKey], 1, 1, row.length).setValues([row]);
        updated++;
      } else {
        // Append new row
        sheet.appendRow(row);
        added++;
      }
    }

    // Re-apply formatting
    var newLastRow = sheet.getLastRow();
    if (newLastRow > 1) applyConditionalFormatting(sheet, newLastRow - 1);

    return jsonResponse({ok: true, updated: updated, added: added, total: products.length});

  } catch(err) {
    return jsonResponse({ok: false, error: err.message});
  }
}

function jsonResponse(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

