#!/usr/bin/env python3
"""Container runner: hardware probe + sandboxed execution (Backlog #6, Phase 4).

The execution guard of the dynamic skill/tool pipeline. Untrusted (Tier 2/3) code
is NEVER run on the host -- it runs inside a network-isolated, read-only,
resource-capped, timed sandbox, and ONLY from its immutable vault copy (lock-in
execution, RFC 2.E.3).

Runner selection (probe):
    arm64 + `container` on PATH -> apple-container (Apple Silicon native)
    else docker on PATH         -> docker
    else                        -> local-restricted (NO sandbox; refuses Tier 2/3)

Subcommands:
    probe                  Report the selected runner + arch + availability.
    run                    Execute a command sandboxed against a source.

Usage:
    python3 container_runner.py probe [--json]
    python3 container_runner.py run --from-vault <name> --cmd '<cmd>' [--image <i>]
                                    [--tier <n>] [--timeout <s>] [--dry-run] [--json]
    python3 container_runner.py run --source <path> --cmd '<cmd>' --tier 1 ...

Exit codes:
    0  Success / dry-run
    1  Run failed, or blocked (no sandbox available for this tier)
    2  Invalid arguments / no runner / vault name not found
"""

import argparse
import json
import platform
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from vetted_vault import load_registry  # noqa: E402


DEFAULT_IMAGE = "nikolaik/python-nodejs:python3.11-nodejs20"
DEFAULT_TIMEOUT = 120
DEFAULT_CPU_LIMIT = "1"
DEFAULT_MEMORY_LIMIT = "512m"
LOCAL_RESTRICTED_ALLOW_TIER = {1}
OUTPUT_TAIL = 4000

RUNNER_APPLE = "apple-container"
RUNNER_DOCKER = "docker"
RUNNER_LOCAL = "local-restricted"


@dataclass
class RunResult:
    runner: str
    image: str
    cmd: str
    status: str  # success | failed | timeout | blocked | dry-run
    returncode: int = 0
    duration_s: float = 0.0
    output_tail: str = ""
    error: str = ""
    sandbox_command: str = ""

    def as_dict(self) -> dict:
        return {
            "runner": self.runner,
            "image": self.image,
            "cmd": self.cmd,
            "status": self.status,
            "returncode": self.returncode,
            "duration_s": round(self.duration_s, 2),
            "output_tail": self.output_tail,
            "error": self.error,
            "sandbox_command": self.sandbox_command,
        }


# -- Probe --

def probe_runner() -> dict:
    arch = platform.machine().lower()
    available = []
    if shutil.which("container"):
        available.append("container")
    if shutil.which("docker"):
        available.append("docker")

    if arch in ("arm64", "aarch64") and shutil.which("container"):
        runner = RUNNER_APPLE
    elif shutil.which("docker"):
        runner = RUNNER_DOCKER
    else:
        runner = RUNNER_LOCAL

    return {"runner": runner, "arch": arch, "available": available}


# -- Sandbox command construction --

def _docker_command(image: str, work_path: Path, cmd: str,
                    cpus: str, memory: str, read_only: bool) -> list:
    mount = f"{work_path}:/work:ro" if read_only else f"{work_path}:/work"
    return [
        "docker", "run", "--rm",
        "--network", "none",
        "--cpus", cpus,
        "--memory", memory,
        "-v", mount,
        "-w", "/work",
        image,
        "sh", "-lc", cmd,
    ]


def _apple_command(image: str, work_path: Path, cmd: str, read_only: bool) -> list:
    mount = f"{work_path}:/work:ro" if read_only else f"{work_path}:/work"
    return [
        "container", "run", "--rm",
        "--network", "none",
        "-v", mount,
        "-w", "/work",
        image,
        "sh", "-lc", cmd,
    ]


# -- Source resolution --

def _resolve_source(from_vault: Optional[str], source: Optional[str],
                    tier: int, allow_unvaulted: bool) -> tuple:
    """Return (work_path, error). Tier 2/3 must come from the vault (lock-in)."""
    if from_vault:
        registry = load_registry()
        entry = registry.get(from_vault)
        if entry is None:
            return None, f"vault name not found: {from_vault!r}"
        if entry.status != "approved":
            return None, f"vault entry {from_vault!r} is not approved (status={entry.status})"
        path = Path(entry.vaulted_path)
        if not path.exists():
            return None, f"vaulted path missing on disk: {path}"
        return path, ""

    # --source path
    if not source:
        return None, "either --from-vault or --source is required"
    path = Path(source)
    if not path.exists():
        return None, f"source not found: {source}"
    if tier in (2, 3) and not allow_unvaulted:
        return None, (f"Tier {tier} sources must run from the vault (--from-vault), "
                      "not an arbitrary --source path (lock-in execution). "
                      "Pass --allow-unvaulted only for trusted local testing.")
    return path, ""


# -- Run --

def run_sandboxed(args) -> tuple:
    """Returns (RunResult, exit_code)."""
    probe = probe_runner()
    runner = probe["runner"]
    image = args.image or DEFAULT_IMAGE
    tier = args.tier

    work_path, err = _resolve_source(args.from_vault, args.source, tier, args.allow_unvaulted)
    if err:
        return RunResult(runner=runner, image=image, cmd=args.cmd,
                         status="failed", error=err), 2
    work_path = work_path.resolve()

    # local-restricted: no sandbox. Only Tier 1 may run; never run untrusted on host.
    if runner == RUNNER_LOCAL:
        if tier not in LOCAL_RESTRICTED_ALLOW_TIER:
            return RunResult(
                runner=runner, image=image, cmd=args.cmd, status="blocked",
                error=(f"No container runtime available and Tier {tier} may not run on the "
                       "host. Install Docker (or Apple `container` on arm64) to sandbox "
                       "untrusted tools."),
            ), 1
        sandbox_cmd = ["sh", "-lc", args.cmd]
        cwd = str(work_path)
    elif runner == RUNNER_APPLE:
        sandbox_cmd = _apple_command(image, work_path, args.cmd, read_only=True)
        cwd = None
    else:  # docker
        sandbox_cmd = _docker_command(image, work_path, args.cmd,
                                      DEFAULT_CPU_LIMIT, DEFAULT_MEMORY_LIMIT, read_only=True)
        cwd = None

    preview = " ".join(shlex.quote(p) for p in sandbox_cmd)

    if args.dry_run:
        return RunResult(runner=runner, image=image, cmd=args.cmd,
                         status="dry-run", sandbox_command=preview), 0

    start = time.time()
    try:
        proc = subprocess.run(
            sandbox_cmd, cwd=cwd, capture_output=True, text=True,
            timeout=args.timeout,
        )
    except subprocess.TimeoutExpired:
        return RunResult(runner=runner, image=image, cmd=args.cmd, status="timeout",
                         duration_s=time.time() - start, sandbox_command=preview,
                         error=f"timed out after {args.timeout}s"), 1
    except (OSError, FileNotFoundError) as e:
        return RunResult(runner=runner, image=image, cmd=args.cmd, status="failed",
                         duration_s=time.time() - start, sandbox_command=preview,
                         error=str(e)), 1

    duration = time.time() - start
    combined = (proc.stdout or "") + (proc.stderr or "")
    tail = combined[-OUTPUT_TAIL:]
    status = "success" if proc.returncode == 0 else "failed"
    return RunResult(runner=runner, image=image, cmd=args.cmd, status=status,
                     returncode=proc.returncode, duration_s=duration,
                     output_tail=tail, sandbox_command=preview), (0 if status == "success" else 1)


# -- CLI --

def cmd_probe(args) -> int:
    probe = probe_runner()
    if args.json:
        print(json.dumps(probe, indent=2))
    else:
        print(f"runner: {probe['runner']}  (arch={probe['arch']}, "
              f"available={probe['available'] or 'none'})")
    return 0


def cmd_run(args) -> int:
    if not args.cmd:
        print("ERROR: --cmd is required", file=sys.stderr)
        return 2
    result, code = run_sandboxed(args)
    if args.json:
        print(json.dumps(result.as_dict(), indent=2))
    else:
        print(f"[{result.status}] runner={result.runner} rc={result.returncode} "
              f"{result.duration_s:.2f}s")
        if result.sandbox_command:
            print(f"  $ {result.sandbox_command}")
        if result.output_tail:
            print(result.output_tail)
        if result.error:
            print(f"  error: {result.error}", file=sys.stderr)
    return code


def main() -> None:
    parser = argparse.ArgumentParser(description="Hardware probe + sandboxed execution for vaulted tools")
    sub = parser.add_subparsers(dest="command", required=True)

    p_probe = sub.add_parser("probe", help="Report the selected container runner")
    p_probe.add_argument("--json", action="store_true")
    p_probe.set_defaults(func=cmd_probe)

    p_run = sub.add_parser("run", help="Execute a command sandboxed against a source")
    src = p_run.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-vault", default=None, help="Approved vault entry name (lock-in execution)")
    src.add_argument("--source", default=None, help="Source path (Tier 1, or with --allow-unvaulted)")
    p_run.add_argument("--cmd", required=True, help="Command to run inside the sandbox")
    p_run.add_argument("--image", default=None, help=f"Container image (default: {DEFAULT_IMAGE})")
    p_run.add_argument("--tier", type=int, default=3, help="Trust tier of the source (default 3)")
    p_run.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Run timeout (seconds)")
    p_run.add_argument("--allow-unvaulted", action="store_true",
                       help="Permit a non-vault --source for Tier 2/3 (trusted local testing only)")
    p_run.add_argument("--dry-run", action="store_true", help="Print the sandbox command, run nothing")
    p_run.add_argument("--json", action="store_true")
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
