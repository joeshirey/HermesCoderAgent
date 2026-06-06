#!/usr/bin/env python3
"""Incremental triage loop helper script.

Invokes the backlog triage command one issue at a time to prevent terminal timeouts,
saves progress incrementally, and breaks early once the backlog is clean.
"""

import subprocess
import json
import sys
import time

def run_triage(repo_path: str, cmd_path: str, max_iterations: int = 40):
    print(f"Starting incremental triage loop for repo: {repo_path}...")

    for i in range(max_iterations):
        print(f"\n--- Iteration {i+1} ---")
        cmd = [
            "python3", cmd_path,
            "triage",
            "--repo", repo_path,
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

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 triage_loop.py <repo_path> <github_backlog_script_path>")
        sys.exit(1)
    run_triage(sys.argv[1], sys.argv[2])
