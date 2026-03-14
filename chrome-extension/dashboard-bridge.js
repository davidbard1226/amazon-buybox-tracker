// dashboard-bridge.js — Runs on the Buybox Tracker dashboard page
// Automatically injects the extension ID so Push Changes can use auto-upload
// Version 1.0.0

(function injectExtensionId() {
  try {
    const extId = chrome.runtime.id;
    if (!extId) return;

    // Write directly into the page's localStorage
    localStorage.setItem('extensionId', extId);
    console.log('✅ Buybox Tracker: Extension ID injected:', extId);

    // Fire a custom event so dashboard JS can react immediately
    window.dispatchEvent(new CustomEvent('buyboxExtensionReady', { detail: { extId } }));
  } catch (e) {
    console.warn('Buybox dashboard-bridge error:', e);
  }
})();
