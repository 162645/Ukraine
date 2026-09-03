"""内存感知的 ClickHouse 客户端。

设计要点(服务器内存上限 32G):
  1. 所有重聚合都下推到 ClickHouse(GROUP BY),Python 只接收聚合后的小结果。
  2. 对必须逐行拉取的场景(如原始 traceroute 提边),使用**流式分块**读取,
     绝不 SELECT * 到单个 DataFrame。
  3. 每个查询附带服务端内存限制与外部聚合/排序落盘设置,避免 OOM。
  4. 流式读取带 tqdm 进度条,满足"跑的时候要能输出进度条"。

优先使用 clickhouse-connect(HTTP:8123),不可用时回退 clickhouse-driver(native:9000)。
"""
from __future__ import annotations

from typing import Any, Iterator

import pandas as pd

from .config import Config
from .progress import get_logger, pbar


class CHClient:
    def __init__(self, cfg: Config, prefer: str = "connect"):
        self.cfg = cfg
        self.logger = get_logger(cfg.out_dir("logs"))
        self.backend = None
        self._client = None
        self._prefer = prefer
        self._connect()

    # ------------------------------------------------------------------ 连接
    def _server_settings(self) -> dict[str, Any]:
        rt = self.cfg.runtime
        return {
            "max_memory_usage": self.cfg.ch_max_memory_usage,
            "max_bytes_before_external_group_by": self.cfg.ch_external_group_by,
            "max_bytes_before_external_sort": self.cfg.ch_external_sort,
            "max_threads": int(rt["ch_max_threads"]),
            # 只读用户:显式声明只读,避免误写
            "readonly": 1,
        }

    def _settings_for_user(self) -> dict[str, Any]:
        """Return optional per-query safeguards.

        Many institutional ClickHouse accounts are read-only and are not allowed
        to change settings (error 164).  Users can disable client-side settings
        through ``database.apply_query_settings: false`` or
        ``UR_CH_APPLY_SETTINGS=0``.  Connection also retries once without
        settings, so a username does not need to be literally ``readonly_user``.
        """
        import os
        db = self.cfg.db_conn()
        flag = str(os.environ.get("UR_CH_APPLY_SETTINGS",
                                  db.get("apply_query_settings", True))).lower()
        if flag in {"0", "false", "no", "off"}:
            return {}
        return self._server_settings()

    def _open_backend(self, backend: str, db: dict[str, Any], settings: dict[str, Any]):
        if backend == "connect":
            import clickhouse_connect
            self._client = clickhouse_connect.get_client(
                host=db["host"], port=int(db["http_port"]), username=db["user"],
                password=db["password"], database=db["database"],
                secure=bool(db.get("secure", False)),
                connect_timeout=int(db.get("connect_timeout", 30)),
                send_receive_timeout=int(db.get("send_receive_timeout", 1800)),
                settings=settings,
                # No session id: a streaming read and a mapping point-query must
                # never deadlock each other with SESSION_IS_LOCKED.
                autogenerate_session_id=False,
            )
        else:
            from clickhouse_driver import Client
            self._client = Client(
                host=db["host"], port=int(db["native_port"]), user=db["user"],
                password=db["password"], database=db["database"],
                secure=bool(db.get("secure", False)),
                connect_timeout=int(db.get("connect_timeout", 30)),
                send_receive_timeout=int(db.get("send_receive_timeout", 1800)),
                settings=settings,
            )
        self.backend = backend
        self._ping()
        # A production run must never silently fall back to an unlimited
        # server profile.  Set UR_CH_REQUIRE_MEMORY_GUARD=1 in the run
        # environment to require a positive max_memory_usage at connection
        # time; this catches readonly accounts that cannot apply per-query
        # settings before any large analytical query is issued.
        import os
        require_guard = str(os.environ.get("UR_CH_REQUIRE_MEMORY_GUARD", "0")).lower()
        if require_guard in {"1", "true", "yes", "on"}:
            if self.backend == "connect":
                value = self._client.query("SELECT getSetting('max_memory_usage')").result_rows[0][0]
            else:
                value = self._client.execute("SELECT getSetting('max_memory_usage')")[0][0]
            if int(value) <= 0:
                raise PermissionError(
                    "ClickHouse memory guard is not active (max_memory_usage=0); "
                    "configure a bounded readonly profile before running the experiment."
                )

    def _connect(self):
        db = self.cfg.db_conn()
        order = [self._prefer] + [b for b in ("connect", "driver") if b != self._prefer]
        preferred_settings = self._settings_for_user()
        setting_attempts = [preferred_settings]
        if preferred_settings:
            setting_attempts.append({})
        last_err = None
        for backend in order:
            for settings in setting_attempts:
                try:
                    self._open_backend(backend, db, settings)
                    if not settings and preferred_settings:
                        self.logger.warning(
                            "ClickHouse connected without client query settings; "
                            "the account likely cannot modify server settings."
                        )
                    self.logger.info("已连接 ClickHouse (backend=%s, host=%s)", self.backend, db["host"])
                    return
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    self.logger.warning(
                        "后端 %s 连接失败 (settings=%s): %s",
                        backend, "on" if settings else "off", e,
                    )
                    try:
                        if backend == "connect" and self._client is not None:
                            self._client.close()
                    except Exception:
                        pass
                    self._client = None
                    self.backend = None
        raise ConnectionError(
            f"无法连接 ClickHouse {db['host']} (http:{db['http_port']}/native:{db['native_port']}). "
            f"最后错误: {last_err}"
        )

    def _ping(self):
        if self.backend == "connect":
            self._client.query("SELECT 1")
        else:
            self._client.execute("SELECT 1")

    # ------------------------------------------------------------------ 查询
    @staticmethod
    def _is_session_locked(err: Exception) -> bool:
        s = str(err)
        return "373" in s or "SESSION_IS_LOCKED" in s or "Session" in s and "locked" in s

    @staticmethod
    def _is_reconnectable_error(err: Exception) -> bool:
        s = str(err)
        needles = [
            "Read timed out", "ConnectTimeoutError", "NewConnectionError",
            "Connection aborted", "Max retries exceeded", "ProtocolError",
            "Network is unreachable", "Can't assign requested address",
            "Connection reset by peer", "Broken pipe", "Connection refused",
            "RemoteDisconnected", "Operation timed out", "timed out",
        ]
        return any(x in s for x in needles)

    def _reconnect(self) -> None:
        preferred = self.backend or self._prefer
        self.close()
        self._client = None
        self.backend = None
        self._prefer = preferred
        self._connect()

    def _retry_session(self, sql: str, fn, *, what: str = "query"):
        """遇到 session 锁或瞬时网络失败时等待并重连重试。"""
        import time as _t
        last = None
        max_attempts = max(1, int(self.cfg.runtime.get("ch_query_retries", 8)))
        base_wait = max(0.5, float(self.cfg.runtime.get("ch_retry_backoff_seconds", 3)))
        for attempt in range(max_attempts):
            try:
                return fn()
            except Exception as e:  # noqa: BLE001
                last = e
                wait_s = base_wait * (attempt + 1)
                if self._is_session_locked(e):
                    self.logger.warning("%s: session 被锁, 等待 %.1fs 重试 (尝试%d/5)",
                                        what, wait_s, attempt + 1)
                    _t.sleep(wait_s)
                    continue
                if self._is_reconnectable_error(e):
                    self.logger.warning("%s: 网络错误, %.1fs 后重连重试 (尝试%d/5): %s",
                                        what, wait_s, attempt + 1, e)
                    _t.sleep(wait_s)
                    try:
                        self._reconnect()
                    except Exception as reconnect_err:  # noqa: BLE001
                        last = reconnect_err
                        self.logger.warning("%s: 重连失败 (尝试%d/5): %s",
                                            what, attempt + 1, reconnect_err)
                    continue
                raise
        raise last

    def scalar(self, sql: str) -> Any:
        """返回单值(第一行第一列)。"""
        if self.backend == "connect":
            res = self._retry_session(sql, lambda: self._client.query(sql), what="scalar")
            return res.result_rows[0][0] if res.result_rows else None
        rows = self._retry_session(sql, lambda: self._client.execute(sql), what="scalar")
        return rows[0][0] if rows else None

    def query_df(self, sql: str, params: dict | None = None) -> pd.DataFrame:
        """拉取(通常已聚合的)结果为 DataFrame。仅用于结果规模可控的查询。"""
        if self.backend == "connect":
            # 连接已禁用 autogenerate_session_id, 不会 373; 重试仅作保险。
            return self._retry_session(sql, lambda: self._client.query_df(
                sql, parameters=params or {}), what="query_df")
        data, cols = self._retry_session(
            sql,
            lambda: self._client.execute(sql, params or {}, with_column_types=True),
            what="query_df",
        )
        return pd.DataFrame(data, columns=[c[0] for c in cols])

    def stream_df(
        self,
        sql: str,
        *,
        desc: str = "streaming",
        params: dict | None = None,
        approx_total_rows: int | None = None,
    ) -> Iterator[pd.DataFrame]:
        """**流式**分块读取,内存友好。逐块 yield DataFrame,并显示行级进度条。

        用于必须逐行处理的大表(如 traceroute 提边)。切勿一次性物化整表。
        """
        bar = pbar(total=approx_total_rows, desc=desc, unit="row")
        try:
            if self.backend == "connect":
                with self._client.query_df_stream(sql, parameters=params or {}) as stream:
                    for block in stream:
                        bar.update(len(block))
                        yield block
            else:
                settings = {"max_block_size": int(self.cfg.runtime["fetch_block_rows"])}
                rows_iter = self._client.execute_iter(
                    sql, params or {}, with_column_types=True, settings=settings
                )
                first = next(rows_iter, None)
                if first is None:
                    return
                # execute_iter: 第一项是列信息? 不是,driver 每次给一行数据。
                # 这里用 with_column_types 时,首元素是列类型元组列表。
                cols = [c[0] for c in first] if isinstance(first, list) and first and isinstance(first[0], tuple) else None
                buf, cols_ready = [], cols
                block_size = int(self.cfg.runtime["fetch_block_rows"])
                # 若首元素是数据行(无列信息模式),回退处理
                if cols_ready is None:
                    buf.append(first)
                for row in rows_iter:
                    buf.append(row)
                    if len(buf) >= block_size:
                        df = pd.DataFrame(buf, columns=cols_ready)
                        bar.update(len(df))
                        yield df
                        buf = []
                if buf:
                    df = pd.DataFrame(buf, columns=cols_ready)
                    bar.update(len(df))
                    yield df
        finally:
            bar.close()

    # ------------------------------------------------------------------ 工具
    def table_count(self, logical_or_full: str) -> int:
        full = self.cfg.database["tables"].get(logical_or_full, logical_or_full)
        return int(self.scalar(f"SELECT count() FROM {full}"))

    def describe(self, logical_or_full: str) -> pd.DataFrame:
        full = self.cfg.database["tables"].get(logical_or_full, logical_or_full)
        return self.query_df(f"DESCRIBE TABLE {full}")

    def close(self):
        try:
            if self.backend == "connect" and self._client is not None:
                self._client.close()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
