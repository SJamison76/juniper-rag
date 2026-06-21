# Juniper Day One - Ask Books

A local system for querying Juniper Day One books using natural language. Ask questions about Junos OS configuration and get answers with actual CLI commands and config examples pulled directly from the books.

---

## How It Works

1. PDF books are chunked and embedded into a local ChromaDB vector database using
   the all-minilm embedding model running in Ollama.

2. When you ask a question, the query is embedded and used to find the most
   semantically relevant chunks from the books.

3. The relevant chunks are passed as context to Claude (claude-sonnet-4-6) via the
   Anthropic API, which generates a focused answer with actual Junos CLI commands.

Embeddings and retrieval run locally. Answer generation requires an internet connection
to reach the Anthropic API. Your PDF content is sent to Anthropic only as part of the
query context.

---

## Requirements

- Ubuntu 22.04 or later (tested on Ubuntu 26.04 LTS, kernel 7.0)
- Python 3.10 or later
- Ollama 0.30.9 or later (for embeddings only)
- 16GB RAM minimum (32GB recommended)
- Juniper Day One PDF books placed in /srv/ftp/dayone
- Anthropic API key (see API Key Setup below)

---

## API Key Setup

Answer generation uses the Anthropic API. You need an API key from console.anthropic.com.

The key is loaded from your shell environment. Add it to ~/.bashrc so it is available
at every login:

    echo "export ANTHROPIC_API_KEY='sk-ant-...'" >> ~/.bashrc
    source ~/.bashrc

Never hardcode the key in any script or commit it to git. The .gitignore already
excludes .env files if you prefer to store the key there instead.

Note: The Anthropic API is a separate paid service from a Claude.ai subscription.
Costs are minimal for this use case (approximately $0.007 per query with Sonnet 4.6).

---

## Setup

Place your Juniper Day One PDF books in /srv/ftp/dayone, then run:

    chmod +x setup.sh
    ./setup.sh

This will:
- Create a Python virtual environment
- Install all dependencies including the Anthropic SDK
- Pull the all-minilm embedding model via Ollama
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

Example output:

    $ python ask_books.py "show me a complete EBGP configuration with authentication and route policy on Junos"
    ============================================================
    ANSWER:
    ============================================================
    Here is the complete EBGP configuration with authentication and route policy:

    set protocols bgp group EBGP type external
    set protocols bgp group EBGP peer-as 65001
    set protocols bgp group EBGP neighbor 10.0.0.1
    set protocols bgp group EBGP authentication key "my_secret_key"
    set protocols bgp group EBGP authentication algorithm md5
    set policy-options policy-statement send-direct term 1 from protocol direct
    set policy-options policy-statement send-direct term 1 then accept

    Explanation:

    set protocols bgp group EBGP type external
      Sets up an External BGP peer group called EBGP. The type external keyword
      specifies this is an EBGP peer, as opposed to an IBGP peer.

    set protocols bgp group EBGP peer-as 65001
      Sets the Autonomous System Number for the EBGP peer group. Replace with
      your actual peer ASN.

    set protocols bgp group EBGP neighbor 10.0.0.1
      Specifies the IP address of the neighboring router. Replace with the actual
      IP address of your BGP neighbor.

    set protocols bgp group EBGP authentication key "my_secret_key"
      Sets the authentication key for the peer group. Replace with a strong,
      unique password that meets your organization's security policy.

    set protocols bgp group EBGP authentication algorithm md5
      Specifies MD5 as the authentication algorithm for the peer group.

    set policy-options policy-statement send-direct term 1 from protocol direct
      Creates a policy statement called send-direct that matches routes learned
      directly (not through an intermediate router).

    set policy-options policy-statement send-direct term 1 then accept
      Accepts routes that match the criteria in the previous line.

    ============================================================
    SOURCES:
      EX_Series_UpRunning.pdf — p.177
      junos-beginners-guide.pdf — p.9
      ExploreJunosCLI_2ndEd.pdf — p.80
      TW_HardeningJunosDevices_2ndEd.pdf — p.96, p.151
      TW_HardeningJunosDevices_2ndEd_Checklist.pdf — p.1
    ============================================================

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
- TOP_K          Number of chunks to keep after filtering (default 6)
- FETCH_K        Number of candidates to fetch before filtering (default 12)
- MAX_CONTEXT    Max characters of context sent to Claude (default 7000)
- MIN_RELEVANCE  L2 distance threshold, lower is stricter (default 1.2)
- CLAUDE_MODEL   Anthropic model to use (default claude-sonnet-4-6)

---

## Models Used

- all-minilm         Embedding model, runs locally via Ollama, fast on CPU
- claude-sonnet-4-6  Language model for answer generation, via Anthropic API

---

## Tested On

- Hardware:  AMD Ryzen 7, 32GB RAM
- OS:        Ubuntu 26.04 LTS, kernel 7.0.0-22-generic
- Ollama:    0.30.9
- ChromaDB:  1.5.9
