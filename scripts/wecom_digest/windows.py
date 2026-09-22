"""Windows-only discovery that does not read chat text or process memory."""

import hashlib
from pathlib import Path
import time

import psutil


def data_directories():
    roots = []
    for documents in (Path.home() / "Documents", Path.home() / "OneDrive" / "Documents"):
        base = documents / "WXWork"
        if not base.is_dir():
            continue
        for candidate in base.glob("*/Data"):
            if all((candidate / name).is_file() for name in ("message.db", "session.db", "user.db")):
                roots.append(candidate.resolve())
    return sorted(set(roots))


def processes():
    result = []
    for process in psutil.process_iter(["pid", "name", "exe"]):
        if (process.info.get("name") or "").lower() != "wxwork.exe":
            continue
        executable = process.info.get("exe")
        item = {"pid": process.info["pid"], "name": process.info["name"], "exe": executable}
        if executable and Path(executable).is_file():
            item["exe_sha256"] = hashlib.sha256(Path(executable).read_bytes()).hexdigest()
        result.append(item)
    return result


def is_running():
    return bool(processes())


def wait_for_exit(timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_running():
            return True
        time.sleep(0.5)
    return False


def choose_data_directory(value=None):
    available = data_directories()
    if value:
        chosen = Path(value).resolve()
        if chosen not in available:
            raise ValueError("--data-dir 必须是自动检测到且包含三个核心数据库的账号目录")
        return chosen
    if len(available) != 1:
        raise ValueError("企业微信账号目录不唯一，请用 --data-dir 明确选择：" + str(available))
    return available[0]


def client_identity():
    running = processes()
    if not running:
        return "WXWork（运行前未能识别构建）"
    executable = running[0].get("exe") or "WXWork.exe"
    digest = running[0].get("exe_sha256") or "unavailable"
    return f"{Path(executable).name}; exe_sha256={digest}"
