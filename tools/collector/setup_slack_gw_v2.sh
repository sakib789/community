#!/bin/bash
# Quick installation script for Slack Gateway v2
# For Amazon Linux

set -e  # Exit on any error

echo "================================================"
echo "   Slack Gateway v2 - Quick Installation"
echo "================================================"
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo -e "${YELLOW}📍 Working directory: $SCRIPT_DIR${NC}"
echo ""

# Step 1: Verify Python
echo "🔍 Checking Python 3..."
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3 is not installed${NC}"
    echo "Install with: sudo yum install python3 -y"
    exit 1
fi

PYTHON_VERSION=$(python3 --version)
echo -e "${GREEN}✅ $PYTHON_VERSION found${NC}"
echo ""

# Step 2: Create virtual environment
echo "📦 Creating virtual environment..."
if [ -d "venv" ]; then
    echo -e "${YELLOW}⚠️  Virtual environment already exists${NC}"
    read -p "Do you want to recreate it? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf venv
        python3 -m venv venv
        echo -e "${GREEN}✅ Virtual environment recreated${NC}"
    else
        echo "Using existing virtual environment"
    fi
else
    python3 -m venv venv
    echo -e "${GREEN}✅ Virtual environment created${NC}"
fi
echo ""

# Step 3: Activate virtual environment and install dependencies
echo "📥 Installing dependencies..."
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt
echo -e "${GREEN}✅ Dependencies installed${NC}"
echo ""

# Step 4: Verify token files
echo "🔑 Checking token files..."
MISSING_TOKENS=0

if [ ! -f ".token_slack" ]; then
    echo -e "${RED}❌ Missing .token_slack${NC}"
    MISSING_TOKENS=1
fi

if [ ! -f ".token_slack_app" ]; then
    echo -e "${RED}❌ Missing .token_slack_app${NC}"
    MISSING_TOKENS=1
fi

if [ ! -f ".token_github" ]; then
    echo -e "${RED}❌ Missing .token_github${NC}"
    MISSING_TOKENS=1
fi

if [ $MISSING_TOKENS -eq 1 ]; then
    echo ""
    echo -e "${YELLOW}⚠️  You need to create the token files${NC}"
    echo "See README_slack_gw_v2.md for instructions"
    echo ""
    echo "Quick commands:"
    echo "  nano .token_slack       # Paste Bot Token (xoxb-...)"
    echo "  nano .token_slack_app   # Paste App Token (xapp-...)"
    echo "  nano .token_github      # Paste GitHub Token (ghp_...)"
    echo "  chmod 600 .token_*"
else
    echo -e "${GREEN}✅ All token files exist${NC}"
    
    # Verify permissions
    chmod 600 .token_slack .token_slack_app .token_github 2>/dev/null || true
    echo -e "${GREEN}✅ Token permissions configured${NC}"
fi
echo ""

# Step 5: Verify repository configuration
echo "🔧 Checking configuration..."
GITHUB_REPO=$(grep "^GITHUB_REPO = " slack_gw_v2.py | cut -d'"' -f2)
echo "Configured repository: $GITHUB_REPO"

if [ "$GITHUB_REPO" = "snaow/community-dev" ]; then
    echo -e "${YELLOW}⚠️  Using example repository. Edit slack_gw_v2.py line 23${NC}"
fi
echo ""

# Summary
echo "================================================"
echo "   ✅ Installation completed"
echo "================================================"
echo ""
echo "Next steps:"
echo ""

if [ $MISSING_TOKENS -eq 1 ]; then
    echo "1. Create token files (see above)"
    echo "2. Activate environment: source venv/bin/activate"
    echo "3. Run: python3 slack_gw_v2.py"
else
    echo "1. Activate environment: source venv/bin/activate"
    echo "2. Run: python3 slack_gw_v2.py"
fi
echo ""
echo "For more information: cat README_slack_gw_v2.md"
echo ""
