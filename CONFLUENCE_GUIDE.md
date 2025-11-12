# Barcode Scanner Tool - Complete User Guide

> ℹ️ **What is this tool?**  
> This tool automatically detects barcodes from images (including HEIC format), fetches product names, and uploads results to Confluence. Perfect for documenting test images, produce items, and barcode validation.

---

## 📋 Table of Contents

1. [Create Your Confluence API Token](#step-1-create-your-confluence-api-token)
2. [Install the Tool](#step-2-install-the-tool-first-time-only)
3. [Using the Tool](#step-3-using-the-tool)
4. [Supported Formats & Barcodes](#supported-formats--barcodes)
5. [Common Options](#common-options)
6. [Troubleshooting](#troubleshooting)
7. [FAQ](#faq)

---

## 🔑 Step 1: Create Your Confluence API Token

**Why do I need this?** The API token allows the tool to upload images and create tables on your behalf. Each person needs their own token.

### 1.1 Generate API Token

1. Go to **[Atlassian Account Settings](https://id.atlassian.com/manage-profile/security/api-tokens)**
2. Click **"Create API token"**
3. Enter a label (e.g., "Barcode Scanner Tool")
4. Click **"Create"**
5. **Important:** Copy the token immediately - you won't be able to see it again!

> ⚠️ **Security Note:** Never share your API token with others! Each person should create their own token. Treat it like a password.

### 1.2 What You'll Need

Have these ready before starting:

- **Confluence URL:** `https://instacart.atlassian.net/wiki` (or your company's URL)
- **Your Email:** The email you use to log into Confluence
- **API Token:** The token you just created

---

## 💻 Step 2: Install the Tool (First Time Only)

### 2.1 Get the Code

```bash
# Clone the repository
git clone https://github.com/hamza-sohrab/test-barcode-proj.git
cd test-barcode-proj
```

### 2.2 Run Automated Setup (Recommended)

```bash
./setup.sh
```

The setup script will:
1. ✅ Check your Python version
2. ✅ Install system dependencies (zbar library)
3. ✅ Create a virtual environment
4. ✅ Install all Python packages
5. ✅ **Prompt for your Confluence credentials**

### 2.3 Enter Your Credentials

When prompted, enter your information:

```
⚠️  No credentials configured!

Let's set up your Confluence credentials...
(You can skip this and configure manually later)

Configure credentials now? (y/n): y

📝 Enter your Confluence credentials:

Confluence URL [https://instacart.atlassian.net/wiki]: (press Enter)
Your Confluence email: your.email@instacart.com

Get your API token from: https://id.atlassian.com/manage-profile/security/api-tokens
Your Confluence API token: (paste your token here)

✅ Credentials saved to env.local
```

> 💡 **You only do this once!** Your credentials are saved and you won't be asked again.

---

## 🚀 Step 3: Using the Tool

### 3.1 Activate the Virtual Environment

Every time you use the tool, first activate the environment:

```bash
cd /path/to/test_barcodes_proj
source .venv/bin/activate
```

You'll see `(.venv)` appear at the start of your terminal prompt.

### 3.2 Test Run (Dry Run - No Upload)

First, try a dry run to see what will be uploaded without actually uploading:

```bash
python -m confluence_uploader.cli \
  --src /path/to/your/images \
  --dry-run
```

**What you'll see:**

```
Scanning images: 100%|██████████| 10/10 [00:15<00:00]
DRY RUN RESULTS:
type=UPC-A    value=051000284174    name=Campbell's Clam Chowder    notes=
type=UPC-E    value=04963406        name=Coke Coca-Cola             notes=
type=DataBar  value=0100751972364415 name=                          notes=
```

### 3.3 Upload to Confluence

Once you're happy with the dry run results, upload for real:

```bash
python -m confluence_uploader.cli \
  --src /path/to/your/images \
  --page "https://instacart.atlassian.net/wiki/spaces/SPACE/pages/123456789/Your+Page"
```

**Or use page ID directly:**

```bash
python -m confluence_uploader.cli \
  --src /path/to/your/images \
  --page-id 123456789
```

> 💡 **Finding the Page ID:** Look at your Confluence page URL. The page ID is the number after `/pages/`  
> Example: `https://instacart.atlassian.net/wiki/spaces/TEST/pages/**123456789**/My-Page`

---

## 📂 Supported Formats & Barcodes

### Supported Image Formats

The tool works with:

- ✅ **HEIC/HEIF** (iPhone photos)
- ✅ **JPEG/JPG**
- ✅ **PNG**
- ✅ **BMP, TIFF, WEBP**
- ✅ **ZIP files** containing images

### Supported Barcode Types

| Type | Description | Example Use Case |
|------|-------------|------------------|
| **UPC-A** | Standard US product barcodes | Most retail products |
| **UPC-E** | Compressed UPC codes | Small packages |
| **EAN-13/EAN-8** | European product codes | International products |
| **Code 128** | Manager markdowns, internal codes | Store-generated labels |
| **DataBar** | Produce items with weight/price | Fresh fruits, vegetables |

---

## ⚙️ Common Options

### Basic Usage

```bash
# Dry run (no upload, just preview)
python -m confluence_uploader.cli --src /path/to/images --dry-run

# Upload to Confluence
python -m confluence_uploader.cli --src /path/to/images --page-id 123456789

# Scan a ZIP file
python -m confluence_uploader.cli --src /path/to/images.zip --page-id 123456789
```

### Disable Lookups (Faster)

If you just need barcodes without product names:

```bash
python -m confluence_uploader.cli \
  --src /path/to/images \
  --page-id 123456789 \
  --no-lookup \
  --no-deep-lookup \
  --no-free-lookup \
  --no-ocr
```

---

## ✨ Smart Features

### 🔄 Automatic Deduplication

- **Filename deduplication:** If you have "item.HEIC" and "item.jpeg" (same item, different formats), only one is processed
- **Barcode deduplication:** Same barcode won't be uploaded twice in one run
- **Page deduplication:** Checks existing page content to avoid duplicates across multiple runs

### 🔍 Detection Modes

- **Standard mode:** Fast detection for clear barcodes
- **Aggressive mode:** Tries harder on difficult images (rotations, enhancements, etc.)

### 🌐 Product Name Lookup

The tool tries multiple sources to find product names:

1. **OpenFoodFacts** - Free database of food products
2. **DuckDuckGo** - Free web search
3. **OCR** - Reads text directly from the image

---

## 🔧 Troubleshooting

### ❌ "bad interpreter" Error

```
bad interpreter: /Users/someone/.venv/bin/python3.13: no such file or directory
```

**Solution:** Delete the virtual environment and recreate it:

```bash
rm -rf .venv
./setup.sh
```

### ❌ "Unable to find zbar shared library"

**Solution:** Install the zbar system library:

```bash
# macOS
brew install zbar

# Ubuntu/Debian
sudo apt-get install libzbar0
```

### ❌ "No barcodes detected"

**Possible causes:**

- Images don't contain barcodes
- Barcodes are too small or blurry
- Try with `--aggressive` flag for difficult images

### ❌ Using Someone Else's Credentials

**Solution:** Delete the old `env.local` and create your own:

```bash
rm env.local
./setup.sh  # Will prompt for YOUR credentials
```

---

## 📖 Real-World Examples

### Example 1: Upload Test Images

```bash
# Preview first
python -m confluence_uploader.cli \
  --src ~/Desktop/test_images \
  --dry-run

# Upload to your test page
python -m confluence_uploader.cli \
  --src ~/Desktop/test_images \
  --page-id 987654321
```

### Example 2: Produce Items (Fast Mode)

```bash
# Skip lookups for faster processing
python -m confluence_uploader.cli \
  --src ~/Desktop/produce_images \
  --page-id 987654321 \
  --no-lookup --no-ocr
```

### Example 3: Difficult Barcodes

```bash
# Use aggressive mode for hard-to-read barcodes
python -m confluence_uploader.cli \
  --src ~/Desktop/difficult_images \
  --page-id 987654321 \
  --aggressive
```

---

## ❓ FAQ

### Q: Do I need to setup credentials every time?

**A:** No! Setup is only needed once. After that, credentials are saved in `env.local` and used automatically.

### Q: Can multiple people use the same installation?

**A:** No. Each person should have their own copy with their own credentials. Virtual environments and credentials are user-specific.

### Q: What happens if I run it twice on the same images?

**A:** The tool checks for duplicate barcodes on the page and skips them. Only new barcodes are added.

### Q: Can I use this on Windows?

**A:** Yes, but you'll need to set up manually (setup.sh is for macOS/Linux). Follow the manual setup instructions in the README.

### Q: How do I update my credentials?

**A:** Edit the `env.local` file directly, or delete it and run `./setup.sh` again.

### Q: Where do the uploaded images appear?

**A:** Images are attached to the Confluence page you specified, and a table is added/updated with the barcode information.

---

## 🎯 Best Practices

✅ **Always do a dry-run first** to preview what will be uploaded  
✅ **Use descriptive filenames** for your images (they become attachment names)  
✅ **Keep your API token secret** - never share or commit `env.local`  
✅ **Use --no-lookup flags** if you only need barcodes (faster)  
✅ **Check for duplicates** before uploading large batches  
✅ **Use ZIP files** for large image sets (easier to manage)  

---

## 📞 Need Help?

If you run into issues:

1. Check the **Troubleshooting** section above
2. Read the detailed `README.md` in the project folder
3. Try running `./setup.sh` again to reset
4. Contact your team's tool administrator

> 💡 **Quick Reference:** Keep this page bookmarked for easy access to commands and troubleshooting!

---

**Last Updated:** November 2025  
**Tool Version:** 2.0 (Unified Detection Engine)

