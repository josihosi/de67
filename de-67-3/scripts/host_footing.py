#!/usr/bin/env python3
"""Read-only host/repository observations. A snapshot is not launch permission."""
import argparse
import base64
import datetime
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit, urlunsplit


def command(argv, cwd=None, timeout=15):
    try:
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                                timeout=timeout, env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
        if result.returncode:
            return {"available": False, "reason": "command_failed", "exit_code": result.returncode}
        return {"available": True, "value": result.stdout.strip()}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"available": False, "reason": type(error).__name__}


def powershell(script):
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    result = command(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded])
    if result["available"]:
        try:
            return {"available": True, "value": json.loads(result["value"])}
        except ValueError:
            return {"available": False, "reason": "invalid_json"}
    return result


def safe_remote(value):
    # Never expose embedded HTTP credentials, queries or fragments.
    if "://" in value:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    return value


def repository(path):
    root = Path(path).expanduser().resolve()
    row = {"requested_path": path, "path": str(root)}
    if not root.is_dir():
        return dict(row, available=False, reason="directory_missing")
    git = lambda *args: command(["git", "-C", str(root), *args])
    top = git("rev-parse", "--show-toplevel")
    if not top["available"]:
        return dict(row, available=False, reason="git_repository_unavailable")
    if Path(top["value"]).resolve() != root:
        return dict(row, available=False, reason="not_repository_root", discovered_root=top["value"])
    row.update(available=True)
    for key, args in {
        "commit": ("rev-parse", "HEAD"),
        "branch": ("symbolic-ref", "--quiet", "--short", "HEAD"),
        "status": ("status", "--porcelain=v1", "--untracked-files=normal"),
        "common_git_dir": ("rev-parse", "--git-common-dir"),
        "worktrees": ("worktree", "list", "--porcelain"),
    }.items():
        row[key] = git(*args)
    remote_names = git("remote")
    row["remotes"] = []
    if remote_names["available"]:
        for name in remote_names["value"].splitlines():
            url = git("remote", "get-url", name)
            row["remotes"].append({"name": name, "url": safe_remote(url["value"]) if url["available"] else None})
    row["dirty"] = bool(row["status"]["value"]) if row["status"]["available"] else None
    row["source_ready"] = "not_assessed"  # Build, branch purpose and dirty-work disposition belong to caller.
    row["disk_free_bytes"] = shutil.disk_usage(root).free
    return row


def resources():
    system = platform.system()
    if system == "Windows":
        return powershell("$ErrorActionPreference='Stop'; $o=Get-CimInstance Win32_OperatingSystem; "
            "$c=Get-CimInstance Win32_Processor; [ordered]@{"
            "physical_total_bytes=([long]$o.TotalVisibleMemorySize*1024);"
            "physical_free_bytes=([long]$o.FreePhysicalMemory*1024);"
            "paging_free_bytes=([long]$o.FreeSpaceInPagingFiles*1024);"
            "cpu_load_percent=($c|Measure-Object LoadPercentage -Average).Average;"
            "boot_utc=$o.LastBootUpTime.ToUniversalTime().ToString('o');"
            "disks=@(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3'|"
            "Select-Object DeviceID,FreeSpace,Size)}|ConvertTo-Json -Depth 4")
    if system == "Darwin":
        return {"available": True, "value": {
            "physical_total_bytes": command(["sysctl", "-n", "hw.memsize"]),
            "vm_pages": command(["vm_stat"]),
            "swap_usage": command(["sysctl", "-n", "vm.swapusage"]),
            "memory_pressure_level": command(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"]),
            "load_average": list(os.getloadavg()), "logical_cpu_count": os.cpu_count(),
            "boot": command(["sysctl", "-n", "kern.boottime"]),
        }, "meaning": "Darwin page counters/load averages, not Windows free-memory or CPU-percent equivalents"}
    return {"available": False, "reason": "unsupported_platform"}


def process(pid):
    if platform.system() == "Windows":
        result = powershell("$ErrorActionPreference='Stop'; $p=Get-CimInstance Win32_Process -Filter "
            f"'ProcessId={pid}'; if ($null -eq $p) {{ 'null' }} else {{ "
            "$p|Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CreationDate,WorkingSetSize|ConvertTo-Json }")
    else:
        result = command(["ps", "-p", str(pid), "-o", "pid=,ppid=,lstart=,rss=,comm="])
    return {"pid": pid, "observation": result,
            "ownership": "not_inferred; compare birth/executable with the exact launch record"}


def snapshot(repos, pids):
    began = time.time()
    return {"schema": "de67-host-footing-v1", "observation_started_unix": began,
            "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "host": socket.gethostname(), "system": platform.system(),
            "resources": resources(), "repositories": [repository(p) for p in repos],
            "requested_processes": [process(p) for p in pids],
            "process_inventory_complete": False,
            "launch_admission": "not_assessed", "sync_performed": False,
            "elapsed_seconds": round(time.time() - began, 3),
            "limits": "Point observation; no freshness TTL or capacity threshold invented. "
                      "No game, input, build or repository mutation. Run/build/input ownership must be bound separately."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", action="append", default=[])
    parser.add_argument("--pid", action="append", type=int, default=[])
    parser.add_argument("--ssh", help="Explicit existing SSH host alias for one read-only probe")
    parser.add_argument("--remote-python", default="python")
    args = parser.parse_args()
    if any(pid <= 0 for pid in args.pid):
        parser.error("PID must be positive")
    if args.ssh:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.ssh) or not re.fullmatch(r"[A-Za-z0-9_./:-]+", args.remote_python):
            parser.error("Use an SSH alias and a simple interpreter path without shell syntax")
        # Values travel as Python literals on stdin, never as remote shell interpolation.
        payload = "import sys\nsys.argv=" + repr(["host_footing.py"] +
            [part for p in args.repo for part in ["--repo", p]] +
            [part for p in args.pid for part in ["--pid", str(p)]]) + "\n" + Path(__file__).read_text()
        try:
            start = time.time()
            result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                "-o", "RequestTTY=no", "-o", "RemoteCommand=none", args.ssh,
                args.remote_python + " -"], input=payload, capture_output=True, text=True, timeout=60)
            value = json.loads(result.stdout) if result.returncode == 0 else None
            if not isinstance(value, dict) or value.get("schema") != "de67-host-footing-v1":
                raise ValueError("remote_probe_failed")
            value["transport"] = {"ssh_alias": args.ssh, "collector_started_unix": start,
                                  "collector_received_unix": time.time()}
        except (OSError, subprocess.TimeoutExpired, ValueError) as error:
            value = {"schema": "de67-host-footing-v1", "transport": {"ssh_alias": args.ssh},
                     "available": False, "reason": type(error).__name__,
                     "launch_admission": "not_assessed", "host": None}
    else:
        value = snapshot(args.repo, args.pid)
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    main()
