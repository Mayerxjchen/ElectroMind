"""容器运行时探测。"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Literal

_TIMEOUT = 10


@dataclass(frozen=True)
class RuntimeProbeResult:
    runtime: Literal["docker", "podman"]
    usable: bool
    executable_found: bool
    service_reachable: bool
    error_code: str | None
    message: str


class ContainerRuntimeProbe:
    def probe(self, runtime: Literal["docker", "podman"]) -> RuntimeProbeResult:
        exe = shutil.which(runtime)
        if exe is None:
            return RuntimeProbeResult(
                runtime=runtime,
                usable=False,
                executable_found=False,
                service_reachable=False,
                error_code="executable_not_found",
                message=f"{runtime} executable not found on PATH",
            )
        reachable, code, msg = _check_daemon(runtime)
        return RuntimeProbeResult(
            runtime=runtime,
            usable=reachable,
            executable_found=True,
            service_reachable=reachable,
            error_code=code,
            message=msg,
        )


def _check_daemon(runtime: str) -> tuple[bool, str | None, str]:
    try:
        r = subprocess.run(
            [runtime, "info"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            check=False,
        )
        if r.returncode == 0:
            return True, None, f"{runtime} daemon reachable"
        return (
            False,
            "daemon_unreachable",
            r.stderr.strip() or f"{runtime} info returned {r.returncode}",
        )
    except subprocess.TimeoutExpired:
        return False, "daemon_timeout", f"{runtime} info timed out"
    except PermissionError:
        return False, "permission_denied", f"{runtime}: permission denied"
    except (FileNotFoundError, OSError):
        return False, "executable_not_found", f"{runtime}: executable not found"
