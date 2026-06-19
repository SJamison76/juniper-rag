# Juniper Day One RAG

A local Retrieval-Augmented Generation (RAG) system for querying Juniper Day One
books using natural language. Ask questions about Junos OS configuration and get
answers with actual CLI commands and config examples pulled directly from the books.

---

## How It Works

1. PDF books are chunked and embedded into a local ChromaDB vector database using
   the all-minilm embedding model running in Ollama.

2. When you ask a question, the query is embedded and used to find the most
   semantically relevant chunks from the books.

3. The relevant chunks are passed as context to llama3:8b running locally in Ollama,
   which generates a focused answer with actual Junos CLI commands.

Everything runs locally. No internet connection required after setup. No data leaves
the machine.

---

## Requirements

- Ubuntu 22.04 or later (tested on Ubuntu 26.04 LTS, kernel 7.0)
- Python 3.10 or later
- Ollama 0.30.9 or later
- 16GB RAM minimum (32GB recommended)
- Juniper Day One PDF books placed in /srv/ftp/dayone

---

## Performance Notice

This system runs on CPU by default. Expect 30 to 90 seconds per query on a
modern CPU without hardware acceleration.

For fast responses you need one of the following:

- A dedicated NVIDIA or AMD GPU with Ollama GPU support enabled
- An NPU or AI accelerator such as Intel Arc, Hailo, or similar
- An Apple Silicon Mac using Metal acceleration via Ollama

Without GPU or NPU acceleration the system is fully functional but slow.
For faster responses with slightly reduced quality, switch to a smaller model:

    ollama pull llama3.2:3b

Then update the model name in ask_books.py from llama3:8b to llama3.2:3b.

---

## Setup

Place your Juniper Day One PDF books in /srv/ftp/dayone, then run:

    chmod +x setup.sh
    ./setup.sh

This will:
- Create a Python virtual environment
- Install all dependencies
- Pull the required Ollama models (llama3:8b and all-minilm)
- Index all PDFs into the ChromaDB vector database

Indexing 30 books takes approximately 10 to 20 minutes. Progress is saved after
each book so if the process is interrupted it will resume where it left off.

---

## Usage

    ./juniper-env/bin/python ask_books.py "your question here"

Examples:

    ./juniper-env/bin/python ask_books.py "how do I configure a BGP neighbor?"
    ./juniper-env/bin/python ask_books.py "show me OSPF area configuration on Junos"
    ./juniper-env/bin/python ask_books.py "how do I configure EVPN VXLAN on an EX switch?"
    ./juniper-env/bin/python ask_books.py "what is the Junos command to check BGP neighbor state?"

---

## File Structure

    juniper-rag/
    |-- ask_books.py              Query the vector database and generate answers
    |-- index_books.py            Index PDF books into ChromaDB
    |-- requirements.txt          Python dependencies
    |-- setup.sh                  Automated setup script
    |-- .gitignore                Excludes venv, database, and PDFs from git
    |-- README.md                 This file
    |-- juniper-env/              Python virtual environment (not committed)
    |-- juniper_vector_db/        ChromaDB vector database (not committed)
    |-- juniper_index_checkpoint.json  Indexing progress tracker (not committed)

---

## Re-indexing

To re-index from scratch (for example after adding new books):

    rm -rf juniper_vector_db juniper_index_checkpoint.json
    ./juniper-env/bin/python index_books.py

To add new books without re-indexing existing ones, just place the new PDFs in
/srv/ftp/dayone and re-run index_books.py. Already indexed books will be skipped.

---

## Configuration

Key settings are at the top of each script:

index_books.py:
- BOOK_DIR       Path to PDF books (default /srv/ftp/dayone)
- DB_PATH        Path to ChromaDB database
- CHUNK_SIZE     Characters per chunk (default 1200)
- CHUNK_STEP     Step between chunks, controls overlap (default 900)

ask_books.py:
- TOP_K          Number of chunks to retrieve (default 6)
- MAX_CONTEXT    Max characters of context sent to LLM (default 7000)
- MIN_RELEVANCE  L2 distance threshold, lower is stricter (default 1.4)

---

## Models Used

- all-minilm    Embedding model, runs fast on CPU
- llama3:8b     Language model for answer generation, slow without GPU

---

## Tested On

- Hardware:  AMD Ryzen 7, 32GB RAM
- OS:        Ubuntu 26.04 LTS, kernel 7.0.0-22-generic
- Ollama:    0.30.9
- ChromaDB:  1.5.9
