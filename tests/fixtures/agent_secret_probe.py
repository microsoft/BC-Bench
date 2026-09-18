import json
import os
import subprocess
import sys
from pathlib import Path

processes = subprocess.run(
    [
        "pwsh",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        f"@(Get-CimInstance Win32_Process -Filter 'ProcessId={os.getpid()}'; Get-CimInstance Win32_Process -Filter 'ProcessId={os.getppid()}') | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress",
    ],
    capture_output=True,
    text=True,
    check=True,
)
files = {str(path.relative_to(Path.cwd())): path.read_text(encoding="utf-8", errors="replace") for path in Path.cwd().rglob("*") if path.is_file() and path.stat().st_size < 100_000}
protected_denied = None
if len(sys.argv) > 2:
    try:
        Path(sys.argv[2]).read_bytes()
    except PermissionError:
        protected_denied = True
    else:
        protected_denied = False
sys.stdout.write(json.dumps({"environment": dict(os.environ), "processes": json.loads(processes.stdout), "config": json.loads(sys.argv[1]), "files": files, "protected_denied": protected_denied}))
