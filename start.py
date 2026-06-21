import os
import sys
import subprocess
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
VENV_PYTHON     = os.path.join(os.path.dirname(__file__), "juniper-env", "bin", "python")
BOOK_DIR        = "/srv/ftp/dayone"
STIG_DIR        = "/srv/ftp/stigs"
DB_PATH         = os.path.join(os.path.expanduser("~"), "juniper_vector_db")
CHECKPOINT_FILE = os.path.join(os.path.expanduser("~"), "juniper_index_checkpoint.json")
REPORTS_DIR     = os.path.join(os.path.dirname(__file__), "reports")
# ─────────────────────────────────────────────────────────────────────────────

PYTHON = VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable


def clear():
    os.system("clear")


def header():
    print("=" * 60)
    print("  Juniper Day One - AI Network Assistant")
    print("=" * 60)
    print("")


def make_report_folder(ip=None):
    """Create a timestamped report folder for this run."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    label     = ip.replace(".", "_") if ip else "manual"
    folder    = os.path.join(REPORTS_DIR, f"{timestamp}_{label}")
    os.makedirs(folder, exist_ok=True)
    return folder


def run(script, *args, report_dir=None):
    """Run a script, optionally passing a report directory via environment."""
    cmd = [PYTHON, script] + list(args)
    env = os.environ.copy()
    if report_dir:
        env["REPORT_DIR"] = report_dir
    try:
        subprocess.run(cmd, env=env)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted.")


def list_reports():
    """Show existing report folders."""
    if not os.path.exists(REPORTS_DIR):
        print("   No reports yet.")
        return
    folders = sorted(os.listdir(REPORTS_DIR), reverse=True)
    if not folders:
        print("   No reports yet.")
        return
    print("Recent reports:\n")
    for idx, folder in enumerate(folders[:10], 1):
        folder_path = os.path.join(REPORTS_DIR, folder)
        files = os.listdir(folder_path)
        tags = []
        if any("config.txt" == f for f in files):
            tags.append("config")
        if any("critique" in f for f in files):
            tags.append("critique")
        if any("stig_audit" in f for f in files):
            tags.append("STIG")
        if any(".ckl" in f for f in files):
            tags.append("CKL")
        tag_str = " + ".join(tags) if tags else "empty"
        print(f"  {idx}. {folder}  [{tag_str}]")


def pull_config_from_device(report_dir):
    """SSH into a device and pull the running config into the report folder."""
    import getpass
    print("Enter device details to pull config via SSH.\n")
    ip       = input("  Device IP address: ").strip()
    if not ip:
        return None, None
    username = input("  Username: ").strip()
    if not username:
        return None, None
    password = getpass.getpass("  Password: ")

    print(f"\n🔌 Connecting to {ip}...")

    try:
        import paramiko
    except ImportError:
        print("❌ paramiko not installed. Run:")
        print("   ./juniper-env/bin/pip install paramiko")
        return None, None

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ip, username=username, password=password, timeout=15)

        cmd = "show configuration | display set | no-more"
        stdin, stdout, stderr = ssh.exec_command(cmd)
        config_text = stdout.read().decode("utf-8").strip()
        stdout.close()
        stdin.close()
        stderr.close()
        ssh.close()

        if not config_text:
            print("❌ No config returned from device.")
            return None, None

        output_file = os.path.join(report_dir, "config.txt")
        with open(output_file, "w") as f:
            f.write(config_text)

        print(f"✅ Config saved to {output_file} ({len(config_text.splitlines())} lines)")
        return output_file, ip

    except Exception as e:
        print(f"❌ SSH error: {e}")
        return None, None


def pick_config_file():
    """Ask how the user wants to provide the config."""
    print("How do you want to provide the config?\n")
    print("  1. Pull from a live device (SSH)")
    print("  2. Use a config file from a previous report")
    print("  3. Use a config file from this directory")
    print("")
    choice = input("  Enter choice: ").strip()
    print("")

    if choice == "1":
        return "ssh", None

    elif choice == "2":
        # List reports that have a config.txt
        if not os.path.exists(REPORTS_DIR):
            print("❌ No reports directory found.")
            return None, None
        folders = sorted(os.listdir(REPORTS_DIR), reverse=True)
        config_folders = [
            f for f in folders
            if os.path.exists(os.path.join(REPORTS_DIR, f, "config.txt"))
        ]
        if not config_folders:
            print("❌ No previous reports with config files found.")
            return None, None
        print("Select a previous report:\n")
        for idx, folder in enumerate(config_folders[:10], 1):
            print(f"  {idx}. {folder}")
        print("")
        sel = input("Enter number: ").strip()
        if sel.isdigit():
            idx = int(sel) - 1
            if 0 <= idx < len(config_folders):
                config_path = os.path.join(REPORTS_DIR, config_folders[idx], "config.txt")
                return config_path, config_folders[idx]
        print("❌ Invalid selection.")
        return None, None

    elif choice == "3":
        txt_files = sorted([
            f for f in os.listdir(".")
            if f.endswith(".txt")
            and "_critique" not in f
            and "_stig_audit" not in f
            and "_stig_remediation" not in f
            and f != "requirements.txt"
        ])
        if txt_files:
            print("Config files found:\n")
            for idx, f in enumerate(txt_files, 1):
                size = os.path.getsize(f)
                print(f"  {idx}. {f}  ({size} bytes)")
            print("")
            sel = input("Enter number or full path: ").strip()
            if sel.isdigit():
                idx = int(sel) - 1
                if 0 <= idx < len(txt_files):
                    return txt_files[idx], None
            elif os.path.exists(sel):
                return sel, None
            print("❌ Invalid selection.")
            return None, None
        else:
            path = input("Config file path: ").strip()
            if path and os.path.exists(path):
                return path, None
            print("❌ File not found.")
            return None, None
    else:
        print("❌ Invalid choice.")
        return None, None


def get_config(existing_report_dir=None):
    """
    Get a config file path and report directory.
    Returns (config_path, report_dir) or (None, None).
    """
    result, meta = pick_config_file()

    if result == "ssh":
        # Create report folder now, named after IP
        tmp_folder = make_report_folder("unknown")
        config_path, ip = pull_config_from_device(tmp_folder)
        if not config_path:
            return None, None
        # Rename folder with actual IP
        if ip:
            new_folder = os.path.join(
                REPORTS_DIR,
                f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{ip.replace('.', '_')}"
            )
            os.rename(tmp_folder, new_folder)
            # Update config path to new folder
            config_path = os.path.join(new_folder, "config.txt")
            return config_path, new_folder
        return config_path, tmp_folder

    elif result and meta:
        # Returning an existing report folder's config
        report_dir = os.path.join(REPORTS_DIR, meta) if not meta.startswith("/") else os.path.dirname(result)
        return result, report_dir

    elif result:
        # A loose file — create a new report folder for it
        report_dir = make_report_folder()
        import shutil
        dest = os.path.join(report_dir, "config.txt")
        shutil.copy(result, dest)
        return dest, report_dir

    return None, None


def run_stig_audit(config, report_dir):
    """Run STIG audit with device type and severity selection, then merge into CKLB."""
    print("")
    print("What device type is this?\n")
    print("  1. EX Switch        (NDM + L2S + RTR — ~182 rules)")
    print("  2. SRX Gateway      (NDM + ALG + VPN + IDPS — ~149 rules)")
    print("  3. Router           (NDM + RTR — ~145 rules)")
    print("  4. All rules        (628 rules — slowest, most expensive)")
    print("")
    dev_choice = input("  Enter choice (default 1): ").strip()
    dev_map = {"1": "ex", "2": "srx", "3": "router", "4": None}
    device_type = dev_map.get(dev_choice, "ex")

    print("")
    print("Filter by severity?\n")
    print("  1. High only   (CAT I — recommended for quick audits)")
    print("  2. Medium only (CAT II)")
    print("  3. Low only    (CAT III)")
    print("  4. All severities")
    print("")
    sev_choice = input("  Enter choice (default 1): ").strip()
    sev_map = {"1": "high", "2": "medium", "3": "low", "4": None}
    severity = sev_map.get(sev_choice, "high")

    env = os.environ.copy()
    env["REPORT_DIR"] = report_dir
    if device_type:
        env["STIG_DEVICE_TYPE"] = device_type

    cmd = [PYTHON, "stig_audit.py", config]
    if severity:
        cmd.append(severity)

    try:
        subprocess.run(cmd, env=env)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted.")
        return

    # ── Auto-merge results into STIG Viewer CKLB ─────────────────────────────
    audit_txt = os.path.join(report_dir, "stig_audit.txt")
    if os.path.exists(audit_txt) and device_type:
        print("\n🔀 Merging results into STIG Viewer checklist...")
        merge_cmd = [PYTHON, "merge_stig_results.py", audit_txt, device_type]
        try:
            subprocess.run(merge_cmd)
            cklb_out = os.path.join(report_dir, f"stig_results_{device_type}.cklb")
            if os.path.exists(cklb_out):
                print(f"✅ STIG Viewer checklist ready: {os.path.basename(cklb_out)}")
                print(f"   Open in STIG Viewer 3.x: Checklists → Load Checklist")
        except KeyboardInterrupt:
            print("\n⚠️  Merge interrupted.")


def reindex_books():
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
        print("✅ Checkpoint cleared.")
    try:
        import chromadb
        client = chromadb.PersistentClient(path=DB_PATH)
        client.delete_collection("juniper_books")
        print("✅ Book collection removed.")
    except Exception as e:
        print(f"⚠️  Could not remove collection: {e}")
    print("\n📚 Starting reindex...")
    run("index_books.py")


def index_stigs():
    print(f"Scanning {STIG_DIR} for STIG XML files...")
    print("Already indexed files will be skipped.\n")
    run("index_stigs.py")


def reindex_stigs():
    stig_checkpoint = os.path.join(os.path.expanduser("~"), "juniper_stig_checkpoint.json")
    confirm = input("Clear STIG checkpoint and reindex all? (yes/no): ").strip().lower()
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

        # Show recent reports in the header
        if os.path.exists(REPORTS_DIR):
            folders = sorted(os.listdir(REPORTS_DIR), reverse=True)[:3]
            if folders:
                print("  Recent reports:")
                for folder in folders:
                    folder_path = os.path.join(REPORTS_DIR, folder)
                    files = os.listdir(folder_path)
                    tags = []
                    if any("critique" in f for f in files): tags.append("critique")
                    if any("stig_audit" in f for f in files): tags.append("STIG")
                    if any(".ckl" in f for f in files): tags.append("CKL")
                    tag_str = " + ".join(tags) if tags else "config only"
                    print(f"  📁 {folder}  [{tag_str}]")
                print("")

        print("  What would you like to do?\n")
        print("  ── Query & Audit ─────────────────────────────────────")
        print("  1. Ask a question about Junos (interactive chat)")
        print("  2. Ask a single question about Junos")
        print("  3. Critique a config file against Day One books")
        print("  4. Run a DoD STIG audit on a config file")
        print("  5. Critique + STIG audit (both, one config pull)")
        print("")
        print("  ── Configure Devices ─────────────────────────────────")
        print("  6. Configure a live device (do_configure.py)")
        print("")
        print("  ── Indexing & Maintenance ────────────────────────────")
        print("  7. Reindex Day One books (full rebuild)")
        print("  8. Index new STIG files (skips already indexed)")
        print("  9. Reindex ALL STIG files (full rebuild)")
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
            config, report_dir = get_config()
            if config and report_dir:
                print("")
                focus = input("Focus area (or Enter for general review): ").strip()
                if focus:
                    run("critique_config.py", config, focus, report_dir=report_dir)
                else:
                    run("critique_config.py", config, report_dir=report_dir)
                print(f"\n📁 Report saved to: {report_dir}")

        elif choice == "4":
            config, report_dir = get_config()
            if config and report_dir:
                run_stig_audit(config, report_dir)
                print(f"\n📁 Report saved to: {report_dir}")

        elif choice == "5":
            # Both critique and STIG in one go
            config, report_dir = get_config()
            if config and report_dir:
                print("")
                focus = input("Critique focus area (or Enter for general review): ").strip()
                if focus:
                    run("critique_config.py", config, focus, report_dir=report_dir)
                else:
                    run("critique_config.py", config, report_dir=report_dir)
                print("")
                run_stig_audit(config, report_dir)
                print(f"\n📁 All reports saved to: {report_dir}")

        elif choice == "6":
            device_ip = input("Device IP address: ").strip()
            if device_ip:
                task = input("What do you want to do? ").strip()
                if task:
                    run("do_configure.py", device_ip, task)

        elif choice == "7":
            reindex_books()
            input("\nPress Enter to return to menu...")

        elif choice == "8":
            index_stigs()
            input("\nPress Enter to return to menu...")

        elif choice == "9":
            reindex_stigs()
            input("\nPress Enter to return to menu...")

        elif choice == "0":
            print("👋 Goodbye.")
            sys.exit(0)

        else:
            print("❌ Invalid choice.")

        input("\nPress Enter to return to menu...")


if __name__ == "__main__":
    main_menu()
