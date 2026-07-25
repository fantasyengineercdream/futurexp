"""Local-only process supervisor for the KaleidoRoom demo."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.request import urlopen
from uuid import uuid4


HOST = "127.0.0.1"
API_PORT = 8000
WEB_PORT = 5173
REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ChildSpec:
    name: str
    command: tuple[str, ...]
    cwd: Path
    environment: dict[str, str]


class PollableProcess(Protocol):
    pid: int

    def poll(self) -> int | None: ...


class ManagedProcess(PollableProcess, Protocol):
    def wait(self, *, timeout: float) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


@dataclass(frozen=True)
class RunningChild:
    name: str
    process: ManagedProcess


class ChildExited(RuntimeError):
    pass


class ReadinessTimeout(TimeoutError):
    pass


def url_is_ready(
    url: str,
    *,
    opener: Callable[..., Any] = urlopen,
    timeout_seconds: float = 1.0,
) -> bool:
    try:
        with opener(url, timeout=timeout_seconds) as response:
            return 200 <= response.status < 400
    except OSError:
        return False


def api_command(python_executable: str) -> tuple[str, ...]:
    return (
        python_executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        HOST,
        "--port",
        str(API_PORT),
    )


def web_command() -> tuple[str, ...]:
    return (
        "npm.cmd",
        "run",
        "dev",
        "--",
        "--host",
        HOST,
        "--port",
        str(WEB_PORT),
    )


def _random_token() -> str:
    return uuid4().hex


def new_database_path(
    *,
    temp_root: Path | None = None,
    token_factory: Callable[[], str] | None = None,
) -> Path:
    root = temp_root if temp_root is not None else Path(tempfile.gettempdir())
    token = (token_factory or _random_token)()
    return root / f"kaleidoroom-demo-{token}.sqlite3"


def with_database_environment(
    base_environment: Mapping[str, str],
    database_path: Path,
) -> dict[str, str]:
    environment = dict(base_environment)
    environment["KALEIDOROOM_DB_PATH"] = str(database_path)
    return environment


def cleanup_database_files(
    database_path: Path,
    *,
    remove: Callable[[Path], None] | None = None,
) -> None:
    def unlink_if_present(path: Path) -> None:
        path.unlink(missing_ok=True)

    remover = remove or unlink_if_present
    for artifact in (
        database_path,
        Path(f"{database_path}-wal"),
        Path(f"{database_path}-shm"),
    ):
        remover(artifact)


def start_child(
    spec: ChildSpec,
    *,
    popen_factory: Callable[..., ManagedProcess] = subprocess.Popen,
    creation_flags: int | None = None,
) -> ManagedProcess:
    flags = creation_flags
    if flags is None:
        flags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            if os.name == "nt"
            else 0
        )
    return popen_factory(
        spec.command,
        cwd=spec.cwd,
        env=spec.environment,
        creationflags=flags,
    )


def stop_process_tree(
    process: ManagedProcess,
    *,
    platform: str = os.name,
    command_runner: Callable[..., Any] = subprocess.run,
    timeout_seconds: float = 5.0,
) -> None:
    if process.poll() is not None:
        return
    if platform == "nt":
        command_runner(
            ("taskkill", "/PID", str(process.pid), "/T", "/F"),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=timeout_seconds)


def finalize_run(
    children: tuple[RunningChild, ...],
    database_path: Path,
    *,
    stopper: Callable[[ManagedProcess], None],
    cleaner: Callable[[Path], None],
) -> tuple[str, ...]:
    errors: list[str] = []
    for child in reversed(children):
        try:
            stopper(child.process)
        except Exception as error:
            errors.append(f"Failed to stop {child.name}: {error}")
    try:
        cleaner(database_path)
    except Exception as error:
        errors.append(f"Failed to clean demo database: {error}")
    return tuple(errors)


def build_child_specs(
    *,
    repo_root: Path,
    python_executable: str,
    database_path: Path,
    base_environment: Mapping[str, str],
) -> tuple[ChildSpec, ChildSpec]:
    base = dict(base_environment)
    web_environment = dict(base)
    web_environment.pop("KALEIDOROOM_DB_PATH", None)
    return (
        ChildSpec(
            name="API",
            command=api_command(python_executable),
            cwd=repo_root / "services" / "api",
            environment=with_database_environment(base, database_path),
        ),
        ChildSpec(
            name="web",
            command=web_command(),
            cwd=repo_root / "apps" / "web",
            environment=web_environment,
        ),
    )


def readiness_urls() -> tuple[str, str]:
    return (
        f"http://{HOST}:{API_PORT}/docs",
        f"http://{HOST}:{WEB_PORT}/world/infinite-apartment",
    )


def direct_urls() -> tuple[tuple[str, str], ...]:
    web_origin = f"http://{HOST}:{WEB_PORT}"
    return (
        ("World", f"{web_origin}/world/infinite-apartment"),
        ("Companion", f"{web_origin}/companion/oc-user"),
        ("Proof", f"{web_origin}/proof/demo-session"),
        ("Passport", f"{web_origin}/passport/oc-user"),
    )


def wait_for_readiness(
    children: tuple[RunningChild, ...],
    urls: tuple[str, ...],
    *,
    probe: Callable[[str], bool],
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    timeout_seconds: float = 60.0,
    poll_interval_seconds: float = 0.2,
) -> None:
    pending = list(urls)
    deadline = monotonic() + timeout_seconds
    while pending:
        for child in children:
            return_code = child.process.poll()
            if return_code is not None:
                raise ChildExited(
                    f"{child.name} exited before readiness "
                    f"with status {return_code}"
                )
        pending = [url for url in pending if not probe(url)]
        if not pending:
            return
        if monotonic() >= deadline:
            raise ReadinessTimeout(
                "Timed out waiting for: " + ", ".join(pending)
            )
        sleep(poll_interval_seconds)


def monitor_children(
    children: tuple[RunningChild, ...],
    *,
    sleep: Callable[[float], None] = time.sleep,
    poll_interval_seconds: float = 0.2,
) -> None:
    while True:
        for child in children:
            return_code = child.process.poll()
            if return_code is not None:
                raise ChildExited(
                    f"{child.name} exited unexpectedly "
                    f"with status {return_code}"
                )
        sleep(poll_interval_seconds)


def _wait_for_default_readiness(
    children: tuple[RunningChild, ...],
    urls: tuple[str, ...],
) -> None:
    wait_for_readiness(children, urls, probe=url_is_ready)


def _write_error(message: str) -> None:
    print(message, file=sys.stderr)


def run_supervisor(
    *,
    repo_root: Path = REPO_ROOT,
    python_executable: str = sys.executable,
    base_environment: Mapping[str, str] = os.environ,
    database_path_factory: Callable[[], Path] = new_database_path,
    starter: Callable[[ChildSpec], ManagedProcess] = start_child,
    readiness_waiter: Callable[
        [tuple[RunningChild, ...], tuple[str, ...]], None
    ] = _wait_for_default_readiness,
    monitor: Callable[[tuple[RunningChild, ...]], None] = monitor_children,
    stopper: Callable[[ManagedProcess], None] = stop_process_tree,
    cleaner: Callable[[Path], None] = cleanup_database_files,
    write_line: Callable[[str], None] = print,
    write_error: Callable[[str], None] = _write_error,
) -> int:
    database_path = database_path_factory()
    children: list[RunningChild] = []
    try:
        specs = build_child_specs(
            repo_root=repo_root,
            python_executable=python_executable,
            database_path=database_path,
            base_environment=base_environment,
        )
        for spec in specs:
            children.append(RunningChild(spec.name, starter(spec)))
        running = tuple(children)
        readiness_waiter(running, readiness_urls())
        for label, url in direct_urls():
            write_line(f"{label}: {url}")
        monitor(running)
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        write_error(f"KaleidoRoom demo failed: {error}")
        return 1
    finally:
        for cleanup_error in finalize_run(
            tuple(children),
            database_path,
            stopper=stopper,
            cleaner=cleaner,
        ):
            write_error(cleanup_error)


def main(*, runner: Callable[[], int] = run_supervisor) -> int:
    return runner()


if __name__ == "__main__":
    raise SystemExit(main())
