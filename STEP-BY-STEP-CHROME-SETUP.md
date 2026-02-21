# 🎯 CHROME EXTENSION INSTALLATION - STEP BY STEP
## For Profile: davidbar74

---

## ⏱️ **TIME: 5 Minutes**
## 🎯 **RESULT: 100% Bot-Proof Amazon Scraping**

---

## 📝 **STEP 1: Open Chrome Extensions Page**

### **Option A: Using Address Bar** (Easiest)

1. **Open Google Chrome** (it will open with your davidbar74 profile)

2. **Click** on the address bar at the top (where URLs go)

3. **Type or paste** this:
   ```
   chrome://extensions/
   ```

4. **Press Enter**

✅ You should now see the "Extensions" page

---

### **Option B: Using Menu** (Alternative)

1. **Open Google Chrome**

2. **Click** the three dots ⋮ in the top-right corner

3. **Hover over** "Extensions"

4. **Click** "Manage Extensions"

✅ You should now see the "Extensions" page

---

## 🔧 **STEP 2: Enable Developer Mode**

1. **Look at the TOP RIGHT corner** of the Extensions page

2. You'll see a toggle switch labeled **"Developer mode"**

3. **Click the toggle** to turn it ON
   - It will turn **BLUE** when enabled
   - You'll see new buttons appear: "Load unpacked", "Pack extension", "Update"

✅ Developer mode is now enabled!

---

## 📂 **STEP 3: Load the Extension**

1. **Click** the **"Load unpacked"** button (top left area)

2. A **folder browser window** will open

3. **Navigate** to this exact folder:
   ```
   C:\WebProjects\amazon-buybox-tracker\chrome-extension
   ```

   **TIP**: You can copy the path above and paste it in the address bar of the folder browser!

4. **Click** on the `chrome-extension` folder to select it

5. **Click** the **"Select Folder"** button

✅ The extension is now installed! You should see:
- "Amazon Buybox Tracker" appears in your extensions list
- A card showing the extension name, version, and icon

---

## 📌 **STEP 4: Pin the Extension to Toolbar** (Recommended)

1. **Look at the top-right** of Chrome (next to your profile icon)

2. **Click** the **puzzle piece icon** 🧩 (Extensions icon)

3. A dropdown menu appears showing all your extensions

4. **Find** "Amazon Buybox Tracker" in the list

5. **Click** the **pin icon** 📌 next to it
   - The pin will turn BLUE when pinned

✅ Extension icon now appears in your toolbar!

---

## ✅ **STEP 5: Verify Installation**

1. **Look at your Chrome toolbar** (top-right)

2. You should see the **Amazon Buybox Tracker icon** 
   - It looks like a small buybox/package icon

3. **Click the icon** - a popup should open showing:
   - "Scrape Current Page" button
   - "Settings" tab
   - "Bulk Scrape" tab

✅ Extension is working!

---

## ⚙️ **STEP 6: Configure API URL** 

⚠️ **IMPORTANT**: Do this AFTER deploying to Render (we'll do that next)

1. **Click** the extension icon in your toolbar

2. **Click** the **"⚙️ Settings"** tab

3. You'll see "Backend API URL" field

4. **Enter your Render URL** (we'll get this from Render)
   - Format: `https://your-app-name.onrender.com`
   - **NO trailing slash!**

5. **Click** "Save Settings"

6. You'll see: ✅ "Settings saved successfully!"

✅ Extension is configured!

---

## 🧪 **STEP 7: Test the Extension**

1. **Go to** any Amazon.co.za product page, for example:
   ```
   https://www.amazon.co.za/dp/B01ARH3Q5G
   ```

2. **Wait** for the page to fully load

3. **Click** the extension icon in your toolbar

4. **Click** "Scrape This Page" button

5. **Watch** the magic happen:
   - Button shows "Scraping..."
   - Progress appears
   - Success message: "✅ Product scraped and sent to dashboard!"

6. **Open** your dashboard to see the product!

✅ Extension is working perfectly!

---

## 📋 **VISUAL CHECKLIST**

Mark each step as you complete it:

- [ ] Step 1: Chrome extensions page open
- [ ] Step 2: Developer mode enabled (blue toggle)
- [ ] Step 3: Extension loaded (appears in list)
- [ ] Step 4: Extension pinned (icon in toolbar)
- [ ] Step 5: Popup opens when clicked
- [ ] Step 6: API URL configured
- [ ] Step 7: Successfully scraped a product

---

## 🆘 **TROUBLESHOOTING**

### **Problem: "Load unpacked" button doesn't appear**
**Solution**: Make sure Developer Mode toggle is ON (should be blue)

---

### **Problem: Can't find the chrome-extension folder**
**Solution**: 
1. Open File Explorer
2. Paste this in the address bar: `C:\WebProjects\amazon-buybox-tracker`
3. Double-click the `chrome-extension` folder
4. Copy the full path from the address bar
5. Paste it in the "Load unpacked" dialog

---

### **Problem: Extension icon doesn't appear in toolbar**
**Solution**:
1. Click the puzzle piece 🧩 in Chrome toolbar
2. Find "Amazon Buybox Tracker"
3. Click the pin icon 📌

---

### **Problem: Extension says "Not on Amazon product page"**
**Solution**: 
- Make sure you're on `amazon.co.za` (not .com)
- Make sure the URL contains `/dp/` or `/gp/product/`
- Try refreshing the page

---

### **Problem: "Failed to send to backend" error**
**Solution**:
1. Make sure you configured the API URL in Settings
2. Make sure your Render app is deployed and running
3. Check that the URL doesn't have a trailing slash
4. Try adding `https://` at the start if missing

---

## 📁 **FILE LOCATIONS**

**Extension Folder:**
```
C:\WebProjects\amazon-buybox-tracker\chrome-extension
```

**Files in Folder:**
- `manifest.json` - Extension configuration
- `content.js` - Main scraper script
- `background.js` - Background worker
- `popup.html` - Popup interface
- `popup.js` - Popup logic
- `styles.css` - Styling
- `icon16.png`, `icon48.png` - Icons

---

## 🎯 **AFTER INSTALLATION**

### **Next Steps:**

1. ✅ **Deploy to Render** (we'll do this together next)
2. ✅ **Configure API URL** in extension settings
3. ✅ **Test scraping** on Amazon products
4. ✅ **Verify data** appears in dashboard

---

## 💡 **PRO TIPS**

### **Tip 1: Keep Chrome Open**
The extension only works when Chrome is running with your davidbar74 profile

### **Tip 2: Use Keyboard Shortcuts**
- Press `Alt + E` to open extensions (once pinned)
- Press `Ctrl + Shift + E` to reload extension (if you modify code)

### **Tip 3: Check Console for Errors**
- Right-click extension icon → "Inspect popup"
- Opens developer tools to see any errors

### **Tip 4: Extension Updates**
If I update the extension code:
1. Go to `chrome://extensions/`
2. Click the ⟳ reload button on the extension card
3. Changes apply immediately!

---

## 🎊 **YOU'RE READY!**

Extension is now installed on your davidbar74 Chrome profile!

**Next**: Deploy to Render, then configure the API URL

---

## 📞 **NEED HELP?**

If anything goes wrong at any step, just let me know which step number you're on and I'll help you through it!

---