#!/bin/bash
# Setup script for Confluence Barcode Uploader
# This script automates the setup process for new users

set -e  # Exit on error

echo "=========================================="
echo "Confluence Barcode Uploader - Setup"
echo "=========================================="
echo ""

# Check Python version
echo "Checking Python version..."
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || [ "$PYTHON_MINOR" -lt 8 ]; then
    echo "❌ Error: Python 3.8 or higher is required (found $PYTHON_VERSION)"
    echo "Please install a newer Python version:"
    echo "  macOS: brew install python@3.11"
    echo "  Ubuntu: sudo apt-get install python3.11"
    exit 1
fi
echo "✓ Python $PYTHON_VERSION found"
echo ""

# Check for zbar
echo "Checking for zbar library..."
if [ "$(uname)" == "Darwin" ]; then
    # macOS
    if ! brew list zbar &>/dev/null; then
        echo "⚠️  zbar not found. Installing via Homebrew..."
        brew install zbar
    else
        echo "✓ zbar is installed"
    fi
elif [ -f /etc/debian_version ]; then
    # Debian/Ubuntu
    if ! dpkg -l | grep -q libzbar0; then
        echo "⚠️  zbar not found. Installing..."
        sudo apt-get update
        sudo apt-get install -y libzbar0
    else
        echo "✓ libzbar0 is installed"
    fi
else
    echo "⚠️  Unable to auto-install zbar on this platform"
    echo "Please install zbar manually:"
    echo "  Windows: choco install zbar"
    echo "  Or see: https://github.com/NaturalHistoryMuseum/pyzbar#installation"
fi
echo ""

# Remove old virtual environment if it exists
if [ -d ".venv" ]; then
    echo "Removing old virtual environment..."
    rm -rf .venv
    echo "✓ Old .venv removed"
fi
echo ""

# Create new virtual environment
echo "Creating fresh virtual environment..."
python3 -m venv .venv
echo "✓ Virtual environment created"
echo ""

# Activate virtual environment
echo "Activating virtual environment..."
source .venv/bin/activate
echo "✓ Virtual environment activated"
echo ""

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip --quiet
echo "✓ pip upgraded"
echo ""

# Install dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt
echo "✓ All dependencies installed"
echo ""

# Configure venv to automatically set DYLD_LIBRARY_PATH on activation
echo "Configuring virtual environment for automatic library path setup..."
ACTIVATE_SCRIPT=".venv/bin/activate"
if [ -f "$ACTIVATE_SCRIPT" ]; then
    # Add library path export to activation script if not already present
    if ! grep -q "DYLD_LIBRARY_PATH" "$ACTIVATE_SCRIPT"; then
        cat >> "$ACTIVATE_SCRIPT" << 'EOF'

# Auto-configure library path for pyzbar (Code128 detection)
if [ "$(uname)" = "Darwin" ]; then
    export DYLD_LIBRARY_PATH=$(brew --prefix)/lib:$DYLD_LIBRARY_PATH
fi
EOF
        echo "✓ Virtual environment configured for automatic library path setup"
    fi
fi
echo ""

# Verify installation (test zxing-cpp only, skip pyzbar which can have linking issues)
echo "Verifying installation..."
if python -c "import zxingcpp; import pillow_heif; print('OK')" >/dev/null 2>&1; then
    echo "✓ Core libraries installed successfully!"
else
    echo "❌ Installation verification failed"
    echo "Please check the error messages above."
    exit 1
fi
echo ""

echo "=========================================="
echo "✅ Setup Complete!"
echo "=========================================="
echo ""

# Auto-detect if credentials belong to current user
current_user=$(whoami)
needs_config=false

if [ -f "env.local" ]; then
    # Check if the username marker exists
    existing_user=$(grep "^# CONFIGURED_FOR_USER=" env.local 2>/dev/null | cut -d'=' -f2)
    existing_email=$(grep "^CONFLUENCE_EMAIL=" env.local 2>/dev/null | cut -d'=' -f2)
    
    if [ -n "$existing_user" ] && [ "$existing_user" = "$current_user" ]; then
        # Same user, credentials already configured
        echo "✓ Using your existing Confluence credentials ($existing_email)"
        echo ""
    else
        # Different user or no user marker - needs reconfiguration
        if [ -n "$existing_email" ]; then
            echo "⚠️  WARNING: Detected credentials from a different user!"
            echo ""
            echo "Previous user: ${existing_user:-unknown}"
            echo "Previous email: $existing_email"
            echo "Current user: $current_user"
            echo ""
            echo "🗑️  Auto-removing old credentials..."
            rm env.local
            echo "✓ Old credentials deleted"
            echo ""
        fi
        needs_config=true
    fi
else
    needs_config=true
fi

# Setup credentials if needed
if [ "$needs_config" = true ]; then
    echo "📝 Setting up YOUR Confluence credentials..."
    echo "(You can skip this and configure manually later)"
    echo ""
    
    read -p "Configure credentials now? (y/n): " configure_now
    
    if [ "$configure_now" = "y" ] || [ "$configure_now" = "Y" ]; then
        echo ""
        echo "Enter your Confluence credentials:"
        echo ""
        
        # Confluence URL
        read -p "Confluence URL [https://instacart.atlassian.net/wiki]: " confluence_url
        confluence_url=${confluence_url:-https://instacart.atlassian.net/wiki}
        
        # Email
        read -p "Your Confluence email: " confluence_email
        
        # API Token
        echo ""
        echo "Get your API token from: https://id.atlassian.com/manage-profile/security/api-tokens"
        read -p "Your Confluence API token: " confluence_token
        
        # Create env.local with user marker
        cat > env.local << EOF
# Confluence Credentials - NEVER commit this file to git!
# CONFIGURED_FOR_USER=$current_user

CONFLUENCE_BASE_URL=$confluence_url
CONFLUENCE_EMAIL=$confluence_email
CONFLUENCE_API_TOKEN=$confluence_token

# Optional: API keys for enhanced lookups
# SERPAPI_KEY=your-serpapi-key
# CSE_KEY=your-google-cse-key
# CSE_CX=your-google-search-engine-id
EOF
        
        echo ""
        echo "✅ Credentials saved for user: $current_user"
        echo "⚠️  NEVER share or commit env.local - it contains your personal API token!"
    else
        echo ""
        echo "Skipped. To configure later:"
        echo "  1. Copy the example: cp env.local.example env.local"
        echo "  2. Edit env.local with YOUR credentials"
    fi
    echo ""
fi

echo "To use the tool:"
echo ""
echo "  source .venv/bin/activate"
echo "  python -m confluence_uploader.cli --src /path/to/images"
echo ""
echo "✓ Library paths are configured automatically on activation!"
echo ""
echo "See README.md for detailed usage instructions."

