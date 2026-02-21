# 🚀 Render Auto-Deploy Setup

## Quick Setup (2 minutes)

### **Step 1: Enable Auto-Deploy on Render**

1. Go to: https://dashboard.render.com
2. Click on your service: **`buybox-tracker-api`**
3. Click **"Settings"** tab (left sidebar)
4. Scroll to **"Build & Deploy"** section
5. Find **"Auto-Deploy"**
6. Set to: **"Yes"** ✅
7. Click **"Save Changes"**

**Done!** 🎉

---

## **What Happens Now**

Every time you (or I) do `git push`, Render will:
1. ✅ Detect the push automatically
2. ✅ Build your app
3. ✅ Deploy the latest code
4. ✅ Restart your service

**No manual clicking needed!**

---

## **Optional: Branch Selection**

In the same Settings page, you can choose which branch to auto-deploy:
- **Default**: `main` branch (recommended)
- **Can change to**: `production`, `dev`, etc.

---

## **How to Verify It's Working**

After you enable auto-deploy:

1. I'll make a small test change
2. Push to GitHub
3. Go to Render → Events tab
4. You'll see: "Deploy triggered by push to main"
5. ✅ Automatic deployment!

---

## **Deployment Time**

- ⏱️ Takes: 2-5 minutes per deployment
- 📊 You can watch: Live logs in Events tab
- 🔔 Optional: Set up email notifications for deploy success/failure

---

## **Current Status**

- GitHub repo: ✅ Connected
- Auto-deploy: ❌ **Needs manual enable** (you must do this in Render dashboard)
- Branch: `main`

---

**Enable this NOW so future fixes deploy automatically!** 🚀
