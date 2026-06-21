#!/bin/bash
# ── Juniper RAG Setup Script ──────────────────────────────────────────────────
# Sets up the Python virtual environment, installs dependencies,
# checks for Ollama, pulls required models, and indexes the books.
# ─────────────────────────────────────────────────────────────────────────────

set -e

VENV_DIR="./juniper-env"
BOOK_DIR="/srv/ftp/dayone"
STIG_DIR="/srv/ftp/stigs"
EMBED_MODEL="all-minilm"

echo ""
echo "============================================================"
echo " Juniper Day One RAG Setup"
echo "============================================================"
echo ""

# ── Check Python ──────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "❌ Python3 not found. Install it with: sudo apt install python3 python3-venv"
    exit 1
fi
echo "✅ Python3 found: $(python3 --version)"

# ── Check Ollama ──────────────────────────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
    echo ""
    echo "❌ Ollama not found. Install it first:"
    echo "   curl -fsSL https://ollama.com/install.sh | sh"
    echo "   Then re-run this script."
    exit 1
fi
echo "✅ Ollama found: $(ollama --version)"

# ── Check book directory ──────────────────────────────────────────────────────
if [ ! -d "$BOOK_DIR" ]; then
    echo ""
    echo "⚠️  Book directory not found at $BOOK_DIR"
    echo "   Create it and place your Juniper Day One PDF books there:"
    echo "   sudo mkdir -p $BOOK_DIR"
    echo "   Then re-run this script."
    exit 1
fi

PDF_COUNT=$(find "$BOOK_DIR" -name "*.pdf" | wc -l)
if [ "$PDF_COUNT" -eq 0 ]; then
    echo ""
    echo "⚠️  No PDF files found in $BOOK_DIR"
    echo "   Download your Juniper Day One books and place them there."
    exit 1
fi
echo "✅ Found $PDF_COUNT PDF(s) in $BOOK_DIR"

# ── Check STIG directory ──────────────────────────────────────────────────────
if [ ! -d "$STIG_DIR" ]; then
    echo ""
    echo "⚠️  STIG directory not found at $STIG_DIR"
    echo "   Create it and place DISA STIG XML files there:"
    echo "   sudo mkdir -p $STIG_DIR"
    echo "   Download STIGs from: https://public.cyber.mil/stigs/downloads/"
    echo "   STIG indexing is optional — skipping for now."
else
    STIG_COUNT=$(find "$STIG_DIR" -name "*.xml" | wc -l)
    if [ "$STIG_COUNT" -eq 0 ]; then
        echo "⚠️  No STIG XML files found in $STIG_DIR — skipping STIG indexing."
        echo "   Download STIGs from: https://public.cyber.mil/stigs/downloads/"
    else
        echo "✅ Found $STIG_COUNT STIG XML file(s) in $STIG_DIR"
    fi
fi

# ── Create virtual environment ────────────────────────────────────────────────
echo ""
echo "🔧 Creating Python virtual environment at $VENV_DIR ..."
python3 -m venv "$VENV_DIR"
echo "✅ Virtual environment created."

# ── Install dependencies ──────────────────────────────────────────────────────
echo ""
echo "📦 Installing Python dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install -r requirements.txt --quiet
echo "✅ Dependencies installed."

# ── Pull Ollama embedding model ───────────────────────────────────────────────
echo ""
echo "🤖 Pulling Ollama embedding model..."
ollama pull "$EMBED_MODEL"
echo "✅ Embedding model ready."

# ── Check Anthropic API key ───────────────────────────────────────────────────
echo ""
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "⚠️  ANTHROPIC_API_KEY is not set."
    echo "   Answer generation requires an Anthropic API key."
    echo "   Get one at: https://console.anthropic.com"
    echo ""
    echo "   Add it to your shell so it is available at every login:"
    echo "   echo \"export ANTHROPIC_API_KEY='sk-ant-...'\" >> ~/.bashrc"
    echo "   source ~/.bashrc"
    echo ""
    echo "   Then re-run this script, or just start querying if books are indexed."
else
    echo "✅ ANTHROPIC_API_KEY is set."
fi

# ── Index books ───────────────────────────────────────────────────────────────
echo ""
echo "📚 Indexing Juniper Day One books into ChromaDB..."
echo "   Using PyMuPDF for accurate text extraction with preserved formatting."
echo "   This will take several minutes depending on book count."
echo ""
"$VENV_DIR/bin/python" index_books.py

# ── Index STIGs if available ──────────────────────────────────────────────────
if [ -d "$STIG_DIR" ]; then
    STIG_COUNT=$(find "$STIG_DIR" -name "*.xml" | wc -l)
    if [ "$STIG_COUNT" -gt 0 ]; then
        echo ""
        echo "📋 Indexing DISA STIG XML files..."
        echo "   Already indexed files will be skipped."
        echo ""
        "$VENV_DIR/bin/python" index_stigs.py
    fi
fi

echo ""
echo "============================================================"
echo " ✅ Setup complete!"
echo ""
echo " Launch the menu:"
echo "   $VENV_DIR/bin/python start.py"
echo ""
echo " Or run scripts directly:"
echo "   $VENV_DIR/bin/python ask_books.py"
echo "   $VENV_DIR/bin/python critique_config.py config.txt"
echo "   $VENV_DIR/bin/python stig_audit.py config.txt"
echo "   $VENV_DIR/bin/python do_configure.py 192.168.1.1 'harden this switch'"
echo "============================================================"
echo ""
