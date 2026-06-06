#!/usr/bin/env python3
"""Incremental Triage Loop

Statically re-runnable script to safely triage and groom a large backlog
of GitHub issues one-by-one, preventing API timeouts and rate-limiting blocks.
Incremental writes ensure that if the process is interrupted, progress is preserved.

Usage:
    python3 incremental_triage.py --repo "/path/to/repo" --limit 20
"""

import argparse
import subprocess
import json
import sys
import time

def main():
    parser = argparse.ArgumentParser(description="Incremental Backlog Triage")
    parser.add_argument("--repo", required=True, help="Absolute path to git repository")
    parser.add_argument("--limit", type=int, default=10, help="Maximum number of issues to triage")
    parser.add_argument("--confirm", action="store_true", default=True, help="Actually apply mutations to GitHub")
    args = parser.parse_args()

    cmd_path = "/Users/you/.hermes-coder/scripts/github_backlog.py"
    print(f"Starting incremental triage loop for repo: {args.repo}...")

    for i in range(args.limit):
        print(f"\n--- Triage Iteration {i+1}/{args.limit} ---")
        cmd = [
            "python3", cmd_path,
            "triage",
            "--repo", args.repo,
            "--limit", "1",
        ]
        if args.confirm:
            cmd.append("--confirm")
        cmd.append("--json")

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
    main()
