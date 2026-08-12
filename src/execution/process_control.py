"""Conservative local worker termination helpers."""

from __future__ import annotations

import os
import signal
from pathlib import Path

import psutil

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def terminate_strategy_worker(process_id: int | None, run_id: str) -> bool:
    """Terminate only a verified strategy command in this workspace."""
    if process_id is None:
        return False
    try:
        process = psutil.Process(process_id)
        command = process.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    command_text = " ".join(command)
    if process_id == os.getpid():
        raise PermissionError("拒绝终止 Web 服务自身")
    try:
        working_directory = Path(process.cwd()).resolve()
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        working_directory = None
    belongs_to_workspace = (
        str(PROJECT_ROOT).lower() in command_text.lower()
        or working_directory == PROJECT_ROOT
    )
    if not belongs_to_workspace:
        raise PermissionError("租约 PID 不属于当前工作区，拒绝终止")
    if "golden-pit" not in command_text:
        raise PermissionError("租约 PID 不是黄金坑工作进程，拒绝终止")
    if run_id not in command_text and "workflow" not in command_text:
        raise PermissionError("租约 PID 与目标运行不匹配，拒绝终止")
    processes = [*process.children(recursive=True), process]
    for item in processes:
        try:
            item.send_signal(signal.SIGTERM)
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(processes, timeout=5)
    for item in alive:
        try:
            item.kill()
        except psutil.NoSuchProcess:
            pass
    if alive:
        psutil.wait_procs(alive, timeout=3)
    return not psutil.pid_exists(process_id)
