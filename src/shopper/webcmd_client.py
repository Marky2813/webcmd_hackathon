"""Thin subprocess wrapper around the webcmd CLI.

Every webcmd invocation in the app goes through `run()`. That gives us one
place to enforce the payment guard, one place to handle the JSON contract, and
one place to bound how long a browser-backed command may block a Telegram turn.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from typing import Any

# Browser-backed commands (amazon-in uses the `ui` strategy) are slow. This
# bounds a single provider so one hung site can't hold up the whole reply.
DEFAULT_TIMEOUT_S = 45

# Never allowed, from any caller, for any reason. The app prepares carts and
# stops; the user completes payment themselves.
FORBIDDEN_FLAGS = frozenset({"--place-order"})

# Failure signatures worth one retry. A DNS blip hits every provider at once,
# which is indistinguishable from the app being broken.
TRANSIENT_MARKERS = (
    "ERR_NAME_NOT_RESOLVED",
    "ERR_FAILED",
    "ERR_CONNECTION",
    "ERR_TIMED_OUT",
    "ERR_NETWORK_CHANGED",
)
RETRY_DELAY_S = 1.5


class WebcmdError(RuntimeError):
    """A webcmd command failed. Carries the CLI's own message where available."""

    def __init__(self, command: str, message: str, exit_code: int | None = None):
        self.command = command
        self.exit_code = exit_code
        super().__init__(f"{command}: {message}")


class PaymentGuardError(RuntimeError):
    """Refused to run a command that would complete a purchase."""


def _resolve_binary() -> str:
    path = shutil.which("webcmd")
    if not path:
        raise WebcmdError("webcmd", "CLI not found on PATH — is webcmd installed?")
    return path


def _is_transient(detail: str) -> bool:
    """Did this fail for a reason that might not repeat?

    A DNS hiccup takes down every site at once and looks identical to the app
    being broken. One cheap retry turns that into a blip instead of an empty
    reply mid-demo.
    """
    return any(marker in detail for marker in TRANSIENT_MARKERS)


def _invoke(
    site: str, command: str, argv: list[str], timeout: int
) -> subprocess.CompletedProcess[str]:
    """Guard, execute, retry once on transient failure, then raise."""
    forbidden = FORBIDDEN_FLAGS.intersection(argv)
    if forbidden:
        raise PaymentGuardError(
            f"Refusing to run {site} {command} with {sorted(forbidden)}. "
            "This app never completes a purchase."
        )

    label = f"{site} {command}"
    full = [_resolve_binary(), site, command, *argv]

    for attempt in range(2):
        try:
            proc = subprocess.run(
                full,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired as exc:
            raise WebcmdError(label, f"timed out after {timeout}s") from exc

        if proc.returncode == 0:
            return proc

        detail = (proc.stderr or proc.stdout or "").strip()
        if attempt == 0 and _is_transient(detail):
            time.sleep(RETRY_DELAY_S)
            continue

        raise WebcmdError(label, _first_message(detail), proc.returncode)

    raise WebcmdError(label, "exhausted retries")


def run_raw(
    site: str,
    command: str,
    *args: str,
    timeout: int = DEFAULT_TIMEOUT_S,
) -> str:
    """Run a webcmd command and return stdout verbatim, without `-f json`.

    Used for `web fetch-browser --stdout`, which emits Markdown rather than
    structured rows. Subject to the same payment guard as `run()`.
    """
    return _invoke(site, command, [str(a) for a in args], timeout).stdout or ""


def run(
    site: str,
    command: str,
    *args: str,
    timeout: int = DEFAULT_TIMEOUT_S,
) -> list[dict[str, Any]]:
    """Run `webcmd <site> <command> [args] -f json` and parse the result.

    Args:
        site: The webcmd site, e.g. "amazon-in".
        command: The command name, e.g. "search".
        *args: Positional and flag arguments, already stringified.
        timeout: Seconds before the command is killed.

    Returns:
        The parsed JSON rows. webcmd returns a list for table-shaped commands;
        a bare object is wrapped so callers always get a list.

    Raises:
        PaymentGuardError: If any argument would submit an order.
        WebcmdError: If the command fails, times out, or returns non-JSON.
    """
    argv = [str(a) for a in args] + ["-f", "json"]
    label = f"{site} {command}"

    proc = _invoke(site, command, argv, timeout)
    stdout = (proc.stdout or "").strip()
    if not stdout:
        return []

    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise WebcmdError(label, f"expected JSON, got: {stdout[:200]}") from exc

    if isinstance(parsed, dict):
        return [parsed]
    return parsed


def _first_message(stderr: str) -> str:
    """Pull the human-readable line out of webcmd's YAML error block."""
    for line in stderr.splitlines():
        line = line.strip()
        if line.startswith("message:"):
            return line.removeprefix("message:").strip()
    return stderr.splitlines()[0] if stderr else "unknown error"
