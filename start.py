import os
import sys
import subprocess

# ── Config ────────────────────────────────────────────────────────────────────
VENV_PYTHON     = os.path.join(os.path.dirname(__file__), "juniper-env", "bin", "python")
BOOK_DIR        = "/srv/ftp/dayone"
STIG_DIR        = "/srv/ftp/stigs"
DB_PATH         = os.path.join(os.path.expanduser("~"), "juniper_vector_db")
CHECKPOINT_FILE = os.path.join(os.path.expanduser("~"), "juniper_index_checkpoint.json")
# ─────────────────────────────────────────────────────────────────────────────

# Use venv python if available, otherwise fall back to current python
PYTHON = VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable


def clear():
    os.system("clear")


def header():
    print("=" * 60)
    print("  Juniper Day One - AI Network Assistant")
    print("=" * 60)
    print("")


def run(script, *args):
    """Run a script with optional arguments."""
    cmd = [PYTHON, script] + list(args)
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted.")


def pick_config_file():
    """Ask the user for a config file path."""
    print("Enter the path to the config file.")
    print("To pull from a device first run:")
    print("  ssh admin@<ip> 'show configuration | display set' > config.txt")
    print("")
    path = input("Config file path: ").strip()
    if not path:
        return None
    if not os.path.exists(path):
        print(f"❌ File not found: {path}")
        return None
    return path


def reindex_books():
    """Remove existing book index and reindex from scratch."""
    print("⚠️  This will delete the existing book index and rebuild it from scratch.")
    print(f"   Books directory : {BOOK_DIR}")
    print(f"   Database        : {DB_PATH}")
    print("")
    confirm = input("Are you sure? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Cancelled.")
        return

    import shutil
    if os.path.exists(DB_PATH):
        # Only remove the books collection, not STIGs
        # We do this by deleting and letting index_books.py recreate
        print("🗑️  Removing book index...")
        # Remove checkpoint so all books reindex
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)
            print("✅ Checkpoint cleared.")

        # Use chromadb to delete just the books collection
        try:
            import chromadb
            client = chromadb.PersistentClient(path=DB_PATH)
            client.delete_collection("juniper_books")
            print("✅ Book collection removed.")
        except Exception as e:
            print(f"⚠️  Could not remove collection: {e}")
            print("   Continuing with reindex anyway...")
    else:
        print("ℹ️  No existing database found. Starting fresh.")

    print("\n📚 Starting reindex...")
    run("index_books.py")


def index_stigs():
    """Index all STIG XML files in STIG_DIR, skipping already indexed ones."""
    print(f"Scanning {STIG_DIR} for STIG XML files...")
    print("Already indexed files will be skipped (checkpoint-based).\n")
    run("index_stigs.py")


def reindex_stigs():
    """Clear STIG checkpoint and reindex everything from scratch."""
    stig_checkpoint = os.path.join(os.path.expanduser("~"), "juniper_stig_checkpoint.json")
    print("⚠️  This will clear the STIG checkpoint and reindex all XML files.")
    print(f"   STIG directory : {STIG_DIR}")
    print(f"   Checkpoint     : {stig_checkpoint}")
    print("")
    confirm = input("Are you sure? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Cancelled.")
        return

    if os.path.exists(stig_checkpoint):
        os.remove(stig_checkpoint)
        print("✅ STIG checkpoint cleared.")

    try:
        import chromadb
        client = chromadb.PersistentClient(path=DB_PATH)
        client.delete_collection("juniper_stigs")
        print("✅ STIG collection removed.")
    except Exception as e:
        print(f"⚠️  Could not remove STIG collection: {e}")

    print("\n📚 Starting STIG reindex...")
    run("index_stigs.py")


def main_menu():
    while True:
        clear()
        header()
        print("  What would you like to do?\n")
        print("  ── Query & Audit ─────────────────────────────────────")
        print("  1. Ask a question about Junos (interactive chat)")
        print("  2. Ask a single question about Junos")
        print("  3. Critique a config file against Day One books")
        print("  4. Run a DoD STIG audit on a config file")
        print("")
        print("  ── Configure Devices ─────────────────────────────────")
        print("  5. Configure a live device (do_configure.py)")
        print("")
        print("  ── Indexing & Maintenance ────────────────────────────")
        print("  6. Reindex Day One books (full rebuild)")
        print("  7. Index new STIG files (skips already indexed)")
        print("  8. Reindex ALL STIG files (full rebuild)")
        print("")
        print("  0. Exit")
        print("")

        choice = input("  Enter your choice: ").strip()
        print("")

        if choice == "1":
            run("ask_books.py")

        elif choice == "2":
            question = input("Enter your question: ").strip()
            if question:
                run("ask_books.py", question)

        elif choice == "3":
            config = pick_config_file()
            if config:
                print("")
                focus = input("Focus area (or Enter for general review): ").strip()
                if focus:
                    run("critique_config.py", config, focus)
                else:
                    run("critique_config.py", config)

        elif choice == "4":
            config = pick_config_file()
            if config:
                print("")
                print("Filter by severity?")
                print("  1. All severities")
                print("  2. High only")
                print("  3. Medium only")
                print("  4. Low only")
                sev_choice = input("  Enter choice (default 1): ").strip()
                sev_map = {"2": "high", "3": "medium", "4": "low"}
                severity = sev_map.get(sev_choice)
                if severity:
                    run("stig_audit.py", config, severity)
                else:
                    run("stig_audit.py", config)

        elif choice == "5":
            device_ip = input("Device IP address: ").strip()
            if device_ip:
                task = input("What do you want to do? ").strip()
                if task:
                    run("do_configure.py", device_ip, task)

        elif choice == "6":
            reindex_books()
            input("\nPress Enter to return to menu...")

        elif choice == "7":
            index_stigs()
            input("\nPress Enter to return to menu...")

        elif choice == "8":
            reindex_stigs()
            input("\nPress Enter to return to menu...")

        elif choice == "0":
            print("👋 Goodbye.")
            sys.exit(0)

        else:
            print("❌ Invalid choice. Please enter a number from the menu.")

        input("\nPress Enter to return to menu...")


if __name__ == "__main__":
    main_menu()
