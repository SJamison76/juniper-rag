#!/bin/bash
# ── Juniper RAG Setup Script ──────────────────────────────────────────────────
# Sets up the Python virtual environment, installs dependencies,
# checks for Ollama, pulls required models, and indexes the books.
# ─────────────────────────────────────────────────────────────────────────────

set -e

VENV_DIR="./juniper-env"
BOOK_DIR="/srv/ftp/dayone"
OLLAMA_MODEL="llama3:8b"
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

# ── Pull Ollama models ────────────────────────────────────────────────────────
echo ""
echo "🤖 Pulling Ollama models (this may take a while)..."
ollama pull "$OLLAMA_MODEL"
ollama pull "$EMBED_MODEL"
echo "✅ Models ready."

# ── Performance warning ───────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo " ⚠️  PERFORMANCE NOTICE"
echo "============================================================"
echo " This system runs inference on CPU only by default."
echo " Expect 30-90 seconds per query on a modern CPU."
echo ""
echo " For fast responses you need one of the following:"
echo "   - A dedicated NVIDIA/AMD GPU with Ollama GPU support"
echo "   - An NPU or AI accelerator (Intel Arc, Hailo, etc.)"
echo "   - An Apple Silicon Mac (Metal acceleration via Ollama)"
echo ""
echo " Without GPU/NPU acceleration, the system is functional"
echo " but slow. Consider a smaller model for faster responses:"
echo "   ollama pull llama3.2:3b"
echo " Then update OLLAMA_MODEL in ask_books.py to llama3.2:3b"
echo "============================================================"
echo ""

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
