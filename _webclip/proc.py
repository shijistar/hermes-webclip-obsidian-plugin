"""Bounded subprocess execution and decoding."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from typing import Sequence
import os
import signal
import subprocess
import threading

from .core import ClipError

@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes


def _run_bounded(
    command: Sequence[str],
    *,
    timeout: int,
    stdout_limit: int,
    stderr_limit: int,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> ProcessResult:
    """Run without a shell while draining pipes into strictly capped buffers."""
    if not isinstance(command, (list, tuple)) or not all(
        isinstance(part, str) for part in command
    ):
        raise ClipError("Internal command construction failed.")
    try:
        process = subprocess.Popen(
            list(command),
            cwd=str(cwd) if cwd is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=dict(env) if env is not None else None,
            start_new_session=True,
        )
    except OSError as exc:
        raise ClipError("A required local command could not be started.") from exc

    stdout_buffer = bytearray()
    stderr_buffer = bytearray()
    exceeded = threading.Event()
    termination_lock = threading.Lock()

    def terminate_group() -> None:
        with termination_lock:
            if process.poll() is not None:
                return
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass
            try:
                process.wait(timeout=1)
                return
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

    def drain(stream, buffer: bytearray, limit: int) -> None:
        if stream is None:
            return
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                return
            remaining = limit - len(buffer)
            if remaining > 0:
                buffer.extend(chunk[:remaining])
            if len(chunk) > remaining:
                exceeded.set()
                terminate_group()
                return

    threads = [
        threading.Thread(
            target=drain, args=(process.stdout, stdout_buffer, stdout_limit), daemon=True
        ),
        threading.Thread(
            target=drain, args=(process.stderr, stderr_buffer, stderr_limit), daemon=True
        ),
    ]
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        terminate_group()
        returncode = process.returncode if process.returncode is not None else -1
    finally:
        for thread in threads:
            thread.join(timeout=2)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
    if timed_out:
        raise ClipError("The local command timed out.")
    if exceeded.is_set():
        raise ClipError("The local command returned too much output.")
    return ProcessResult(returncode, bytes(stdout_buffer), bytes(stderr_buffer))


def _decode_output(result: ProcessResult) -> str:
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ClipError("Git returned an invalid local response.") from exc
