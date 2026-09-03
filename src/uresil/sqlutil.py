"""SQL 模板加载与安全格式化。

SQL 文件用 Python str.format 占位符({name})。这里只允许代入我们自己控制的值:
时间字符串、data_center、整数 cycle_id 列表、引号安全的 /24 与 IP 列表。
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

_SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def load_sql(name: str) -> str:
    if not name.endswith(".sql"):
        name += ".sql"
    return (_SQL_DIR / name).read_text(encoding="utf-8")


def render(name: str, **kwargs) -> str:
    sql = load_sql(name).format(**kwargs)
    # ClickHouse HTTP 接口不允许单条查询带结尾分号(Multi-statements are not allowed, 62),
    # 去掉末尾空白与分号。
    return sql.rstrip().rstrip(";").rstrip()


def int_list(values: Iterable[int]) -> str:
    """整数列表 -> "1,2,3" (用于 IN)。"""
    vals = list(values)
    if not vals:
        return "0"  # 空集合的安全占位(不会命中任何行)
    return ",".join(str(int(v)) for v in vals)


def str_list(values: Iterable[str]) -> str:
    """字符串列表 -> "'a','b'"。转义单引号,防注入。"""
    vals = list(values)
    if not vals:
        return "''"
    esc = [v.replace("\\", "\\\\").replace("'", "\\'") for v in vals]
    return ",".join(f"'{v}'" for v in esc)
