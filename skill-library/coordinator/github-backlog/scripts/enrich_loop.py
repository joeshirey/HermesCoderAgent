#!/usr/bin/env python3
import subprocess
import json
import sys
import time
import os

repo = os.getcwd()
cmd_path = os.path.expanduser("~/.hermes-coder/scripts/github_backlog.py")
log_file = os.path.expanduser("~/.hermes-coder/logs/enrich_loop.log")

# Ensure the logs directory exists
os.makedirs(os.path.dirname(log_file), exist_ok=True)

def log(msg):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    print(formatted)
    with open(log_file, "a") as f:
        f.write(formatted + "\n")

log(f"Starting automatic enrichment loop for thin/boilerplate backlog issues in repo: {repo}...")

# Fetch all open issues in the repo
cmd_list = [
    "gh", "issue", "list",
    "--limit", "100",
    "--state", "open",
    "--json", "number,title,body"
]

try:
    res = subprocess.run(cmd_list, capture_output=True, text=True, check=True)
    issues = json.loads(res.stdout)
except Exception as e:
    log(f"Error fetching issues from GitHub: {e}")
    sys.exit(1)

thin_issues = []
for issue in issues:
    body = issue.get("body", "") or ""
    if "_TBD_" in body or "identify during triage" in body:
        thin_issues.append((issue["number"], issue["title"]))

log(f"Discovered {len(thin_issues)} thin/boilerplate issues out of {len(issues)} open issues.")

if not thin_issues:
    log("All backlog issues are already fully triaged and enriched! Nothing to do.")
    sys.exit(0)

# Process them sequentially
success_count = 0
fail_count = 0

for idx, (num, title) in enumerate(thin_issues):
    log(f"\n--- [Progress: {idx+1}/{len(thin_issues)}] Enriching Issue #{num}: {title} ---")
    
    cmd_enrich = [
        "python3", cmd_path,
        "enrich",
        "--repo", repo,
        "--issue", str(num),
        "--confirm",
        "--json"
    ]
    
    start_time = time.time()
    try:
        result = subprocess.run(cmd_enrich, capture_output=True, text=True, timeout=300)
        duration = round(time.time() - start_time, 1)
        
        if result.returncode != 0:
            log(f"Failed to enrich issue #{num}. Exit code: {result.returncode}. Duration: {duration}s")
            log(f"Stderr: {result.stderr.strip()}")
            fail_count += 1
            time.sleep(5)
            continue
            
        try:
            data = json.loads(result.stdout)
            status = data.get("status")
            if status == "enriched":
                log(f"Successfully enriched issue #{num} in {duration}s!")
                success_count += 1
            else:
                log(f"Warning: Issue #{num} finished with status '{status}' (expected 'enriched'). Duration: {duration}s")
                log(f"Response: {result.stdout}")
                fail_count += 1
        except json.JSONDecodeError:
            log(f"Warning: Command output was not valid JSON for issue #{num}. Duration: {duration}s")
            log(f"Stdout: {result.stdout.strip()}")
            success_count += 1
            
    except subprocess.TimeoutExpired:
        log(f"Timeout expired (300s) while enriching issue #{num}! Skipping...")
        fail_count += 1
    except Exception as e:
        log(f"Unexpected error while enriching issue #{num}: {e}")
        fail_count += 1
        
    time.sleep(5)

log("\n==================================================")
log(f"Enrichment Loop Completed!")
log(f"Total processed: {len(thin_issues)}")
log(f"Successfully enriched: {success_count}")
log(f"Failed/Skipped: {fail_count}")
log(f"Logs written to: {log_file}")
log("==================================================")
