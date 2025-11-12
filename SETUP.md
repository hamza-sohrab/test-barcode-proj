# Setup Guide for New Users

This guide will help you set up the Confluence Barcode Uploader on your machine from scratch.

## Prerequisites

- Python 3.8 or higher
- Homebrew (macOS) or apt (Linux) or Chocolatey (Windows)
- Git (to clone/pull the repository)

## Step-by-Step Setup

### 1. Install System Dependencies

The tool requires `zbar`, a barcode scanning library that must be installed at the system level.

**macOS:**
```bash
brew install zbar
```

**Ubuntu/Debian Linux:**
```bash
sudo apt-get update
sudo apt-get install libzbar0
```

**Windows:**
```bash
# Using Chocolatey
choco install zbar

# Or download from: https://github.com/NaturalHistoryMuseum/pyzbar#installation-on-windows
```

### 2. Navigate to Project Directory

```bash
cd /path/to/test_barcodes_proj
```

### 3. Remove Old Virtual Environment (if present)

If you received this project from another user or are setting up on a new machine, you **must** remove any existing `.venv` directory:

```bash
# This is important! Old .venv contains hardcoded paths
rm -rf .venv
```

### 4. Create Fresh Virtual Environment

```bash
python3 -m venv .venv
```

### 5. Activate Virtual Environment

**macOS/Linux:**
```bash
source .venv/bin/activate
```

**Windows (PowerShell):**
```bash
.venv\Scripts\Activate.ps1
```

**Windows (CMD):**
```bash
.venv\Scripts\activate.bat
```

You should see `(.venv)` appear at the beginning of your terminal prompt.

### 6. Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

This will install all required Python packages including:
- zxing-cpp (barcode detection)
- pyzbar (barcode detection fallback)
- Pillow (image processing)
- pillow-heif (HEIC support)
- requests (API calls)
- opencv-python (image preprocessing)

### 7. Verify Installation

Run a quick test to ensure everything is working:

```bash
python -c "from confluence_uploader.unified_barcode_detector import detect_barcodes_best; print('✓ Setup successful!')"
```

If you see `✓ Setup successful!`, you're ready to go!

## Common Setup Issues

### Issue: "Unable to find zbar shared library"

**Cause:** The zbar system library is not installed.

**Solution:** Install zbar using the commands in Step 1 above, then run `pip install -r requirements.txt` again.

### Issue: "bad interpreter" error

**Cause:** You're trying to use a virtual environment created on another machine or by another user.

**Solution:** Delete the `.venv` directory and recreate it (Steps 3-6 above).

### Issue: Python version too old

**Cause:** Some dependencies require Python 3.8+.

**Solution:** Install a newer Python version:
```bash
# macOS
brew install python@3.11

# Ubuntu/Debian
sudo apt-get install python3.11
```

Then recreate your virtual environment using the newer Python:
```bash
python3.11 -m venv .venv
```

## Environment Configuration

### Optional: Confluence Credentials

If you're uploading to Confluence, create an `env.local` file:

```bash
CONFLUENCE_URL=https://your-domain.atlassian.net
CONFLUENCE_USER=your.email@example.com
CONFLUENCE_TOKEN=your-api-token
```

Get your API token from: https://id.atlassian.com/manage-profile/security/api-tokens

### Optional: Lookup API Keys

For enhanced item name lookups, add to `env.local`:

```bash
SERPAPI_KEY=your-serpapi-key
CSE_KEY=your-google-cse-key
CSE_CX=your-google-search-engine-id
```

## Next Steps

Once setup is complete, see:
- [README.md](README.md) - Usage instructions and features
- [QUICKSTART.md](QUICKSTART.md) - Quick start guide with examples
- [IMPROVEMENTS.md](IMPROVEMENTS.md) - Detailed documentation

## Testing Your Setup

Try a dry-run on a test folder:

```bash
python -m confluence_uploader.cli \
  --src /path/to/test/images \
  --dry-run
```

This will detect barcodes and show what would be uploaded without actually uploading anything.

## Getting Help

If you encounter issues not covered here:
1. Check the Troubleshooting section in [README.md](README.md)
2. Verify all system dependencies are installed
3. Ensure your virtual environment is activated (`(.venv)` in prompt)
4. Try recreating the virtual environment from scratch

---

**Important:** Never commit the `.venv` directory to version control! It contains machine-specific paths and will not work on other machines.

