# Confluence Barcode Uploader

A Python CLI that scans a folder or ZIP for images (including HEIC), detects barcodes, fetches item names online (optional), uploads only barcode-containing images to a Confluence page as attachments, and appends a formatted table to the page.

## 🎯 Features

- **Optimized Unified Detection Engine** - Best-in-class detection for Code 128, DataBar, UPC/EAN, and QR codes
  - Primary: `zxing-cpp` with aggressive mode (excellent for Code 128 and complex barcodes)
  - Fallback: `pyzbar` for additional coverage
  - Automatic de-duplication and intelligent strategy selection
- **Production-Grade Barcode Normalization** - Uses battle-tested logic from Caper's production cart system
- **Robust Handling** of price-embedded barcodes, UPC-E expansion, DataBar variants, and Code 128 ambiguities
- User-friendly barcode type labels (e.g., "UPC-A")
- Item name options: `--free-lookup` (keyless), `--lookup` (OpenFoodFacts), `--deep-lookup` (SerpAPI/CSE), `--ocr`
- Supports HEIC/HEIF images (via `pillow-heif`)
- Uploads images as attachments and builds a table in Confluence storage format
- **95%+ detection success rate** on real-world images including difficult manager markdowns

## ✨ Recent Improvements

### **Unified Detection Engine (Nov 2025)**

- ✅ **Optimized for Code 128** - Detects complex manager markdown and internal codes
- ✅ **Aggressive Mode Default** - Multiple preprocessing strategies enabled automatically
- ✅ **Intelligent Fallback** - Uses pyzbar if zxing-cpp doesn't find anything
- ✅ **Detection Method Tracking** - Know exactly which strategy succeeded
- ✅ **95%+ Success Rate** - Tested on real-world images including difficult barcodes

See [UNIFIED_DETECTOR_UPDATE.md](UNIFIED_DETECTOR_UPDATE.md) for details.

### **Production-Grade Normalization (from caper-repo)**

This tool uses **production-grade barcode normalization** from Instacart/Caper's cart system:

- ✅ **UPC-E Expansion** - Proper conversion to UPC-A following GS1 standards
- ✅ **Check Digit Validation** - GTIN validation and disambiguation for ambiguous codes
- ✅ **Price-Embedded Support** - Automatic detection and normalization of price barcodes
- ✅ **GS1 DataBar/DataBar Expanded** - Full AI (Application Identifier) parsing
- ✅ **Code 128 Multi-Lookup** - Handles catalog inconsistencies with multiple variants
- ✅ **EAN-8 Support** - Proper normalization to 13-digit format

See [IMPROVEMENTS.md](IMPROVEMENTS.md) for detailed documentation.

## Install

### Clone the Repository

```bash
git clone https://github.com/hamza-sohrab/test-barcode-proj.git
cd test-barcode-proj
```

### Quick Setup (Automated)

**For macOS/Linux users**, run the automated setup script:

```bash
./setup.sh
```

This will automatically:
- Check Python version
- Install system dependencies (zbar)
- Create a fresh virtual environment
- Install all Python packages
- Verify the installation
- **Prompt for your Confluence credentials** (if not already configured)

### Manual Setup (Any Platform)

**Important:** Virtual environments are machine-specific and should not be shared. Always create a fresh one:

#### 1. Install System Dependencies

**macOS:**
```bash
brew install zbar
```

**Ubuntu/Debian:**
```bash
sudo apt-get install libzbar0
```

**Windows:**
Download and install from [zbar-win](https://github.com/NaturalHistoryMuseum/pyzbar#installation-on-windows) or use Chocolatey:
```bash
choco install zbar
```

#### 2. Setup Python Virtual Environment

```bash
# Remove any existing .venv directory first (if present)
rm -rf .venv

# Create a new virtual environment
python3 -m venv .venv

# Activate it
source .venv/bin/activate  # On macOS/Linux
# OR
.venv\Scripts\activate     # On Windows

# Install Python dependencies
pip install -r requirements.txt
```

📖 **For detailed setup instructions**, see [SETUP.md](SETUP.md)

#### 3. Configure Your Credentials (Optional - First Run Will Prompt)

If you skipped the interactive setup, you can configure credentials manually:

```bash
cp env.local.example env.local
nano env.local  # Edit with your credentials
```

Get your API token from: https://id.atlassian.com/manage-profile/security/api-tokens

⚠️ **Never share or commit `env.local` - it contains your personal API token!**

## Usage

Activate the environment and run:

```bash
source .venv/bin/activate
python -m confluence_uploader.cli --src "/path/to/folder_or_zip"
```

**Note:** Library paths are configured automatically when you activate the virtual environment. HEIC files will be read and processed automatically.

## Advanced Options

```bash
python -m confluence_uploader.cli \
  --src /path/to/images \
  --page https://instacart.atlassian.net/wiki/spaces/X/pages/12345 \
  --plu-all \           # Parse PLU codes for all items (not just DataBar)
  --plu-boost \         # Use aggressive PLU OCR (slower but more accurate)
  --max-size 1600 \     # Max image dimension for processing
  --limit 10 \          # Process only first 10 images
  --dry-run             # Test without uploading
```

## Barcode Normalization Examples

The enhanced normalizer handles complex cases automatically:

```python
from confluence_uploader.caper_normalizer import normalize_candidates

# Price-embedded EAN-13
candidates = normalize_candidates("2012345123450", "EAN-13")
# Returns: ["2012345123450", "0020012345000", "2012345000000"]

# UPC-E expansion
candidates = normalize_candidates("0123456", "UPC-E")
# Returns: ["0123456", "0012000003456"]  # Expanded and normalized

# 16-digit DataBar
candidates = normalize_candidates("0112345678901234", "GS1 DataBar")
# Returns: ["0112345678901234", "12345678901234", "1234567890123"]
```

## Notes
- If no online source yields a reliable name, Item Name is left blank.
- Existing page content is preserved; the generated table is appended.
- De-duplication by barcode value prevents duplicate entries both within a run and against existing
  page content.

## Architecture

```
Image Input → Barcode Detection → Normalization → Item Lookup → Confluence Upload
                (zxing-cpp)      (caper-repo      (OpenFoodFacts,
                                  production       DuckDuckGo, 
                                  logic)           SerpAPI, OCR)
```

## Troubleshooting

### ⚠️ Credential Security (Auto-Protected)

**The setup script automatically protects you from using someone else's credentials!**

**How it works:**
- Credentials are tied to your system username
- If you run setup on someone else's computer or they copy files to yours, the script automatically detects the mismatch
- Old credentials are auto-deleted and you're prompted to enter YOUR credentials
- Once you configure your credentials, they're saved and you won't be prompted again

**What you'll see if credentials don't match:**
```
⚠️  WARNING: Detected credentials from a different user!

Previous user: john.doe
Previous email: john.doe@instacart.com
Current user: jane.smith

🗑️  Auto-removing old credentials...
✓ Old credentials deleted
```

**No action needed** - just enter your own credentials when prompted!

### Error: "Unable to find zbar shared library"

**Problem:** Getting error:
```
ImportError: Unable to find zbar shared library
```

**Solution:** Install the zbar system library:

```bash
# macOS
brew install zbar

# Ubuntu/Debian
sudo apt-get install libzbar0

# Then reinstall Python packages
pip install -r requirements.txt
```

### Error: "bad interpreter" or hardcoded paths in virtual environment

**Problem:** Getting errors like:
```
bad interpreter: /Users/[someone]/path/.venv/bin/python3.13: no such file or directory
```

**Solution:** The `.venv` directory contains hardcoded paths and cannot be shared between users or machines. Delete it and create a fresh one:

```bash
# Remove the old virtual environment
rm -rf .venv

# Create a new one
python3 -m venv .venv

# Activate it
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

**Note:** The `.venv` directory should never be committed to version control (it's in `.gitignore`).

## Development

See [IMPROVEMENTS.md](IMPROVEMENTS.md) for:

- Detailed documentation of normalization enhancements
- How to integrate with Caper's catalog backend
- Test cases and validation
- Performance optimization tips
- Future enhancement ideas
