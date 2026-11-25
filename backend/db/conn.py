"""DuckDB 连接。

DuckDB 同一时刻只允许一个进程写入，且写入进程持有文件锁时其它进程无法打开。
因此所有读写都用"短连接"：用完即关，遇到锁冲突时重试。ETL 批量写入时
只在落盘的一瞬间持有写锁，API 在其余时间都能读取。
"""
from contextlib import contextmanager
from pathlib import Path
import time

import duckdb

from backend.config import DB_PATH

SCHEMA = Path(__file__).with_name("schema.sql")
_initialized = False


def _open(read_only: bool, retries: int = 60):
    last = None
    for _ in range(retries):
        try:
            return duckdb.connect(str(DB_PATH), read_only=read_only)
        except duckdb.IOException as e:  # 文件被其他进程锁住
            last = e
            time.sleep(0.5)
    raise last


def init_db():
    global _initialized
    if _initialized:
        return
    con = _open(read_only=False)
    try:
        con.execute(SCHEMA.read_text(encoding="utf-8"))
    finally:
        con.close()
    _initialized = True


@contextmanager
def connect(read_only: bool = True):
    init_db()
    con = _open(read_only)
    try:
        yield con
    finally:
        con.close()


def query_df(sql: str, params=None):
    with connect() as con:
        return con.execute(sql, params or []).df()


def upsert_df(table: str, df, key_cols: list[str]):
    """按主键覆盖写入（先删后插，保证重复执行幂等）。"""
    if df is None or len(df) == 0:
        return 0
    with connect(read_only=False) as con:
        con.register("_incoming", df)
        cols = ", ".join(df.columns)
        on = " AND ".join(f"t.{k} = s.{k}" for k in key_cols)
        con.execute("BEGIN")
        con.execute(f"DELETE FROM {table} t USING _incoming s WHERE {on}")
        con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _incoming")
        con.execute("COMMIT")
        con.unregister("_incoming")
    return len(df)


def log_etl(task: str, status: str, message: str = ""):
    with connect(read_only=False) as con:
        con.execute(
            "INSERT OR REPLACE INTO etl_log VALUES (?, ?, ?, current_timestamp)",
            [task, status, message[:1000]],
        )
