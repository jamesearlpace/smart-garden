"""Smart Garden Server — Main entry point.

Runs the scheduler, irrigation engine, and Flask dashboard.
Designed to run as a systemd service on the Acer home server.
"""

import logging
from logging.handlers import RotatingFileHandler
import fcntl
from functools import wraps
import http.client
import errno
import os
import sys
import signal
import subprocess
import threading
import time
from datetime import datetime, timedelta

import yaml
from apscheduler.schedulers.background import BackgroundScheduler

import database as db
from weather import WeatherClient
from billing import BillingCalculator
from irrigation import IrrigationEngine

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Logging ──

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            os.path.join(BASE_DIR, "smart-garden.log"),
            maxBytes=5_000_000, backupCount=3
        ),
    ],
)
# Quiet noisy third-party loggers — urllib3 logs every retry as WARNING which spams
# logs when ESP32 is flaky. Our irrigation.py already logs the consolidated result.
logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)
log = logging.getLogger("smart-garden")
_LOCK_FH = None
STALE_STARTUP_GRACE_SECONDS = 120
_API_HEALTH_CHECK_LOCK = threading.Lock()


def load_config() -> dict:
    config_path = os.path.join(BASE_DIR, "config.yaml")
    last_error = None
    for attempt in range(5):
        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)
            if not isinstance(config, dict):
                raise ValueError("config.yaml did not contain a mapping")
            for key in ("zones", "location", "esp32", "dashboard"):
                if key not in config:
                    raise ValueError(f"config.yaml missing required key: {key}")
            return config
        except (OSError, ValueError, yaml.YAMLError) as exc:
            last_error = exc
            if attempt == 4:
                break
            log.warning(
                "Config load failed during startup (%s); retrying",
                exc,
            )
            time.sleep(0.5)
    raise RuntimeError(f"Unable to load config.yaml: {last_error}") from last_error


def _try_lock(fh) -> bool:
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _write_lock_pid(fh) -> None:
    fh.seek(0)
    fh.write(str(os.getpid()))
    fh.truncate()
    fh.flush()


def _read_lock_pid(fh) -> int | None:
    try:
        fh.seek(0)
        raw = fh.read().strip()
        return int(raw) if raw else None
    except (OSError, ValueError):
        return None


def _open_lock_file(path: str):
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    return os.fdopen(fd, "r+")


def _clear_dead_lock_pid(path: str) -> None:
    """Remove stale PID text when no process actually holds the flock."""
    if _lock_holder_pids_from_proc_locks(path):
        return

    try:
        with _open_lock_file(path) as fh:
            holder_pid = _read_lock_pid(fh)
            if holder_pid and _process_exists(holder_pid):
                return
            fh.seek(0)
            fh.truncate()
            fh.flush()
    except OSError:
        pass


def _lock_holder_pids_from_proc_locks(path: str) -> list[int]:
    """Return PID(s) holding the lock file according to /proc/locks."""
    try:
        stat = os.stat(path)
        lock_key = (
            f"{os.major(stat.st_dev):02x}:"
            f"{os.minor(stat.st_dev):02x}:"
            f"{stat.st_ino}"
        )
        with open("/proc/locks", "r") as f:
            lines = f.readlines()
    except OSError:
        return []

    pids = []
    for line in lines:
        parts = line.split()
        if len(parts) < 6 or parts[5] != lock_key:
            continue
        try:
            pid = int(parts[4])
        except ValueError:
            continue
        if pid > 0 and pid != os.getpid():
            pids.append(pid)
    return sorted(set(pids))


def _process_exists(pid: int) -> bool:
    try:
        with open(f"/proc/{pid}/stat", "r") as f:
            parts = f.read().split()
        if len(parts) >= 3 and parts[2] in {"Z", "X"}:
            return False
    except OSError:
        return False

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_age_seconds(pid: int) -> float | None:
    try:
        with open(f"/proc/{pid}/stat", "r") as f:
            parts = f.read().split()
        with open("/proc/uptime", "r") as f:
            uptime = float(f.read().split()[0])
        clock_ticks = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        start_time = int(parts[21]) / clock_ticks
    except (OSError, IndexError, KeyError, TypeError, ValueError):
        return None
    return max(0.0, uptime - start_time)


def _is_smart_garden_process(pid: int) -> bool:
    try:
        proc_cwd = os.readlink(f"/proc/{pid}/cwd")
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmdline = f.read().decode("utf-8", errors="replace")
    except OSError:
        return False

    service_dir = BASE_DIR
    server_path = os.path.join(service_dir, "server.py")
    cmd_parts = [part for part in cmdline.split("\0") if part]
    server_realpath = os.path.realpath(server_path)
    has_server_arg = False
    server_arg_points_here = False
    for part in cmd_parts:
        if os.path.basename(part) != "server.py":
            continue
        if part == "server.py" or part == server_path:
            has_server_arg = True
            server_arg_points_here = part == server_path
            break
        if os.path.isabs(part):
            has_server_arg = os.path.realpath(part) == server_realpath
            server_arg_points_here = has_server_arg
        else:
            has_server_arg = (
                os.path.realpath(os.path.join(proc_cwd, part))
                == server_realpath
            )
        if has_server_arg:
            break
    return has_server_arg and (proc_cwd == service_dir or server_arg_points_here)


def _smart_garden_child_pids(parent_pid: int) -> list[int]:
    try:
        output = subprocess.check_output(
            ["pgrep", "-P", str(parent_pid)],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except (subprocess.SubprocessError, OSError):
        return []

    pids = []
    for raw_pid in output.split():
        try:
            pid = int(raw_pid)
        except ValueError:
            continue
        if _is_smart_garden_process(pid):
            pids.append(pid)
    return pids


def _smart_garden_process_pids() -> list[int]:
    """Return same-directory Smart Garden server.py processes, excluding self."""
    pids = []
    for name in os.listdir("/proc"):
        try:
            pid = int(name)
        except ValueError:
            continue
        if pid == os.getpid():
            continue
        if _is_smart_garden_process(pid):
            pids.append(pid)
    return sorted(pids)


def _smart_garden_lock_pid_candidates() -> list[int]:
    """Return verified Smart Garden PIDs associated with the scheduler lock."""
    lock_path = os.path.join(BASE_DIR, ".smart-garden-api.lock")
    candidates = []
    try:
        with _open_lock_file(lock_path) as lock_fh:
            readable_lock_pid = _read_lock_pid(lock_fh)
    except OSError:
        readable_lock_pid = None

    if readable_lock_pid and readable_lock_pid != os.getpid():
        candidates.append(readable_lock_pid)
    candidates.extend(_lock_holder_pids_from_proc_locks(lock_path))
    return sorted({
        pid for pid in candidates
        if pid != os.getpid() and _is_smart_garden_process(pid)
    })


def _smart_garden_peer_pids_for_cleanup() -> list[int]:
    """Return verified peer PIDs using both process scan and lock evidence."""
    return sorted(set(
        _smart_garden_process_pids()
        + _smart_garden_lock_pid_candidates()
    ))


def _listener_is_lan_reachable(proc_net_path: str, local_hex: str) -> bool:
    """Return True when a listener is reachable beyond loopback."""
    raw = local_hex.upper()
    if proc_net_path.endswith("tcp"):
        # /proc/net/tcp stores IPv4 addresses as little-endian hex. 0.0.0.0 is
        # reachable on all interfaces; 127.0.0.0/8 ends with 7F in this format.
        return raw == "00000000" or not raw.endswith("7F")

    if set(raw) == {"0"}:
        return True

    # /proc/net/tcp6 stores the IPv6 loopback address as 000...01000000.
    return raw != "00000000000000000000000001000000"


def _listening_socket_inodes(port: int) -> dict[str, bool] | None:
    """Return listener socket inodes mapped to whether they are LAN-reachable."""
    inodes = {}
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(path, "r") as f:
                lines = f.readlines()[1:]
        except OSError:
            return None

        for line in lines:
            parts = line.split()
            if len(parts) < 10:
                continue
            local_address = parts[1]
            state = parts[3]
            inode = parts[9]
            try:
                raw_host, raw_port = local_address.rsplit(":", 1)
                local_port = int(raw_port, 16)
            except (IndexError, ValueError):
                continue
            if local_port == port and state == "0A":  # TCP_LISTEN
                inodes[inode] = _listener_is_lan_reachable(path, raw_host)
    return inodes


def _process_socket_inodes(pid: int) -> set[str]:
    inodes = set()
    fd_dir = f"/proc/{pid}/fd"
    try:
        fd_names = os.listdir(fd_dir)
    except OSError:
        return inodes

    for fd_name in fd_names:
        try:
            target = os.readlink(os.path.join(fd_dir, fd_name))
        except OSError:
            continue
        if target.startswith("socket:[") and target.endswith("]"):
            inodes.add(target[len("socket:["):-1])
    return inodes


def _pid_listens_on_port(pid: int, port_inodes: dict[str, bool]) -> bool:
    return bool(_process_socket_inodes(pid) & set(port_inodes))


def _pid_has_lan_reachable_listener(pid: int, port_inodes: dict[str, bool]) -> bool:
    return any(
        port_inodes.get(inode, False)
        for inode in _process_socket_inodes(pid)
    )


def _current_process_has_lan_reachable_listener(port: int) -> bool | None:
    port_inodes = _listening_socket_inodes(port)
    if port_inodes is None:
        return None
    return _pid_has_lan_reachable_listener(os.getpid(), port_inodes)


def _current_process_listener_state(port: int) -> str | None:
    """Return lan, loopback, none, or None when listener state is unknown."""
    port_inodes = _listening_socket_inodes(port)
    if port_inodes is None:
        return None

    current_inodes = _process_socket_inodes(os.getpid())
    matching_inodes = current_inodes & set(port_inodes)
    if not matching_inodes:
        return "none"
    if any(port_inodes.get(inode, False) for inode in matching_inodes):
        return "lan"
    return "loopback"


def _confirm_missing_lan_reachable_listener(port: int) -> bool:
    """Return True only after repeated checks show this process has no LAN listener."""
    for _ in range(3):
        has_listener = _current_process_has_lan_reachable_listener(port)
        if has_listener is None:
            return False
        if has_listener:
            return False
        time.sleep(1)
    return True


def _recover_stale_processes_before_bind(port: int) -> bool:
    """Stop verified same-project processes before taking over the API port.

    Return True when this startup should exit. This pre-bind path stops stale
    API port owners and old headless runtimes, but only continues into the
    Waitress bind after the verified stale process has actually exited.
    """
    port_inodes = _listening_socket_inodes(port)
    if port_inodes is None:
        log.warning(
            "Could not inspect /proc TCP listeners before API bind; "
            "skipping pre-bind stale-process recovery"
        )
        return False

    lock_path = os.path.join(BASE_DIR, ".smart-garden-api.lock")
    _clear_dead_lock_pid(lock_path)
    try:
        with _open_lock_file(lock_path) as lock_fh:
            readable_lock_pid = _read_lock_pid(lock_fh)
    except OSError:
        readable_lock_pid = None
    lock_holder_candidates = [
        pid for pid in _lock_holder_pids_from_proc_locks(lock_path)
        if _is_smart_garden_process(pid)
    ]
    if (
        readable_lock_pid
        and readable_lock_pid != os.getpid()
        and _is_smart_garden_process(readable_lock_pid)
    ):
        lock_holder_candidates.append(readable_lock_pid)
        lock_holder_candidates = sorted(set(lock_holder_candidates))
    same_project_candidates = _smart_garden_process_pids()
    candidate_pool = sorted(set(lock_holder_candidates + same_project_candidates))
    if not candidate_pool:
        return False

    port_listening_candidates = [
        pid for pid in candidate_pool if _pid_listens_on_port(pid, port_inodes)
    ]

    non_blocking_candidates = [
        pid for pid in candidate_pool
        if pid not in lock_holder_candidates + port_listening_candidates
    ]
    stale_non_blocking_candidates = [
        pid for pid in non_blocking_candidates
        if (_process_age_seconds(pid) or 0) >= STALE_STARTUP_GRACE_SECONDS
    ]
    stale_lock_holder_candidates = [
        pid for pid in lock_holder_candidates
        if (
            pid not in port_listening_candidates
            and (_process_age_seconds(pid) or 0) >= STALE_STARTUP_GRACE_SECONDS
        )
    ]
    fresh_non_blocking_candidates = [
        pid for pid in non_blocking_candidates
        if pid not in stale_non_blocking_candidates
    ]
    if fresh_non_blocking_candidates:
        log.warning(
            "Found Smart Garden process(es) without the scheduler lock or a "
            "port %s listener before API bind; leaving non-blocking pid(s) "
            "alone to avoid killing an overlapping startup: %s",
            port,
            ", ".join(str(pid) for pid in fresh_non_blocking_candidates),
        )
    if stale_non_blocking_candidates:
        log.warning(
            "Found stale Smart Garden startup process(es) older than %ss "
            "without the scheduler lock or a port %s listener; requesting "
            "pre-bind cleanup so old scheduler-only runtimes cannot survive "
            "another watchdog restart for pid(s): %s",
            STALE_STARTUP_GRACE_SECONDS,
            port,
            ", ".join(str(pid) for pid in stale_non_blocking_candidates),
        )
    if stale_lock_holder_candidates:
        log.warning(
            "Found stale Smart Garden scheduler-lock holder(s) older than %ss "
            "without a port %s listener before API bind; requesting cleanup "
            "before binding so scheduler-only runtimes cannot survive another "
            "watchdog restart for pid(s): %s",
            STALE_STARTUP_GRACE_SECONDS,
            port,
            ", ".join(str(pid) for pid in stale_lock_holder_candidates),
        )
    if (
        not port_listening_candidates
        and not stale_non_blocking_candidates
        and not stale_lock_holder_candidates
    ):
        if lock_holder_candidates:
            log.warning(
                "Found Smart Garden process(es) holding the scheduler lock "
                "before API bind but not port %s; deferring recovery until "
                "after the API listener is bound: %s",
                port,
                ", ".join(str(pid) for pid in lock_holder_candidates),
            )
        return False
    candidates = sorted(set(
        port_listening_candidates
        + stale_non_blocking_candidates
        + stale_lock_holder_candidates
    ))

    if port_listening_candidates:
        lan_listening_candidates = [
            pid for pid in port_listening_candidates
            if _pid_has_lan_reachable_listener(pid, port_inodes)
        ]
        loopback_only_candidates = [
            pid for pid in port_listening_candidates
            if pid not in lan_listening_candidates
        ]
        if lan_listening_candidates:
            log.warning(
                "Found existing Smart Garden process(es) already listening on "
                "LAN-reachable port %s before API bind; watchdog reported the "
                "service unhealthy, so requesting takeover for pid(s): %s",
                port,
                ", ".join(str(pid) for pid in lan_listening_candidates),
            )
        if loopback_only_candidates:
            log.warning(
                "Found Smart Garden process(es) listening on loopback-only "
                "port %s before API bind; requesting shutdown for pid(s): %s",
                port,
                ", ".join(str(pid) for pid in loopback_only_candidates),
            )
    if lock_holder_candidates:
        log.warning(
            "Found Smart Garden process(es) holding the scheduler lock before "
            "API bind; stopping only pid(s) that own port %s or are stale "
            "scheduler-only holders: %s",
            port,
            ", ".join(str(pid) for pid in lock_holder_candidates),
        )

    log.warning(
        "Stopping verified stale Smart Garden process(es) before API bind: %s",
        ", ".join(str(pid) for pid in candidates),
    )
    for pid in candidates:
        _signal_process_tree(pid, signal.SIGTERM)

    port_released = False
    deadline = time.time() + 6
    while time.time() < deadline:
        current_port_inodes = _listening_socket_inodes(port) or {}
        if not any(
            _process_exists(pid)
            and _pid_listens_on_port(pid, current_port_inodes)
            for pid in candidates
        ):
            port_released = True
            break
        time.sleep(0.2)

    current_port_inodes = _listening_socket_inodes(port) or {}
    live_pids = [
        pid for pid in candidates
        if _process_exists(pid)
    ]
    live_port_pids = [
        pid for pid in live_pids
        if _pid_listens_on_port(pid, current_port_inodes)
    ]
    if live_port_pids:
        log.warning(
            "Verified Smart Garden process pid(s) %s survived SIGTERM before "
            "API bind and still hold port %s; forcing shutdown",
            ", ".join(str(pid) for pid in live_port_pids),
            port,
        )
        for pid in live_port_pids:
            _signal_process_tree(pid, signal.SIGKILL)
        deadline = time.time() + 2
        while time.time() < deadline:
            current_port_inodes = _listening_socket_inodes(port) or {}
            if not any(
                _process_exists(pid)
                and _pid_listens_on_port(pid, current_port_inodes)
                for pid in live_port_pids
            ):
                port_released = True
                break
            time.sleep(0.1)
        if not port_released:
            current_port_inodes = _listening_socket_inodes(port) or {}
            port_released = not any(
                _process_exists(pid)
                and _pid_listens_on_port(pid, current_port_inodes)
                for pid in live_port_pids
            )
    elif live_pids:
        log.warning(
            "Verified Smart Garden process pid(s) %s survived SIGTERM before "
            "API bind after releasing port %s; forcing shutdown before "
            "continuing so stale scheduler or DB work cannot block startup",
            ", ".join(str(pid) for pid in live_pids),
            port,
        )
        for pid in live_pids:
            _signal_process_tree(pid, signal.SIGKILL)
        deadline = time.time() + 2
        while time.time() < deadline:
            if not any(_process_exists(pid) for pid in live_pids):
                port_released = True
                break
            time.sleep(0.1)
        if not port_released:
            current_port_inodes = _listening_socket_inodes(port) or {}
            port_released = not any(
                _process_exists(pid)
                and _pid_listens_on_port(pid, current_port_inodes)
                for pid in live_pids
            )
    else:
        port_released = True

    live_pids = [pid for pid in candidates if _process_exists(pid)]
    if port_released and not live_pids:
        log.warning(
            "Stale Smart Garden process released port %s; continuing this "
            "startup into the API bind",
            port,
        )
        return False

    if port_released and live_pids:
        log.warning(
            "Verified stale Smart Garden process pid(s) %s no longer hold "
            "port %s but are still alive after forced cleanup; continuing "
            "into the API bind so the LAN dashboard can recover. Scheduler "
            "ownership will be recovered after the listener is live.",
            ", ".join(str(pid) for pid in live_pids),
            port,
        )
        return False

    if live_pids:
        live_port_pids = [
            pid for pid in live_pids
            if _pid_listens_on_port(pid, current_port_inodes)
        ]
        log.warning(
            "Verified Smart Garden process pid(s) %s survived stale cleanup "
            "before API bind%s",
            ", ".join(str(pid) for pid in live_pids),
            (
                f" and still hold port {port}"
                if live_port_pids else f" after releasing port {port}"
            ),
        )

    log.critical(
        "Stale Smart Garden process cleanup did not release port %s; exiting "
        "instead of starting another partial service",
        port,
    )
    return True


def _recover_headless_processes_after_bind(port: int) -> None:
    """Best-effort cleanup for old scheduler-only Smart Garden processes.

    The API listener is already bound by the current process when this runs.
    Older watchdog failures can leave scheduler processes alive without a port
    listener or readable flock holder, so the lock recovery path alone can miss
    them. Only verified same-project processes that do not own the API port are
    eligible here.
    """
    port_inodes = _listening_socket_inodes(port)
    if port_inodes is None:
        log.warning(
            "Could not inspect /proc TCP listeners after API bind; "
            "skipping headless process recovery"
        )
        return

    lock_path = os.path.join(BASE_DIR, ".smart-garden-api.lock")
    lock_holder_candidates = [
        pid for pid in _lock_holder_pids_from_proc_locks(lock_path)
        if _is_smart_garden_process(pid)
    ]
    same_project_candidates = _smart_garden_process_pids()
    candidate_pool = sorted(set(lock_holder_candidates + same_project_candidates))
    if not candidate_pool:
        return

    headless_candidates = [
        pid for pid in candidate_pool
        if not _pid_listens_on_port(pid, port_inodes)
    ]
    # Once this process has successfully bound the API port, any other
    # same-service process without that listener can only compete for scheduler
    # ownership or keep stale background jobs alive. Stop it even if it is fresh.
    candidates = sorted(set(headless_candidates))
    if not candidates:
        return

    log.warning(
        "Stopping verified headless Smart Garden process(es) after API bind: %s",
        ", ".join(str(pid) for pid in candidates),
    )
    for pid in candidates:
        _signal_process_tree(pid, signal.SIGTERM)

    deadline = time.time() + 6
    while time.time() < deadline:
        if not any(_process_exists(pid) for pid in candidates):
            return
        time.sleep(0.2)

    live_pids = [pid for pid in candidates if _process_exists(pid)]
    if not live_pids:
        return
    log.warning(
        "Headless Smart Garden process pid(s) %s survived SIGTERM after API "
        "bind; forcing shutdown",
        ", ".join(str(pid) for pid in live_pids),
    )
    for pid in live_pids:
        _signal_process_tree(pid, signal.SIGKILL)


def _signal_process_tree(pid: int, sig: int) -> None:
    for child_pid in _smart_garden_child_pids(pid):
        try:
            os.kill(child_pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            log.warning("Cannot signal scheduler child pid %s", child_pid)
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        log.warning("Cannot signal scheduler lock holder pid %s", pid)


def _terminate_other_smart_garden_processes(reason: str) -> None:
    candidates = _smart_garden_peer_pids_for_cleanup()
    if not candidates:
        return

    log.warning(
        "Terminating other verified Smart Garden process(es) before fatal "
        "%s exit: %s",
        reason,
        ", ".join(str(pid) for pid in candidates),
    )
    for pid in candidates:
        _signal_process_tree(pid, signal.SIGTERM)

    deadline = time.time() + 4
    while time.time() < deadline:
        if not any(_process_exists(pid) for pid in candidates):
            return
        time.sleep(0.2)

    live_pids = [pid for pid in candidates if _process_exists(pid)]
    if not live_pids:
        return
    log.warning(
        "Verified Smart Garden process pid(s) %s survived SIGTERM before "
        "fatal %s exit; forcing shutdown",
        ", ".join(str(pid) for pid in live_pids),
        reason,
    )
    for pid in live_pids:
        _signal_process_tree(pid, signal.SIGKILL)


def _request_other_smart_garden_process_shutdown(reason: str) -> None:
    candidates = _smart_garden_peer_pids_for_cleanup()
    if not candidates:
        return

    log.warning(
        "Requesting shutdown of other verified Smart Garden process(es) "
        "before fatal %s exit: %s",
        reason,
        ", ".join(str(pid) for pid in candidates),
    )
    for pid in candidates:
        _signal_process_tree(pid, signal.SIGTERM)


def _flush_log_handlers_best_effort() -> None:
    """Flush logs without blocking the daemon health thread indefinitely."""
    handlers = list(logging.getLogger().handlers)
    handlers.extend(handler for handler in log.handlers if handler not in handlers)
    for handler in handlers:
        lock = getattr(handler, "lock", None)
        acquired = False
        try:
            if lock is not None:
                acquired = lock.acquire(blocking=False)
                if not acquired:
                    continue
            handler.flush()
        except Exception:
            pass
        finally:
            if acquired:
                try:
                    lock.release()
                except Exception:
                    pass


def _start_emergency_hard_exit(reason: str, delay: float = 5.0) -> None:
    """Guarantee fatal health exits cannot hang in cleanup."""
    def hard_exit():
        time.sleep(delay)
        message = (
            f"Emergency hard exit after fatal {reason} cleanup exceeded "
            f"{delay:.0f}s\n"
        )
        try:
            os.write(2, message.encode("utf-8", errors="replace"))
        except Exception:
            pass
        os._exit(1)

    threading.Thread(
        target=hard_exit,
        name=f"fatal-{reason}-hard-exit",
        daemon=True,
    ).start()


def _fatal_api_health_exit(reason: str) -> None:
    # This can run from daemon monitor/scheduler threads. Keep cleanup bounded:
    # a dark API process must exit, but any same-service scheduler-only peers
    # should also be asked to stop so they cannot preserve a running-but-dark
    # systemd service after this process exits.
    _start_emergency_hard_exit(reason, delay=7.0)
    try:
        _terminate_other_smart_garden_processes(reason)
    except Exception:
        pass
    try:
        os.write(
            2,
            f"Smart Garden fatal {reason}; exiting for watchdog restart\n".encode(
                "utf-8",
                errors="replace",
            ),
        )
    except Exception:
        pass
    _flush_log_handlers_best_effort()
    os._exit(1)


def acquire_singleton_lock(recover_headless: bool = False) -> bool:
    """Return True if this process should own scheduler/background work.

    A previous broken start can leave a live scheduler process without a
    dashboard listener. In that case a fatal lock check would keep every
    replacement process from binding the API, so the caller may continue in
    API-only mode after Waitress has created the dashboard listener.
    """
    global _LOCK_FH
    lock_path = os.path.join(BASE_DIR, ".smart-garden-api.lock")
    _LOCK_FH = _open_lock_file(lock_path)
    if _try_lock(_LOCK_FH):
        _write_lock_pid(_LOCK_FH)
        return True

    holder_pid = _read_lock_pid(_LOCK_FH)
    if recover_headless:
        holder_pids = []
        if holder_pid and holder_pid != os.getpid():
            if not _is_smart_garden_process(holder_pid):
                log.warning(
                    "Scheduler lock holder pid %s does not look like this "
                    "service; leaving it alone",
                    holder_pid,
                )
                return False
            holder_pids = [holder_pid]
        elif not holder_pid:
            # Some older recovery attempts truncated or overwrote the lock file
            # with non-PID text while the stale process still held flock(). In
            # that state, ask /proc/locks for the actual flock holder first.
            lock_holder_pids = [
                pid for pid in _lock_holder_pids_from_proc_locks(lock_path)
                if _is_smart_garden_process(pid)
            ]
            if lock_holder_pids:
                log.warning(
                    "Scheduler lock is held without a readable PID; "
                    "/proc/locks identified verified holder pid(s): %s",
                    ", ".join(str(pid) for pid in lock_holder_pids),
                )
                holder_pids = lock_holder_pids
            else:
                # Fall back to same-project process discovery for older kernels
                # or containers where /proc/locks is unavailable or incomplete.
                holder_pids = _smart_garden_process_pids()
                if holder_pids:
                    log.warning(
                        "Scheduler lock is held without a readable PID; "
                        "verified Smart Garden candidates: %s",
                        ", ".join(str(pid) for pid in holder_pids),
                    )

        if not holder_pids:
            log.warning("Scheduler lock holder could not be identified")
            return False

        log.warning(
            "Scheduler lock is held after API bind; requesting stale "
            "headless process shutdown for pid(s): %s",
            ", ".join(str(pid) for pid in holder_pids),
        )
        for pid in holder_pids:
            _signal_process_tree(pid, signal.SIGTERM)
        deadline = time.time() + 6
        while time.time() < deadline:
            if _try_lock(_LOCK_FH):
                log.info("Recovered scheduler lock from stale pid(s): %s",
                         ", ".join(str(pid) for pid in holder_pids))
                _write_lock_pid(_LOCK_FH)
                return True
            if not any(_process_exists(pid) for pid in holder_pids):
                break
            time.sleep(0.2)

        if _try_lock(_LOCK_FH):
            log.info("Recovered scheduler lock from stale pid(s): %s",
                     ", ".join(str(pid) for pid in holder_pids))
            _write_lock_pid(_LOCK_FH)
            return True

        live_holder_pids = [pid for pid in holder_pids if _process_exists(pid)]
        if live_holder_pids:
            log.warning(
                "Scheduler lock holder pid(s) %s did not stop after SIGTERM; "
                "forcing shutdown",
                ", ".join(str(pid) for pid in live_holder_pids),
            )
            for pid in live_holder_pids:
                _signal_process_tree(pid, signal.SIGKILL)
            deadline = time.time() + 2
            while time.time() < deadline:
                if _try_lock(_LOCK_FH):
                    log.info(
                        "Recovered scheduler lock from forced stale pid(s): %s",
                        ", ".join(str(pid) for pid in live_holder_pids),
                    )
                    _write_lock_pid(_LOCK_FH)
                    return True
                if not any(_process_exists(pid) for pid in live_holder_pids):
                    break
                time.sleep(0.1)

        if _try_lock(_LOCK_FH):
            log.info("Recovered scheduler lock from forced stale pid(s): %s",
                     ", ".join(str(pid) for pid in holder_pids))
            _write_lock_pid(_LOCK_FH)
            return True

    if holder_pid:
        log.warning(
            "Another Smart Garden server process holds the scheduler lock "
            "(pid %s)",
            holder_pid,
        )
    else:
        log.warning("Another Smart Garden server process holds the scheduler lock")
    return False


def coerce_int(raw, default: int, min_value: int, max_value: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(max_value, value))


def _normalize_dashboard_host(raw_host) -> str:
    """Force the dashboard bind to a LAN-reachable interface."""
    host = str(raw_host or "").strip() or "0.0.0.0"
    if host.lower() in {"localhost", "127.0.0.1", "::1"}:
        log.warning(
            "Dashboard host %r is loopback-only; overriding to 0.0.0.0 so "
            "LAN clients and the watchdog can reach Smart Garden",
            host,
        )
        return "0.0.0.0"
    return host


def _host_config_is_loopback(host: str | None) -> bool:
    return str(host or "").strip().lower() in {"localhost", "127.0.0.1", "::1"}


def _host_is_lan_reachable(host: str | None) -> bool:
    normalized = str(host or "").strip().lower().strip("[]")
    if not normalized or normalized == "*":
        return True
    if normalized in {"0.0.0.0", "::"}:
        return True
    if normalized in {"localhost", "127.0.0.1", "::1"}:
        return False
    if normalized.startswith("127."):
        return False
    return True


def _waitress_effective_listener_state(wsgi_server, port: int) -> str | None:
    """Return lan, loopback, none, or None from Waitress's created sockets."""
    listeners = getattr(wsgi_server, "effective_listen", None)
    if listeners is None:
        effective_host = getattr(wsgi_server, "effective_host", None)
        effective_port = getattr(wsgi_server, "effective_port", None)
        if effective_host is None or effective_port is None:
            return None
        listeners = [(effective_host, effective_port)]

    matching_hosts = []
    for listener_host, listener_port in listeners:
        try:
            listener_port = int(listener_port)
        except (TypeError, ValueError):
            continue
        if listener_port == port:
            matching_hosts.append(listener_host)

    if not matching_hosts:
        return "none"
    if any(_host_is_lan_reachable(listener_host) for listener_host in matching_hosts):
        return "lan"
    return "loopback"


def _app_waitress_bind_was_lan(app) -> bool:
    return app.config.get("waitress_effective_listener_state") == "lan"


def _health_route_status(app, port: int | None = None) -> int:
    """Exercise the health route through the real listener when possible."""
    if port is not None:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            connection.request(
                "GET",
                "/health",
                headers={"X-Smart-Garden-Internal-Health": "1"},
            )
            response = connection.getresponse()
            response.read()
            return response.status
        except OSError as exc:
            if getattr(exc, "errno", None) != errno.EPERM:
                raise
            log.warning(
                "Loopback /health probe was blocked by the runtime network "
                "policy; falling back to in-process health route after the "
                "LAN listener ownership check"
            )
        finally:
            connection.close()

    with app.test_client() as client:
        response = client.get(
            "/health",
            headers={"X-Smart-Garden-Internal-Health": "1"},
        )
        return response.status_code


def _exit_if_api_listener_unhealthy(app, port: int, host: str | None = None) -> None:
    if not _API_HEALTH_CHECK_LOCK.acquire(blocking=False):
        log.warning("API listener health check already running; skipping overlap")
        return
    try:
        try:
            health_status = _health_route_status(app, port)
            if health_status >= 500:
                raise RuntimeError(f"health returned HTTP {health_status}")
            app.config["last_successful_request_ts"] = time.time()
        except Exception as exc:
            log.critical(
                "Health route failed through the running Waitress listener: %s; "
                "exiting for watchdog restart",
                exc,
            )
            _fatal_api_health_exit("api-listener-health")

        listener_state = _current_process_listener_state(port)
        if listener_state is None:
            log.warning(
                "Could not inspect API listener during health check; keeping the "
                "process alive because the active /health route passed"
            )
        elif listener_state == "loopback":
            if _app_waitress_bind_was_lan(app):
                log.warning(
                    "Process socket inspection reported only a loopback API "
                    "listener on port %s, but Waitress created a LAN-reachable "
                    "listener and active /health returned HTTP %s; keeping the "
                    "API alive because the concrete Waitress bind is correct",
                    port,
                    health_status,
                )
                return
            log.critical(
                "Process owns only a loopback API listener on port %s while "
                "the effective dashboard bind is %s and active /health returned "
                "HTTP %s; exiting so the watchdog can restart Smart Garden with "
                "a LAN-reachable listener",
                port,
                host or "0.0.0.0",
                health_status,
            )
            _fatal_api_health_exit("api-listener-loopback-only")
            return
        elif listener_state == "none":
            if not _confirm_missing_lan_reachable_listener(port):
                log.warning(
                    "API listener check briefly missed a LAN-reachable listener "
                    "on port %s; keeping the process alive after confirmation "
                    "recovered",
                    port,
                )
            else:
                log.critical(
                    "Process does not own a LAN-reachable API listener on port "
                    "%s after repeated checks, even though a /health probe "
                    "returned HTTP %s through Waitress; exiting so the "
                    "watchdog can restart the dark API runtime",
                    port,
                    health_status,
                )
                _fatal_api_health_exit("api-listener-missing")
                return

        now = time.time()
        last_external_request = app.config.get("last_health_check_ts")
        if not last_external_request or now - last_external_request > 900:
            stale_for = (
                now - last_external_request
                if last_external_request
                else now - app.config.get("start_time", now)
            )
            log.warning(
                "No non-internal HTTP request has completed in %.0fs, even "
                "though this process owns a LAN-reachable listener and "
                "internal /health passes through Waitress; keeping the API "
                "alive because concrete listener health checks passed",
                stale_for,
            )
    finally:
        _API_HEALTH_CHECK_LOCK.release()


def _exit_if_initial_api_bind_not_lan(
    port: int,
    host: str | None = None,
    waitress_listener_state: str | None = None,
) -> None:
    """Fail startup before scheduler work if Waitress did not bind for LAN use."""
    configured_lan_bind = _host_is_lan_reachable(host)
    if waitress_listener_state == "lan":
        return
    if waitress_listener_state in {"loopback", "none"}:
        if configured_lan_bind:
            log.warning(
                "Initial Waitress listener inspection reported %s API listener "
                "on port %s, but the configured dashboard bind is %s; "
                "continuing startup and leaving LAN reachability to the "
                "external watchdog",
                "no" if waitress_listener_state == "none" else "only a loopback",
                port,
                host or "0.0.0.0",
            )
            return
        log.critical(
            "Initial Waitress bind created %s API listener on port %s while "
            "the effective dashboard bind is %s; exiting before scheduler "
            "start so Smart Garden restarts with a LAN-reachable API",
            "no" if waitress_listener_state == "none" else "only a loopback",
            port,
            host or "0.0.0.0",
        )
        sys.exit(1)

    listener_state = _current_process_listener_state(port)
    if listener_state == "lan":
        return
    if listener_state is None:
        log.warning(
            "Could not inspect initial API listener on port %s after Waitress "
            "created the socket; continuing because runtime listener "
            "inspection is unavailable",
            port,
        )
        return

    if configured_lan_bind:
        log.warning(
            "Initial process socket inspection reported %s API listener on "
            "port %s, but the configured dashboard bind is %s; continuing "
            "startup and leaving LAN reachability to the external watchdog",
            "no" if listener_state == "none" else "only a loopback",
            port,
            host or "0.0.0.0",
        )
        return

    log.critical(
        "Initial Waitress bind created %s API listener on port %s while the "
        "effective dashboard bind is %s; exiting before scheduler start so "
        "Smart Garden restarts with a LAN-reachable API",
        "no" if listener_state == "none" else "only a loopback",
        port,
        host or "0.0.0.0",
    )
    sys.exit(1)


def _exit_if_scheduler_api_listener_missing(
    port: int,
    job_name: str = "scheduler",
    expected_lan_bind: bool = False,
) -> None:
    """Stop scheduler work if this process no longer owns the LAN API listener."""
    listener_state = _current_process_listener_state(port)
    if listener_state == "lan":
        return
    if listener_state == "loopback" and expected_lan_bind:
        log.warning(
            "Scheduler job %s saw a loopback-only API listener report on port "
            "%s, but the initial Waitress bind was LAN-reachable; continuing "
            "because the external watchdog owns final LAN reachability checks",
            job_name,
            port,
        )
        return
    if listener_state is None:
        for _ in range(2):
            time.sleep(1)
            listener_state = _current_process_listener_state(port)
            if listener_state == "lan":
                return
            if listener_state is not None:
                break
        if listener_state is None:
            log.warning(
                "Scheduler job %s could not inspect this process's API "
                "listener on port %s after repeated checks; continuing because "
                "listener inspection can be unavailable while the external "
                "watchdog owns LAN reachability checks",
                job_name,
                port,
            )
            return
    if listener_state == "none" and not _confirm_missing_lan_reachable_listener(port):
        return

    log.critical(
        "Scheduler job %s found this process has %s API listener on port %s; "
        "exiting so background irrigation work cannot continue without a "
        "LAN-reachable API",
        job_name,
        "no" if listener_state == "none" else "only a loopback",
        port,
    )
    _fatal_api_health_exit(f"{job_name}-api-listener-missing")
    return


def _start_api_health_monitor(app, port: int, host: str | None = None) -> None:
    """Watch API freshness independently of scheduler ownership."""
    def monitor():
        # Give Waitress startup and the external watchdog its first few checks.
        time.sleep(90)
        while True:
            _exit_if_api_listener_unhealthy(app, port, host)
            time.sleep(60)

    thread = threading.Thread(
        target=monitor,
        name="api-health-monitor",
        daemon=True,
    )
    thread.start()


def main():
    log.info("Smart Garden Server starting...")
    startup_time = datetime.now()

    # Load config
    config = load_config()
    log.info("Config loaded: %d zones, location %.2f,%.2f",
             len(config["zones"]), config["location"]["lat"],
             config["location"]["lon"])

    dash_config = config.get("dashboard", {})
    host = _normalize_dashboard_host(dash_config.get("host", "0.0.0.0"))
    dash_config["host"] = host
    port = dash_config.get("port", 5125)
    if _recover_stale_processes_before_bind(port):
        logging.shutdown()
        sys.exit(1)

    # Initialize database
    db.init_db()
    log.info("Database initialized at %s", db.DB_PATH)

    # Initialize components
    weather = WeatherClient(
        lat=config["location"]["lat"],
        lon=config["location"]["lon"],
        timezone=config["location"]["timezone"],
    )

    billing = BillingCalculator(config)
    engine = IrrigationEngine(config, weather, billing)

    # ── Scheduler ──
    scheduler = None

    poll_interval = config["esp32"]["poll_interval_sec"]
    def build_scheduler():
        scheduler = BackgroundScheduler(timezone=config["location"]["timezone"])

        def api_guarded(job_name, func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                _exit_if_scheduler_api_listener_missing(
                    port,
                    job_name,
                    expected_lan_bind=_host_is_lan_reachable(host),
                )
                return func(*args, **kwargs)
            return wrapper

        scheduler.add_job(
            lambda: _exit_if_scheduler_api_listener_missing(
                port,
                "api_listener_guard",
                expected_lan_bind=_host_is_lan_reachable(host),
            ),
            "interval",
            seconds=60,
            id="api_listener_guard",
            max_instances=1,
            next_run_time=startup_time + timedelta(seconds=45),
        )

        # Poll ESP32 sensors every 5 minutes. Delay the first network poll until
        # after Waitress has had a chance to bind, so controller outages cannot
        # make watchdog restarts look like API startup failures.
        scheduler.add_job(api_guarded("irrigation_cycle", engine.run_cycle),
                          "interval", seconds=poll_interval,
                          id="irrigation_cycle", max_instances=1,
                          misfire_grace_time=60,
                          next_run_time=startup_time + timedelta(seconds=20))

        # Safety check every 2 minutes.
        scheduler.add_job(api_guarded("safety_check", engine.safety_check),
                          "interval", seconds=120,
                          id="safety_check", max_instances=1,
                          next_run_time=startup_time + timedelta(seconds=30))

        # Pre-fetch weather every 30 minutes (cache keeps us from hammering API).
        # Delay the first fetch; DNS/TLS stalls from Open-Meteo must not compete
        # with the initial Waitress bind path during watchdog restarts.
        scheduler.add_job(api_guarded("weather_fetch", weather.fetch),
                          "interval", minutes=30,
                          id="weather_fetch", max_instances=1,
                          next_run_time=startup_time + timedelta(seconds=90))

        # Update soil water balances daily at 11 PM (after all watering is done)
        scheduler.add_job(api_guarded(
                              "daily_balance", engine.update_daily_balances),
                          "cron", hour=23,
                          id="daily_balance", max_instances=1,
                          misfire_grace_time=3600)

        # Roll up the day's water, savings, weather, and cost into
        # daily_summary at 23:55 — after daily_balance, before midnight.
        scheduler.add_job(api_guarded(
                              "daily_summary", billing.update_daily_summary),
                          "cron", hour=23, minute=55,
                          id="daily_summary", max_instances=1,
                          misfire_grace_time=3600)

        # Capture forecast snapshot daily at 3:55 AM (before morning watering window)
        scheduler.add_job(api_guarded(
                              "forecast_snapshot", engine.save_daily_forecast_snapshot),
                          "cron", hour=3, minute=55,
                          id="forecast_snapshot", max_instances=1,
                          misfire_grace_time=3600)

        # Prune old data nightly at 3 AM (keep 30d raw, 1y hourly aggregates)
        scheduler.add_job(api_guarded("data_prune", db.prune_old_data),
                          "cron", hour=3,
                          id="data_prune", max_instances=1,
                          misfire_grace_time=3600)

        # Check for alert conditions every 5 minutes
        from notifications import AlertMonitor
        alert_monitor = AlertMonitor(config, engine)
        scheduler.add_job(api_guarded("alert_check", alert_monitor.check),
                          "interval", seconds=poll_interval,
                          id="alert_check", max_instances=1,
                          next_run_time=startup_time + timedelta(seconds=40))

        # Daily 8 AM health digest (one ntfy with 24h summary)
        scheduler.add_job(api_guarded("daily_digest", alert_monitor.daily_digest),
                          "cron", hour=8,
                          id="daily_digest", max_instances=1,
                          misfire_grace_time=3600)

        # Confirm alert pipeline at startup (one ntfy = "I'm alive")
        scheduler.add_job(api_guarded("startup_ping", alert_monitor.startup_ping),
                          "date",
                          run_date=startup_time + timedelta(seconds=60),
                          id="startup_ping")

        # Auto-detect sensor faults every hour
        scheduler.add_job(api_guarded(
                              "sensor_fault_check",
                              lambda: db.check_and_update_sensor_faults(
                                  config["zones"]
                              ),
                          ),
                          "interval", minutes=60,
                          id="sensor_fault_check", max_instances=1)

        # Log server health (disk %, DB size, CPU temp) every 5 minutes
        scheduler.add_job(api_guarded("server_health_log", db.log_server_health),
                          "interval", minutes=5,
                          id="server_health_log", max_instances=1)

        return scheduler

    # ── Flask dashboard (runs in main thread) ──
    # Import here to avoid circular imports
    from dashboard import create_app
    app = create_app(config, engine, weather, billing)

    def stop_scheduler():
        if scheduler and scheduler.running:
            scheduler.shutdown(wait=False)

    # Graceful shutdown
    def shutdown(signum, frame):
        log.info("Shutting down...")
        try:
            stop_scheduler()
            # Best-effort valve close on shutdown. 3s (was 1s) so a normal
            # shutdown actually reaches the ESP32 and closes cleanly instead of
            # logging a timeout error; still short enough not to hang exit if the
            # controller is unreachable. The firmware also closes all valves on
            # its next boot, so this is belt-and-suspenders either way.
            engine.close_all(timeout=3, retry=False)
        finally:
            logging.shutdown()
            # sys.exit() only exits the main thread. If an APScheduler or
            # Waitress worker is blocked on ESP32 I/O, the process can survive
            # as a scheduler-only service with no API listener on port 5125.
            os._exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Use waitress (production WSGI) instead of Flask's dev server.
    # Flask's built-in server is single-threaded, fragile under bad input,
    # and not intended for production. Waitress is battle-tested, threaded,
    # and handles malformed requests gracefully without crashing the process.
    #
    # Create the Waitress server before touching the scheduler singleton lock or
    # starting background jobs. create_server() performs the real socket bind, so
    # a listener failure cannot leave a scheduler-only process behind with no API
    # on port 5125.
    from waitress import create_server
    waitress_threads = coerce_int(dash_config.get("threads"), 16, 8, 32)
    waitress_connection_limit = coerce_int(
        dash_config.get("connection_limit"), 256, 100, 1024)
    waitress_channel_timeout = coerce_int(
        dash_config.get("channel_timeout"), 30, 10, 120)
    waitress_cleanup_interval = coerce_int(
        dash_config.get("cleanup_interval"), 10, 5, 60)
    log.info(
        "Dashboard starting on http://%s:%d (waitress, %d threads, "
        "%d connections, %ds channel timeout)",
        host, port, waitress_threads, waitress_connection_limit,
        waitress_channel_timeout,
    )
    try:
        wsgi_server = create_server(
            app,
            host=host,
            port=port,
            threads=waitress_threads,
            connection_limit=waitress_connection_limit,
            channel_timeout=waitress_channel_timeout,
            cleanup_interval=waitress_cleanup_interval,
            ident="smart-garden",
        )
    except Exception:
        log.exception("Dashboard listener failed before scheduler start")
        sys.exit(1)

    waitress_listener_state = _waitress_effective_listener_state(wsgi_server, port)
    app.config["waitress_effective_listener_state"] = waitress_listener_state
    _exit_if_initial_api_bind_not_lan(port, host, waitress_listener_state)
    _start_api_health_monitor(app, port, host)
    _recover_headless_processes_after_bind(port)

    owns_scheduler = acquire_singleton_lock(recover_headless=True)
    if owns_scheduler:
        scheduler = build_scheduler()
        scheduler.start()
        log.info("Scheduler started: irrigation every %ds, safety every 120s, "
                 "weather every 30min", poll_interval)
    else:
        log.warning("Scheduler not started in API-only lock-recovery mode")

    try:
        wsgi_server.print_listen("Serving on http://{}:{}")
        wsgi_server.run()
    except Exception:
        log.exception("Dashboard listener failed; shutting down scheduler")
        stop_scheduler()
        sys.exit(1)
    finally:
        stop_scheduler()


if __name__ == "__main__":
    main()
