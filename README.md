# Juniper Day One - Ask Books

A local RAG system for querying Juniper Day One books and DISA STIGs using natural
language. Ask questions about Junos OS, critique configs against best practices, run
DoD STIG compliance audits, and apply AI-generated configuration changes to live
devices — all from a simple menu.

---

## How It Works

1. PDF books and DISA STIG XML files are chunked and embedded into a local ChromaDB
   vector database using the all-minilm embedding model running in Ollama. PyMuPDF
   is used for text extraction to preserve whitespace, indentation, and Junos config
   block structure. Chunking is line-aware so set commands and config stanzas are
   never split mid-line.

2. When you ask a question, the query is embedded and used to find the most
   semantically relevant chunks from the books or STIG rules.

3. The relevant chunks are passed as context to Claude (claude-sonnet-4-6) via the
   Anthropic API, which generates a focused answer with actual Junos CLI commands.

Embeddings and retrieval run locally. Answer generation requires an internet connection
to reach the Anthropic API. Your PDF content and config data is sent to Anthropic only
as part of the query context. Prompt caching is used across all scripts to reduce API
costs on repeated queries.

---

## Requirements

- Ubuntu 22.04 or later (tested on Ubuntu 26.04 LTS, kernel 7.0)
- Python 3.10 or later
- Ollama 0.30.9 or later (for embeddings only)
- 16GB RAM minimum (32GB recommended)
- Juniper Day One PDF books placed in /srv/ftp/dayone
- DISA STIG XML files placed in /srv/ftp/stigs (optional, for STIG auditing)
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
Running a full 628-rule STIG audit is expensive. Use device type and severity filters
to reduce cost — an EX Switch high-severity only audit costs approximately $0.05.

---

## STIG Files

DISA STIG XML files are available free from:

    https://public.cyber.mil/stigs/downloads/

Search for Juniper. Place the extracted XML files anywhere under /srv/ftp/stigs.
The indexer scans all subdirectories automatically.

Create the directory and set permissions:

    sudo mkdir -p /srv/ftp/stigs
    sudo chown -R $USER:$USER /srv/ftp/stigs

---

## Setup

Place your Juniper Day One PDF books in /srv/ftp/dayone, then run:

    chmod +x setup.sh
    ./setup.sh

This will:
- Create a Python virtual environment
- Install all dependencies including the Anthropic SDK, PyMuPDF, PyEZ, and paramiko
- Pull the all-minilm embedding model via Ollama
- Index all PDFs into the ChromaDB vector database
- Index any STIG XML files found in /srv/ftp/stigs (if present)

Indexing 36 books takes approximately 10 to 20 minutes. Progress is saved after
each book so if the process is interrupted it will resume where it left off.

---

## Usage: start.py (recommended)

The easiest way to use the system. Presents a numbered menu and manages report
folders automatically.

    ./juniper-env/bin/python start.py

The menu shows your three most recent report folders at the top so you can see
what was last run and what outputs were generated.

Menu options:

    ── Query & Audit ─────────────────────────────────────
    1. Ask a question about Junos (interactive chat)
    2. Ask a single question about Junos
    3. Critique a config file against Day One books
    4. Run a DoD STIG audit on a config file
    5. Critique + STIG audit (both, one config pull)

    ── Configure Devices ─────────────────────────────────
    6. Configure a live device (do_configure.py)

    ── Indexing & Maintenance ────────────────────────────
    7. Reindex Day One books (full rebuild)
    8. Index new STIG files (skips already indexed)
    9. Reindex ALL STIG files (full rebuild)

    0. Exit

Options 3, 4, and 5 ask how you want to provide the config:

    1. Pull from a live device (SSH) — connects, pulls config, saves to report folder
    2. Use a config file from a previous report
    3. Use a config file from this directory

---

## Report Folders

Every audit run creates a timestamped folder under reports/ containing all output
files for that run. Nothing is scattered across the project directory.

    reports/
    └── 20260621_143022_192_168_10_203/
        ├── config.txt               raw device config (pulled via SSH or copied)
        ├── critique.txt             Day One book critique with issues and fix commands
        ├── stig_audit.txt           full PASS/FAIL report for every STIG rule
        ├── stig_remediation.txt     set/delete commands for all failures
        ├── stig_audit.ckl           legacy STIG Viewer checklist (V2 format)
        ├── stig_audit.cklb          raw CKLB generated by audit (structural only)
        └── stig_results_ex.cklb     STIG Viewer 3.x checklist with results populated

The stig_results_ex.cklb (or srx/router) is the file to open in STIG Viewer 3.x.
It is automatically generated after every STIG audit by merging results into the
blank STIG Viewer template for that device type.

The report folder name includes the date, time, and device IP so you can identify
runs at a glance. The reports/ directory is excluded from git via .gitignore.

---

## STIG Audit Cost Control

The STIG database contains 628 rules across 13 files covering EX switches, SRX
gateways, routers, VPN, and IDPS. Running all rules against a device is slow and
expensive. Always use the device type and severity filters.

When running a STIG audit the menu asks two questions:

    What device type is this?
      1. EX Switch        (NDM + L2S + RTR — ~182 rules)
      2. SRX Gateway      (NDM + ALG + VPN + IDPS — ~149 rules)
      3. Router           (NDM + RTR — ~145 rules)
      4. All rules        (628 rules — slowest, most expensive)

    Filter by severity?
      1. High only   (CAT I — recommended for quick audits)
      2. Medium only (CAT II)
      3. Low only    (CAT III)
      4. All severities

Recommended for day-to-day use: EX Switch + High only = approximately 25 rules,
5 API batches, cost under $0.10. Full 628-rule audit = 126 batches, cost $1.50+.

---

## STIG Viewer

After a STIG audit completes, a populated .cklb checklist is automatically created
in the report folder and is ready to open in DISA STIG Viewer 3.x.

Download STIG Viewer 3.x free from:

    https://public.cyber.mil/stigs/srg-stig-tools/

Workflow in STIG Viewer 3.7:

1. Load the STIG benchmarks — STIG Explorer → Open STIG → select the XML files
   from /srv/ftp/stigs or use the Juniper_STIG_XMLs.zip included in this repo.

2. Open the checklist — Checklists → Load Checklist → select stig_results_ex.cklb
   from the report folder.

The checklist shows colour-coded CAT I/II/III findings with rule details, finding
justifications, and fix commands pre-populated from the audit.

Three blank STIG Viewer checklist templates are included in this repo. They were
created by STIG Viewer itself and are required for the merge to work:

    EX_New_Checklist.cklb    EX Switch (NDM + L2S + RTR)
    SRX_New_Checklist.cklb   SRX Gateway (NDM + ALG + VPN + IDPS)
    RTR_New_Checklist.cklb   Router (NDM + RTR)

The stig_audit.txt and critique.txt files are plain text and readable in any editor:

    less reports/20260621_143022_192_168_10_203/stig_audit.txt

---

## Usage: merge_stig_results.py

Merges STIG audit results into a STIG Viewer blank checklist template. This runs
automatically after every STIG audit when using start.py. Run manually if needed:

    python3 merge_stig_results.py <stig_audit.txt> [device_type] [output.cklb]

Device types: ex, srx, router (default: ex)

Examples:

    python3 merge_stig_results.py reports/.../stig_audit.txt ex
    python3 merge_stig_results.py reports/.../stig_audit.txt srx

---

## Usage: ask_books.py

Ask any question about Junos OS in plain English. Supports both single question
mode and an interactive chat loop with conversation history.

Single question mode:

    ./juniper-env/bin/python ask_books.py "your question here"

Interactive chat mode (follow-up questions, conversation history maintained):

    ./juniper-env/bin/python ask_books.py

Example interactive session:

    Ask a question (or 'exit' to quit): how do I configure OSPF?
    📖 Found 10 relevant chunk(s). Asking Claude...
    💾 Cache written: 1842 tokens cached for next run

    EXAMPLE CONFIG:
    set protocols ospf area 0 interface ge-0/0/0.0
    set protocols ospf area 0 interface ge-0/0/1.0

    Ask a question (or 'exit' to quit): how do I add authentication to that?
    💾 Cache hit: 1842 tokens read from cache
    ...

---

## Usage: critique_config.py

Offline config auditor. Reads a config file and critiques it against the indexed
Day One books. No device connection required.

    ./juniper-env/bin/python critique_config.py <config.txt> [focus]

Examples:

    ./juniper-env/bin/python critique_config.py config.txt
    ./juniper-env/bin/python critique_config.py config.txt "harden this config"
    ./juniper-env/bin/python critique_config.py config.txt "review BGP configuration"

Output is structured as Summary, Issues (with fix commands), Recommendations, and
Correct. When run from start.py output is saved to the report folder automatically.

---

## Usage: stig_audit.py

Evaluates a device config against indexed DISA STIG rules. Always use the device
type filter to avoid running unnecessary rules.

    ./juniper-env/bin/python stig_audit.py <config.txt> [severity]

Environment variable STIG_DEVICE_TYPE can be set to ex, srx, or router to filter
rules. This is handled automatically when running from start.py.

Outputs per run (saved to REPORT_DIR if set, otherwise alongside config):
- stig_audit.txt          full PASS/FAIL report
- stig_remediation.txt    set/delete commands for all failures
- stig_audit.ckl          legacy V2 checklist
- stig_audit.cklb         raw CKLB (structural, not for direct use in STIG Viewer)

After the audit, merge_stig_results.py is called automatically to produce the
populated stig_results_ex.cklb (or srx/router) for STIG Viewer 3.x.

---

## Usage: index_stigs.py

Indexes DISA STIG XML files into ChromaDB. Scans /srv/ftp/stigs automatically.
Already indexed files are skipped using a checkpoint file.

    ./juniper-env/bin/python index_stigs.py

Re-run whenever DISA releases a quarterly update — new files are added, existing
ones are skipped. To force a full reindex use option 9 in start.py.

---

## Usage: do_configure.py

WARNING: This script connects to a live device and can apply configuration changes.
Use in a lab environment only. Always review the proposed changes before confirming.
A human should always review the output — this tool assists engineers, it does not
replace them.

do_configure.py works in two passes:

Pass 1 — Claude analyses the task and the current device config, then asks you for
any site-specific values it needs such as NTP server IPs, syslog servers, TACACS+
credentials, management subnets, SNMP community strings, and login banners. Optional
items can be left blank and will be skipped.

Pass 2 — Claude generates the full set of Junos commands using your answers, cross-
referenced against the indexed Day One books. The script runs a commit check on the
device and shows you the proposed changes before asking for confirmation. Nothing is
applied until you type yes.

Requires NETCONF enabled on the device:

    set system services netconf ssh

Run it:

    ./juniper-env/bin/python do_configure.py <device-ip> "what you want to do"

Examples:

    ./juniper-env/bin/python do_configure.py 192.168.1.1 "harden this switch"
    ./juniper-env/bin/python do_configure.py 192.168.1.1 "configure OSPF on all uplink interfaces"
    ./juniper-env/bin/python do_configure.py 192.168.1.1 "set up NTP with authentication"

---

## File Structure

    juniper-ask-books/
    |-- start.py                  Menu launcher for all tools
    |-- ask_books.py              Query the books — single question or interactive chat
    |-- critique_config.py        Offline config auditor — no device connection needed
    |-- stig_audit.py             DoD STIG compliance auditor
    |-- merge_stig_results.py     Merges audit results into STIG Viewer cklb template
    |-- do_configure.py           AI configurator — reads device and applies changes
    |-- index_books.py            Index PDF books into ChromaDB via PyMuPDF
    |-- index_stigs.py            Index DISA STIG XML files into ChromaDB
    |-- EX_New_Checklist.cklb     Blank STIG Viewer template — EX Switch
    |-- SRX_New_Checklist.cklb    Blank STIG Viewer template — SRX Gateway
    |-- RTR_New_Checklist.cklb    Blank STIG Viewer template — Router
    |-- requirements.txt          Python dependencies
    |-- setup.sh                  Automated setup script
    |-- .gitignore                Excludes venv, database, PDFs, and reports from git
    |-- README.md                 This file
    |-- juniper-env/              Python virtual environment (not committed)
    |-- juniper_vector_db/        ChromaDB vector database (not committed)
    |-- reports/                  Audit report folders, one per run (not committed)
    |-- juniper_index_checkpoint.json       Book indexing progress (not committed)
    |-- juniper_stig_checkpoint.json        STIG indexing progress (not committed)

---

## Re-indexing

Books — full rebuild:

    rm -rf ~/juniper_vector_db ~/juniper_index_checkpoint.json
    ./juniper-env/bin/python index_books.py

STIGs — full rebuild:

    rm ~/juniper_stig_checkpoint.json
    ./juniper-env/bin/python index_stigs.py

Or use options 7 and 9 in start.py which handle the cleanup automatically.

Note: DB_PATH and CHECKPOINT_FILE in each script default to your home directory.
If running as a different user update those paths at the top of the script.

---

## Configuration

Key settings are at the top of each script:

index_books.py:
- BOOK_DIR       Path to PDF books (default /srv/ftp/dayone)
- DB_PATH        Path to ChromaDB database (default ~/juniper_vector_db)
- CHUNK_SIZE     Max characters per chunk (default 1200)
- CHUNK_STEP     Overlap step between chunks (default 900)

index_stigs.py:
- STIG_DIR       Path to STIG XML files (default /srv/ftp/stigs)
- DB_PATH        Path to ChromaDB database (default ~/juniper_vector_db)

ask_books.py:
- TOP_K          Number of chunks to keep after filtering (default 10)
- FETCH_K        Number of candidates to fetch before filtering (default 20)
- MAX_CONTEXT    Max characters of context sent to Claude (default 14000)
- MIN_RELEVANCE  L2 distance threshold, lower is stricter (default 1.2)
- CLAUDE_MODEL   Anthropic model to use (default claude-sonnet-4-6)

critique_config.py:
- TOP_K          Number of chunks to keep after filtering (default 12)
- FETCH_K        Number of candidates to fetch before filtering (default 24)
- MAX_CONTEXT    Max characters of book context sent to Claude (default 12000)
- MIN_RELEVANCE  L2 distance threshold, lower is stricter (default 1.2)
- CLAUDE_MODEL   Anthropic model to use (default claude-sonnet-4-6)

stig_audit.py:
- BATCH_SIZE     STIG rules evaluated per Claude call (default 5)
- RATE_SLEEP     Seconds between batches (default 1)
- CLAUDE_MODEL   Anthropic model to use (default claude-sonnet-4-6)

do_configure.py:
- TOP_K          Number of chunks to keep after filtering (default 12)
- FETCH_K        Number of candidates to fetch before filtering (default 24)
- MAX_CONTEXT    Max characters of book context sent to Claude (default 12000)
- MIN_RELEVANCE  L2 distance threshold, lower is stricter (default 1.2)
- CLAUDE_MODEL   Anthropic model to use (default claude-sonnet-4-6)
- NETCONF_PORT   NETCONF port (default 830)

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
