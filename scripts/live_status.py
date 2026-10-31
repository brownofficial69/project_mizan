"""Live status board for MIZAN experiments. Standard library only, no network, no AI calls.

Run it in any terminal:   python scripts/live_status.py
One snapshot and exit:    python scripts/live_status.py --once
Slower refresh:           python scripts/live_status.py --interval 5

Shows: running experiment processes (with elapsed time and CPU time), GPU load,
result files and their verdicts, and the last lines of each run log.
Ctrl+C to quit.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "experiments" / "phase1" / "results"
SPIN = "|/-\\"
G, R, Y, C, D, B, X = "\033[32m", "\033[31m", "\033[33m", "\033[36m", "\033[2m", "\033[1m", "\033[0m"


def run(cmd: list[str], timeout: int = 8) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def processes() -> list[dict]:
    """Python processes running a MIZAN experiment script."""
    if os.name == "nt":
        ps = ("Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
              "Where-Object { $_.CommandLine -match 'run.py|benchmark|uvicorn|auto_runner' } | "
              "ForEach-Object { $p = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue; "
              "[pscustomobject]@{pid=$_.ProcessId; cmd=$_.CommandLine; "
              "start=$_.CreationDate.ToString('yyyy-MM-ddTHH:mm:ss'); cpu=[math]::Round($p.CPU,1)} } | ConvertTo-Json -Compress")
        out = run(["powershell", "-NoProfile", "-Command", ps], timeout=15).strip()
        if not out:
            return []
        data = json.loads(out)
        return data if isinstance(data, list) else [data]
    out = run(["ps", "-eo", "pid,etimes,time,args"]).splitlines()[1:]
    procs = []
    for line in out:
        parts = line.split(None, 3)
        if len(parts) == 4 and any(k in parts[3] for k in ("run.py", "benchmark", "uvicorn")):
            procs.append({"pid": parts[0], "cmd": parts[3], "start": None, "cpu": parts[2], "etimes": int(parts[1])})
    return procs


def gpu() -> str:
    out = run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
               "--format=csv,noheader,nounits"]).strip()
    if not out:
        return f"{D}no NVIDIA GPU / nvidia-smi not found{X}"
    name, util, used, total, temp = [s.strip() for s in out.splitlines()[0].split(",")]
    bar = "#" * (int(util) // 5) + "." * (20 - int(util) // 5)
    colour = G if int(util) > 30 else D
    return f"{name}  {colour}[{bar}] {util}%{X}  mem {used}/{total} MiB  {temp} C"


def elapsed(p: dict) -> str:
    if p.get("etimes") is not None:
        s = int(p["etimes"])
    else:
        try:
            s = int((datetime.now() - datetime.fromisoformat(p["start"])).total_seconds())
        except (TypeError, ValueError):
            return "?"
    h, rem = divmod(max(s, 0), 3600)
    m, sec = divmod(rem, 60)
    return f"{h}h{m:02d}m{sec:02d}s" if h else f"{m}m{sec:02d}s"


def short_cmd(cmd: str) -> str:
    cmd = cmd.replace(str(ROOT), ".")
    for tail in ("experiments/phase1/", "experiments\\phase1\\"):
        cmd = cmd.replace(tail, "")
    return (cmd[:100] + "...") if len(cmd) > 103 else cmd


def verdict(rows: list[dict]) -> str:
    if any(r["method"] == "barrier" and r["violation"] > 0 for r in rows):
        return f"{R}FAIL{X} barrier violated"
    pen = max((r["violation"] for r in rows if r["method"] == "penalty"), default=0)
    if pen <= 0:
        return f"{Y}INCONCLUSIVE{X} penalty never violated"
    return f"{G}barrier held{X}, penalty max overshoot {pen:.4g} nats"


def results_lines() -> list[str]:
    files = sorted(RESULTS.glob("**/phase1*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        return [f"{D}no result files yet{X}"]
    lines = []
    for f in files[-6:]:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            m = d["meta"]
            when = datetime.fromtimestamp(f.stat().st_mtime).strftime("%d %b %H:%M")
            tag = "quick" if m.get("quick") else f"eps {m['eps']:.4g}"
            lines.append(f"{f.relative_to(RESULTS)!s:<28} {tag:<12} {m.get('device', 'cpu'):<5} {when}  {verdict(d['rows'])}")
        except (OSError, ValueError, KeyError):
            lines.append(f"{f.name}: unreadable")
    return lines


def log_tail(n: int = 4) -> list[str]:
    logs = sorted(RESULTS.glob("**/*.log"), key=lambda p: p.stat().st_mtime)
    if not logs:
        return []
    f = logs[-1]
    text = f.read_text(encoding="utf-8", errors="replace").replace("\r", "\n")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and "Loading weights" not in ln and "Warning" not in ln]
    age = int(time.time() - f.stat().st_mtime)
    return [f"{D}{f.relative_to(RESULTS)} (updated {age}s ago){X}"] + [ln[:110] for ln in lines[-n:]]


def render(tick: int) -> str:
    width = min(shutil.get_terminal_size((100, 30)).columns, 110)
    rule = D + "-" * width + X
    out = [f"{B}MIZAN live status{X}  {C}{SPIN[tick % 4]}{X}  {datetime.now():%H:%M:%S}   {D}Ctrl+C to quit{X}", rule]
    procs = processes()
    out.append(f"{B}Processes{X}")
    if procs:
        for p in procs:
            out.append(f"  {G}RUNNING{X} pid {p['pid']}  elapsed {elapsed(p)}  cpu {p['cpu']}s")
            out.append(f"    {D}{short_cmd(str(p['cmd']))}{X}")
    else:
        out.append(f"  {D}nothing running{X}")
    out += [rule, f"{B}GPU{X}", "  " + gpu(), rule, f"{B}Results{X}"]
    out += ["  " + ln for ln in results_lines()]
    tail = log_tail()
    if tail:
        out += [rule, f"{B}Latest log{X}"] + ["  " + ln for ln in tail]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=float, default=2.0)
    args = ap.parse_args()
    if os.name == "nt":
        os.system("")  # enables ANSI colours in the Windows console
    if args.once or not sys.stdout.isatty():
        print(render(0))
        return
    tick = 0
    try:
        while True:
            frame = render(tick)
            sys.stdout.write("\033[H\033[J" + frame + "\n")
            sys.stdout.flush()
            tick += 1
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
