"""统一进度条与日志工具。

- 所有长任务都用 tqdm 展示进度条,满足"跑的时候要能输出进度"。
- 同时把关键节点写入 logs/run.log,便于事后追溯。
"""
from __future__ import annotations

import logging
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from tqdm.auto import tqdm

_LOGGER_NAME = "uresil"


class HeartbeatProgress:
    """Lightweight progress helper that mirrors key milestones into run.log.

    ``tqdm`` is still the primary terminal experience. This helper only emits
    throttled heartbeat summaries so long-running inner loops remain visible in
    ``logs/run.log``.
    """

    def __init__(self, logger: logging.Logger, scope: str, *, total: int | None = None,
                 unit: str = "item", log_every_n: int = 1, log_every_s: float = 30.0):
        self.logger = logger
        self.scope = scope
        self.total = total
        self.unit = unit
        self.log_every_n = max(1, int(log_every_n))
        self.log_every_s = max(0.0, float(log_every_s))
        self.started_at = time.time()
        self.last_log_at = 0.0
        self.done = 0
        self.cached = 0
        self.failed = 0

    @staticmethod
    def _fmt_value(value: Any) -> str:
        if isinstance(value, float):
            return f"{value:.1f}"
        return str(value)

    def _summary(self, *, current: str | None = None, **fields: Any) -> str:
        elapsed = time.time() - self.started_at
        parts = [f"scope={self.scope}", f"done={self.done}"]
        if self.total is not None:
            pct = 100.0 * self.done / max(self.total, 1)
            parts[1] = f"done={self.done}/{self.total}"
            parts.append(f"pct={pct:.1f}%")
            if self.done > 0 and self.done < self.total:
                eta = elapsed * (self.total - self.done) / self.done
                parts.append(f"eta={eta:.1f}s")
        parts.append(f"unit={self.unit}")
        if self.cached:
            parts.append(f"cached={self.cached}")
        if self.failed:
            parts.append(f"failed={self.failed}")
        parts.append(f"elapsed={elapsed:.1f}s")
        if current:
            parts.append(f"current={current}")
        for key, value in fields.items():
            if value is None:
                continue
            parts.append(f"{key}={self._fmt_value(value)}")
        return " | ".join(parts)

    def start(self, **fields: Any) -> None:
        self.last_log_at = time.time()
        self.logger.info("进度开始 | %s", self._summary(**fields))

    def mark_cached(self, n: int = 1) -> None:
        self.cached += int(n)

    def mark_failed(self, n: int = 1) -> None:
        self.failed += int(n)

    def advance(self, n: int = 1, *, current: str | None = None, force: bool = False,
                **fields: Any) -> None:
        self.done += int(n)
        now = time.time()
        count_due = (self.done % self.log_every_n == 0)
        time_due = (now - self.last_log_at) >= self.log_every_s
        finished = self.total is not None and self.done >= self.total
        if force or count_due or time_due or finished:
            self.logger.info("进度心跳 | %s", self._summary(current=current, **fields))
            self.last_log_at = now

    def finish(self, **fields: Any) -> None:
        self.logger.info("进度完成 | %s", self._summary(**fields))


def get_logger(log_dir: str | Path | None = None) -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%Y-%m-%d %H:%M:%S")

    # 控制台
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    # 文件
    if log_dir is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_dir / "run.log", encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger


def pbar(iterable=None, *, total=None, desc="", unit="it", leave=True):
    """统一进度条封装(自动适配终端 / notebook)。"""
    return tqdm(iterable, total=total, desc=desc, unit=unit, leave=leave,
                dynamic_ncols=True, smoothing=0.1)


@contextmanager
def step(desc: str, logger: logging.Logger | None = None):
    """阶段计时上下文,进入/退出各打一条日志与耗时。"""
    logger = logger or get_logger()
    logger.info("▶ 开始: %s", desc)
    t0 = time.time()
    try:
        yield
    finally:
        logger.info("✔ 完成: %s (耗时 %.1fs)", desc, time.time() - t0)
