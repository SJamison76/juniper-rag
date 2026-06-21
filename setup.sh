#!/bin/bash
# ── Juniper RAG Setup Script ──────────────────────────────────────────────────
# Sets up the Python virtual environment, installs dependencies,
# checks for Ollama, pulls required models, and indexes the books.
# ─────────────────────────────────────────────────────────────────────────────

set -e

VENV_DIR="./juniper-env"
BOOK_DIR="/srv/ftp/dayone"
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
echo "📚 Indexing Juniper Day One books into ChromaDB..."
echo "   This will take several minutes depending on book count."
echo ""
"$VENV_DIR/bin/python" index_books.py

echo ""
echo "============================================================"
echo " ✅ Setup complete! You can now query the books:"
echo "   $VENV_DIR/bin/python ask_books.py 'your question here'"
echo "============================================================"
echo ""
