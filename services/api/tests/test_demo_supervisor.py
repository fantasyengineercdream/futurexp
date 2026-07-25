from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

from app import demo_supervisor


def test_demo_supervisor_module_exists_for_python_m_execution() -> None:
    assert importlib.util.find_spec("app.demo_supervisor") is not None


def test_child_commands_bind_only_to_loopback() -> None:
    assert demo_supervisor.api_command("python.exe") == (
        "python.exe",
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    )
    assert demo_supervisor.web_command() == (
        "npm.cmd",
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        "5173",
    )


def test_each_database_path_is_unique_and_only_added_to_api_environment(
    tmp_path: Path,
) -> None:
    tokens = iter(("first-run", "second-run"))
    base_environment = {"PATH": "keep-me"}

    first = demo_supervisor.new_database_path(
        temp_root=tmp_path,
        token_factory=lambda: next(tokens),
    )
    second = demo_supervisor.new_database_path(
        temp_root=tmp_path,
        token_factory=lambda: next(tokens),
    )
    api_environment = demo_supervisor.with_database_environment(
        base_environment,
        first,
    )

    assert first == tmp_path / "kaleidoroom-demo-first-run.sqlite3"
    assert second == tmp_path / "kaleidoroom-demo-second-run.sqlite3"
    assert first != second
    assert api_environment == {
        "PATH": "keep-me",
        "KALEIDOROOM_DB_PATH": str(first),
    }
    assert base_environment == {"PATH": "keep-me"}


def test_child_specs_use_api_and_web_working_directories(tmp_path: Path) -> None:
    database_path = tmp_path / "run.sqlite3"

    api, web = demo_supervisor.build_child_specs(
        repo_root=tmp_path,
        python_executable="python.exe",
        database_path=database_path,
        base_environment={
            "PATH": "tools",
            "KALEIDOROOM_DB_PATH": "stale.sqlite3",
        },
    )

    assert api.name == "API"
    assert api.cwd == tmp_path / "services" / "api"
    assert api.command == demo_supervisor.api_command("python.exe")
    assert api.environment["KALEIDOROOM_DB_PATH"] == str(database_path)
    assert web.name == "web"
    assert web.cwd == tmp_path / "apps" / "web"
    assert web.command == demo_supervisor.web_command()
    assert "KALEIDOROOM_DB_PATH" not in web.environment


def test_readiness_and_direct_urls_are_local_only() -> None:
    assert demo_supervisor.readiness_urls() == (
        "http://127.0.0.1:8000/docs",
        "http://127.0.0.1:5173/world/infinite-apartment",
    )
    assert demo_supervisor.direct_urls() == (
        ("World", "http://127.0.0.1:5173/world/infinite-apartment"),
        ("Companion", "http://127.0.0.1:5173/companion/oc-user"),
        ("Proof", "http://127.0.0.1:5173/proof/demo-session"),
        ("Passport", "http://127.0.0.1:5173/passport/oc-user"),
    )


class FakeProcess:
    def __init__(self, return_code: int | None = None, *, pid: int = 1234) -> None:
        self.return_code = return_code
        self.pid = pid

    def poll(self) -> int | None:
        return self.return_code


def test_wait_for_readiness_polls_each_pending_url() -> None:
    attempts: dict[str, int] = {}
    sleeps: list[float] = []
    urls = ("api-docs", "world-page")

    def probe(url: str) -> bool:
        attempts[url] = attempts.get(url, 0) + 1
        return url == "api-docs" or attempts[url] >= 2

    demo_supervisor.wait_for_readiness(
        (
            demo_supervisor.RunningChild("API", FakeProcess()),
            demo_supervisor.RunningChild("web", FakeProcess()),
        ),
        urls,
        probe=probe,
        monotonic=lambda: 0.0,
        sleep=sleeps.append,
        timeout_seconds=5.0,
        poll_interval_seconds=0.1,
    )

    assert attempts == {"api-docs": 1, "world-page": 2}
    assert sleeps == [0.1]


def test_wait_for_readiness_fails_if_a_child_exits_early() -> None:
    children = (
        demo_supervisor.RunningChild("API", FakeProcess(return_code=3)),
        demo_supervisor.RunningChild("web", FakeProcess()),
    )

    with pytest.raises(
        RuntimeError,
        match="API exited before readiness with status 3",
    ):
        demo_supervisor.wait_for_readiness(
            children,
            ("api-docs", "world-page"),
            probe=lambda _url: True,
        )


def test_wait_for_readiness_times_out_with_pending_urls() -> None:
    clock = iter((0.0, 6.0))

    with pytest.raises(
        TimeoutError,
        match="Timed out waiting for: world-page",
    ):
        demo_supervisor.wait_for_readiness(
            (demo_supervisor.RunningChild("web", FakeProcess()),),
            ("world-page",),
            probe=lambda _url: False,
            monotonic=lambda: next(clock),
            sleep=lambda _seconds: pytest.fail("poll continued past deadline"),
            timeout_seconds=5.0,
        )


def test_url_readiness_probe_is_injectable() -> None:
    assert callable(getattr(demo_supervisor, "url_is_ready", None))


class FakeHttpResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> FakeHttpResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_url_readiness_probe_accepts_successful_http_response() -> None:
    calls: list[tuple[str, float]] = []

    def opener(url: str, *, timeout: float) -> FakeHttpResponse:
        calls.append((url, timeout))
        return FakeHttpResponse(200)

    assert demo_supervisor.url_is_ready(
        "http://127.0.0.1:8000/docs",
        opener=opener,
        timeout_seconds=0.25,
    )
    assert calls == [("http://127.0.0.1:8000/docs", 0.25)]


def test_url_readiness_probe_retries_connection_errors() -> None:
    def unavailable(_url: str, *, timeout: float) -> FakeHttpResponse:
        raise OSError(f"not listening after {timeout}")

    try:
        ready = demo_supervisor.url_is_ready("api-docs", opener=unavailable)
    except OSError as error:
        pytest.fail(f"probe leaked a retryable error: {error}")

    assert ready is False


def test_url_readiness_probe_rejects_unsuccessful_http_response() -> None:
    assert (
        demo_supervisor.url_is_ready(
            "world-page",
            opener=lambda _url, *, timeout: FakeHttpResponse(503),
        )
        is False
    )


def test_database_cleanup_is_injectable() -> None:
    assert callable(getattr(demo_supervisor, "cleanup_database_files", None))


def test_database_cleanup_deletes_only_this_runs_sqlite_artifacts(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "kaleidoroom-demo-this-run.sqlite3"
    artifacts = (
        database_path,
        Path(f"{database_path}-wal"),
        Path(f"{database_path}-shm"),
    )
    for artifact in artifacts:
        artifact.write_text("demo", encoding="utf-8")
    unrelated = tmp_path / "kaleidoroom-demo-another-run.sqlite3"
    unrelated.write_text("keep", encoding="utf-8")

    demo_supervisor.cleanup_database_files(database_path)

    assert all(not artifact.exists() for artifact in artifacts)
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_process_lifecycle_helpers_are_injectable() -> None:
    assert callable(getattr(demo_supervisor, "start_child", None))
    assert callable(getattr(demo_supervisor, "stop_process_tree", None))
    assert callable(getattr(demo_supervisor, "finalize_run", None))


def test_start_child_uses_spec_without_a_process_scanning_shell(
    tmp_path: Path,
) -> None:
    spec = demo_supervisor.ChildSpec(
        name="API",
        command=("python.exe", "-m", "uvicorn"),
        cwd=tmp_path,
        environment={"KALEIDOROOM_DB_PATH": "run.sqlite3"},
    )
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []
    process = FakeProcess()

    def popen_factory(
        command: tuple[str, ...],
        **kwargs: object,
    ) -> FakeProcess:
        calls.append((command, kwargs))
        return process

    try:
        started = demo_supervisor.start_child(
            spec,
            popen_factory=popen_factory,
            creation_flags=42,
        )
    except NotImplementedError:
        pytest.fail("start_child did not launch its declared child")

    assert started is process
    assert calls == [
        (
            spec.command,
            {
                "cwd": spec.cwd,
                "env": spec.environment,
                "creationflags": 42,
            },
        )
    ]


class FakeStoppableProcess(FakeProcess):
    def __init__(self, *, pid: int = 4321) -> None:
        super().__init__(pid=pid)
        self.wait_timeouts: list[float] = []
        self.terminate_calls = 0
        self.kill_calls = 0

    def wait(self, *, timeout: float) -> int:
        self.wait_timeouts.append(timeout)
        self.return_code = 0
        return 0

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1


class FakeHungProcess(FakeStoppableProcess):
    def wait(self, *, timeout: float) -> int:
        self.wait_timeouts.append(timeout)
        if len(self.wait_timeouts) == 1:
            raise demo_supervisor.subprocess.TimeoutExpired(
                cmd=str(self.pid),
                timeout=timeout,
            )
        self.return_code = -9
        return -9


def test_windows_stop_targets_only_the_known_child_tree() -> None:
    process = FakeStoppableProcess(pid=4321)
    commands: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def command_runner(
        command: tuple[str, ...],
        **kwargs: object,
    ) -> object:
        commands.append((command, kwargs))
        return object()

    demo_supervisor.stop_process_tree(
        process,
        platform="nt",
        command_runner=command_runner,
        timeout_seconds=2.5,
    )

    assert commands == [
        (
            ("taskkill", "/PID", "4321", "/T", "/F"),
            {
                "check": False,
                "stdout": demo_supervisor.subprocess.DEVNULL,
                "stderr": demo_supervisor.subprocess.DEVNULL,
            },
        )
    ]
    assert process.wait_timeouts == [2.5]
    assert process.terminate_calls == 0


def test_windows_stop_force_kills_the_known_parent_if_tree_wait_hangs() -> None:
    process = FakeHungProcess(pid=7654)

    try:
        demo_supervisor.stop_process_tree(
            process,
            platform="nt",
            command_runner=lambda _command, **_kwargs: object(),
            timeout_seconds=1.5,
        )
    except demo_supervisor.subprocess.TimeoutExpired as error:
        pytest.fail(f"known child was left running: {error}")

    assert process.kill_calls == 1
    assert process.wait_timeouts == [1.5, 1.5]


def test_finalize_run_attempts_both_children_and_database_after_stop_error(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "run.sqlite3"
    children = (
        demo_supervisor.RunningChild("API", FakeStoppableProcess(pid=1)),
        demo_supervisor.RunningChild("web", FakeStoppableProcess(pid=2)),
    )
    stopped: list[int] = []
    cleaned: list[Path] = []

    def stopper(process: FakeStoppableProcess) -> None:
        stopped.append(process.pid)
        if process.pid == 2:
            raise OSError("access denied")

    errors = demo_supervisor.finalize_run(
        children,
        database_path,
        stopper=stopper,
        cleaner=cleaned.append,
    )

    assert stopped == [2, 1]
    assert cleaned == [database_path]
    assert errors == ("Failed to stop web: access denied",)


def test_stop_process_tree_leaves_an_exited_child_alone() -> None:
    process = FakeStoppableProcess()
    process.return_code = 0
    commands: list[tuple[str, ...]] = []

    demo_supervisor.stop_process_tree(
        process,
        platform="nt",
        command_runner=lambda command, **_kwargs: commands.append(command),
    )

    assert commands == []
    assert process.wait_timeouts == []


def test_child_monitor_is_injectable() -> None:
    assert callable(getattr(demo_supervisor, "monitor_children", None))


def test_child_monitor_reports_any_early_exit() -> None:
    children = (
        demo_supervisor.RunningChild("API", FakeProcess()),
        demo_supervisor.RunningChild("web", FakeProcess(return_code=9)),
    )

    with pytest.raises(
        RuntimeError,
        match="web exited unexpectedly with status 9",
    ):
        demo_supervisor.monitor_children(
            children,
            sleep=lambda _seconds: pytest.fail("exit was not detected"),
        )


def test_supervisor_orchestration_is_injectable() -> None:
    assert callable(getattr(demo_supervisor, "run_supervisor", None))
    assert callable(getattr(demo_supervisor, "main", None))


def test_main_returns_supervisor_status() -> None:
    assert demo_supervisor.main(runner=lambda: 17) == 17


def test_module_execution_exits_with_main_status() -> None:
    tree = ast.parse(
        Path(demo_supervisor.__file__).read_text(encoding="utf-8")
    )
    module_guards = [
        node
        for node in tree.body
        if isinstance(node, ast.If)
        and "__name__" in ast.unparse(node.test)
        and "__main__" in ast.unparse(node.test)
    ]

    assert len(module_guards) == 1
    assert "raise SystemExit(main())" in ast.unparse(module_guards[0])


def test_ctrl_c_stops_both_children_cleans_database_and_returns_success(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "this-run.sqlite3"
    processes = {
        "API": FakeStoppableProcess(pid=101),
        "web": FakeStoppableProcess(pid=202),
    }
    started: list[demo_supervisor.ChildSpec] = []
    stopped: list[int] = []
    cleaned: list[Path] = []
    output: list[str] = []

    def starter(spec: demo_supervisor.ChildSpec) -> FakeStoppableProcess:
        started.append(spec)
        return processes[spec.name]

    def readiness_waiter(
        children: tuple[demo_supervisor.RunningChild, ...],
        urls: tuple[str, ...],
    ) -> None:
        assert tuple(child.name for child in children) == ("API", "web")
        assert urls == demo_supervisor.readiness_urls()

    status = demo_supervisor.run_supervisor(
        repo_root=tmp_path,
        python_executable="python.exe",
        base_environment={"PATH": "tools"},
        database_path_factory=lambda: database_path,
        starter=starter,
        readiness_waiter=readiness_waiter,
        monitor=lambda _children: (_ for _ in ()).throw(KeyboardInterrupt),
        stopper=lambda process: stopped.append(process.pid),
        cleaner=cleaned.append,
        write_line=output.append,
        write_error=lambda message: pytest.fail(message),
    )

    assert status == 0
    assert [spec.name for spec in started] == ["API", "web"]
    assert output == [
        f"{label}: {url}" for label, url in demo_supervisor.direct_urls()
    ]
    assert stopped == [202, 101]
    assert cleaned == [database_path]


def test_early_child_exit_stops_peer_and_returns_nonzero(tmp_path: Path) -> None:
    database_path = tmp_path / "failed-run.sqlite3"
    processes = {
        "API": FakeStoppableProcess(pid=303),
        "web": FakeStoppableProcess(pid=404),
    }
    stopped: list[int] = []
    cleaned: list[Path] = []
    output: list[str] = []
    errors: list[str] = []

    def fail_readiness(
        _children: tuple[demo_supervisor.RunningChild, ...],
        _urls: tuple[str, ...],
    ) -> None:
        raise demo_supervisor.ChildExited(
            "API exited before readiness with status 2"
        )

    try:
        status = demo_supervisor.run_supervisor(
            repo_root=tmp_path,
            database_path_factory=lambda: database_path,
            starter=lambda spec: processes[spec.name],
            readiness_waiter=fail_readiness,
            monitor=lambda _children: pytest.fail("monitor must not start"),
            stopper=lambda process: stopped.append(process.pid),
            cleaner=cleaned.append,
            write_line=output.append,
            write_error=errors.append,
        )
    except demo_supervisor.ChildExited as error:
        pytest.fail(f"supervisor leaked child failure: {error}")

    assert status == 1
    assert output == []
    assert errors == [
        "KaleidoRoom demo failed: API exited before readiness with status 2"
    ]
    assert stopped == [404, 303]
    assert cleaned == [database_path]


def test_second_child_start_failure_stops_first_and_cleans_database(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "partial-run.sqlite3"
    api_process = FakeStoppableProcess(pid=707)
    stopped: list[int] = []
    cleaned: list[Path] = []
    errors: list[str] = []

    def starter(spec: demo_supervisor.ChildSpec) -> FakeStoppableProcess:
        if spec.name == "web":
            raise OSError("npm.cmd unavailable")
        return api_process

    status = demo_supervisor.run_supervisor(
        repo_root=tmp_path,
        database_path_factory=lambda: database_path,
        starter=starter,
        readiness_waiter=lambda _children, _urls: pytest.fail(
            "readiness must not start"
        ),
        monitor=lambda _children: pytest.fail("monitor must not start"),
        stopper=lambda process: stopped.append(process.pid),
        cleaner=cleaned.append,
        write_line=lambda _line: None,
        write_error=errors.append,
    )

    assert status == 1
    assert stopped == [707]
    assert cleaned == [database_path]
    assert errors == ["KaleidoRoom demo failed: npm.cmd unavailable"]


def test_supervisor_finally_continues_after_one_stop_error(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "cleanup-run.sqlite3"
    processes = {
        "API": FakeStoppableProcess(pid=505),
        "web": FakeStoppableProcess(pid=606),
    }
    stopped: list[int] = []
    cleaned: list[Path] = []
    errors: list[str] = []

    def stopper(process: FakeStoppableProcess) -> None:
        stopped.append(process.pid)
        if process.pid == 606:
            raise OSError("cannot stop")

    try:
        status = demo_supervisor.run_supervisor(
            repo_root=tmp_path,
            database_path_factory=lambda: database_path,
            starter=lambda spec: processes[spec.name],
            readiness_waiter=lambda _children, _urls: None,
            monitor=lambda _children: (_ for _ in ()).throw(KeyboardInterrupt),
            stopper=stopper,
            cleaner=cleaned.append,
            write_line=lambda _line: None,
            write_error=errors.append,
        )
    except OSError as error:
        pytest.fail(f"finally stopped after one cleanup error: {error}")

    assert status == 0
    assert stopped == [606, 505]
    assert cleaned == [database_path]
    assert errors == ["Failed to stop web: cannot stop"]
