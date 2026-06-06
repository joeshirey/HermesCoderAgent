#!/usr/bin/env python3
"""Template script for running an incremental backlog triage loop.

Copy this file to your active workspace, modify the repo and cmd_path variables,
and execute it to safely triage large backlogs in a robust, step-by-step manner.
"""

import subprocess
import json
import sys
import time

# --- CONFIGURATION (Modify as needed) ---
REPO_PATH = "/path/to/your/repository"
BACKLOG_CMD_PATH = "/Users/you/.hermes-coder/scripts/github_backlog.py"
MAX_ITERATIONS = 35

print(f"Starting incremental triage loop for repo: {REPO_PATH}...")

for i in range(MAX_ITERATIONS):
    print(f"\n--- Iteration {i+1} ---")
    cmd = [
        "python3", BACKLOG_CMD_PATH,
        "triage",
        "--repo", REPO_PATH,
        "--limit", "1",
        "--confirm",
        "--json"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"Error: Command failed with exit code {result.returncode}")
            print(result.stderr)
            time.sleep(5)
            continue
            
        try:
            data = json.loads(result.stdout)
            processed = data.get("processed", 0)
            groomed = data.get("groomed", 0)
            status = data.get("status", "")
            
            if status == "ok" and processed == 0:
                print("All issues successfully triaged! No untriaged issues remaining.")
                break
                
            if groomed > 0:
                item = data.get("items", [{}])[0]
                number = item.get("number")
                title = item.get("title")
                print(f"Successfully triaged issue #{number}: {title}")
            else:
                print(f"Status: {status}, Processed: {processed}, Groomed: {groomed}")
                if processed == 0:
                    print("Breaking loop as no issues were processed.")
                    break
        except json.JSONDecodeError:
            print("Failed to parse JSON output:")
            print(result.stdout)
            time.sleep(5)
    except subprocess.TimeoutExpired:
        print("Command timed out. Retrying next iteration...")
        time.sleep(5)

print("\nTriage loop finished!")
