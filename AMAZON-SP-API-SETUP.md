# 🔑 Amazon SP-API Setup Guide - Complete Step-by-Step

## What is Amazon SP-API?

**SP-API** = Selling Partner API (Amazon's official API for sellers)

**Benefits vs Web Scraping:**
- ✅ **No bot detection** - It's official!
- ✅ **Real-time data** - Get buybox info instantly
- ✅ **100% reliable** - No blocks or CAPTCHAs
- ✅ **Can update prices** - Auto-repricing possible!
- ✅ **FREE** - No cost for Amazon sellers
- ✅ **Fast** - Get data in milliseconds vs 3+ seconds scraping

---

## 📋 What You Need

1. **Amazon Seller Central Account** (you already have this!)
2. **SP-API Developer Account** (free registration)
3. **AWS Account** (free tier is enough)
4. **15-30 minutes** to set up

---

## 🚀 Step-by-Step Setup

### **STEP 1: Register as SP-API Developer** (5 minutes)

1. Go to: **Seller Central** → https://sellercentral.amazon.com
2. Navigate to: **Apps & Services** → **Develop Apps**
3. Click: **"Add new app client"**
4. Fill in:
   - **App Name**: `Buybox Tracker`
   - **OAuth Redirect URI**: `https://localhost` (or your domain)
   - **IAM ARN**: Leave blank for now
5. Click **"Save and Exit"**

✅ You'll get:
- **LWA Client ID** (like: `amzn1.application-oa2-client.xxxxx`)
- **LWA Client Secret** (like: `amzn1.oa2-cs.v1.xxxxx`)

**⚠️ SAVE THESE!** You need them for authentication.

---

### **STEP 2: Create AWS IAM User** (10 minutes)

Amazon SP-API uses AWS for authentication.

1. Go to: **AWS Console** → https://aws.amazon.com
2. Sign up for free account (if you don't have one)
3. Go to: **IAM** → **Users** → **Create User**
4. User name: `sp-api-user`
5. Select: **"Programmatic access"**
6. Permissions: **"Attach existing policies directly"**
   - Don't need any specific policies for SP-API
7. Click **"Create User"**

✅ You'll get:
- **AWS Access Key ID** (like: `AKIAIOSFODNN7EXAMPLE`)
- **AWS Secret Access Key** (like: `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY`)

**⚠️ SAVE THESE!** You can't view the secret key again.

---

### **STEP 3: Link IAM ARN to SP-API App** (2 minutes)

1. In AWS IAM, click on your `sp-api-user`
2. Copy the **ARN** (like: `arn:aws:iam::123456789012:user/sp-api-user`)
3. Go back to **Seller Central** → **Apps & Services** → **Develop Apps**
4. Edit your app
5. Paste the **IAM ARN**
6. Click **"Save"**

✅ Done! Your app is now linked to AWS.

---

### **STEP 4: Grant SP-API Permissions** (1 minute)

Still in Seller Central:

1. Click **"Authorize"** next to your app
2. Select permissions:
   - ✅ **Product Pricing** (to get buybox prices)
   - ✅ **Product Listings** (to update your prices)
   - ✅ **Catalog Items** (to get product details)
3. Click **"Authorize"**

---

## 🔑 Your SP-API Credentials

After setup, you'll have these 4 credentials:

```bash
# From Seller Central (Step 1)
LWA_CLIENT_ID=amzn1.application-oa2-client.xxxxx
LWA_CLIENT_SECRET=amzn1.oa2-cs.v1.xxxxx

# From AWS (Step 2)
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY

# Your Amazon Seller ID (find in Seller Central → Settings → Account Info)
SELLER_ID=A1B2C3D4E5F6G7

# Marketplace (for South Africa)
MARKETPLACE_ID=A1E5JOF6FQYU90
```

---

## 📦 Add to Your Dashboard

Once you have the credentials, I'll help you:

1. **Install Python SP-API library**
2. **Add credentials to Render environment variables**
3. **Replace web scraping with SP-API calls**
4. **Add automatic repricing feature**

---

## 🌍 Marketplace IDs (Reference)

| Country | Marketplace ID | Domain |
|---------|---------------|---------|
| **South Africa** | `A1E5JOF6FQYU90` | amazon.co.za |
| USA | `ATVPDKIKX0DER` | amazon.com |
| UK | `A1F83G8C2ARO7P` | amazon.co.uk |
| Germany | `A1PA6795UKMFR9` | amazon.de |
| Canada | `A2EUQ1WTGCTBG2` | amazon.ca |
| Australia | `A39IBJ37TRP1C6` | amazon.com.au |

---

## 🔄 What We'll Build After Setup

### **Phase 1: Replace Scraping with SP-API**
- Get buybox price via API (faster, no blocks)
- Get competitive pricing (see all offers)
- Get product details (title, image, ratings)

### **Phase 2: Add Auto-Repricing**
- Monitor competitor prices in real-time
- Automatically adjust your prices to win buybox
- Set min/max price limits
- Profit margin protection

### **Phase 3: Advanced Features**
- Email/WhatsApp alerts when you lose buybox
- Repricing rules (e.g., "Beat Amazon by 5%")
- Historical pricing charts
- Competitor analysis

---

## 💰 Cost

**SP-API**: ✅ **FREE** for Amazon sellers

**AWS**: 
- IAM User: ✅ **FREE**
- API Calls: ✅ **FREE** (within reasonable limits)
- Only pay if you use other AWS services (you won't)

**Total Cost**: ✅ **$0/month**

---

## ⏱️ Timeline

| Task | Time | Who Does It |
|------|------|-------------|
| Register SP-API Developer | 5 min | **You** |
| Create AWS IAM User | 10 min | **You** |
| Link IAM to SP-API | 2 min | **You** |
| Grant Permissions | 1 min | **You** |
| **TOTAL SETUP** | **~20 min** | **You** |
| Install SP-API library | 2 min | Me |
| Add credentials to Render | 3 min | Me (you provide credentials) |
| Replace scraping with API | 30 min | Me |
| Add repricing UI | 1 hour | Me |
| **TOTAL DEVELOPMENT** | **~2 hours** | **Me** |

---

## 🎯 Next Steps

**Ready to set up SP-API?**

1. **Follow Steps 1-4 above** (takes ~20 minutes)
2. **Share the 5 credentials with me** (securely)
3. **I'll integrate SP-API** into your dashboard
4. **You'll have buybox tracking + auto-repricing!**

---

## 📞 Questions?

Common questions:

**Q: Is this legal?**  
✅ Yes! It's Amazon's official API for sellers.

**Q: Will Amazon ban my account?**  
❌ No! This is the recommended way to build seller tools.

**Q: Do I need to pay for AWS?**  
✅ No! IAM users and SP-API calls are free.

**Q: How many API calls can I make?**  
✅ Reasonable limits: ~200 requests/minute (more than enough!)

**Q: Can I update prices automatically?**  
✅ Yes! Via the Listings API (I'll build this for you).

---

## 🚀 Ready to Start?

Let me know when you've completed Steps 1-4, and I'll integrate SP-API into your dashboard!

This will replace all web scraping with official Amazon API calls. 🎉
