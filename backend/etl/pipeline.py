"""ETL 编排：全部步骤幂等，可重复执行；行情按每只股票最后日期增量更新。"""
from __future__ import annotations

import datetime as dt
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from backend.config import BENCHMARKS, FIN_START_YEAR, PRICE_START
from backend.db.conn import connect, log_etl, query_df, upsert_df
from backend.etl import akshare_src, baostock_src, sina_src

log = logging.getLogger("etl")


def _chain(first, futures):
    yield first
    for f in futures:
        yield f.result()


def _as_date(s: pd.Series) -> list[dt.date]:
    """DuckDB 的 DATE 列经 pandas 后是 Timestamp，统一转成 datetime.date 再做比较/格式化。"""
    return list(pd.to_datetime(s).dt.date)


def sync_stock_list():
    baostock_src.login()
    try:
        basic = baostock_src.fetch_stock_list()
        uni = baostock_src.fetch_universe()
    finally:
        baostock_src.logout()
    df = basic.merge(uni, on="code", how="left")
    df["in_universe"] = df["universe_src"].notna()
    upsert_df("stock_basic", df, ["code"])
    log_etl("stock_list", "ok", f"{len(df)} stocks, universe {int(df.in_universe.sum())}")
    log.info("stock list: %d, universe %d", len(df), df.in_universe.sum())


def sync_index():
    last = query_df("SELECT code, max(date) d FROM index_daily GROUP BY code")
    last = dict(zip(last.code, _as_date(last.d)))
    frames = []
    for code in BENCHMARKS:
        # 多取几天重叠，保证 pct_chg 连续
        start = (last[code] - dt.timedelta(days=10)).isoformat() if code in last else PRICE_START
        frames.append(sina_src.fetch_index(code, start))
    df = pd.concat([f for f in frames if not f.empty])
    n = upsert_df("index_daily", df, ["code", "date"])
    log_etl("index", "ok", f"{n} rows")


def universe_codes(scope: str = "all") -> list[str]:
    """all: 2014 年以来上市过的全部 A 股（含退市股，消除幸存者偏差）；core: 当前沪深300+中证500。"""
    if scope == "core":
        sql = "SELECT code FROM stock_basic WHERE in_universe ORDER BY code"
    else:
        sql = (f"SELECT code FROM stock_basic WHERE status = 1 OR out_date >= DATE '{PRICE_START}' "
               "ORDER BY in_universe DESC, code")
    return query_df(sql).code.tolist()


def _spot_fill(codes: list[str], last: dict) -> set[str]:
    """日常增量快速路径：最新日线恰为上一交易日的股票，用全市场快照补上最新交易日。

    - 用快照"昨收"与库中上一交易日收盘核对，确认快照确实是目标交易日（避免指数未更新时错配日期）
    - 昨收与库中收盘不一致 = 当日除权除息，单独刷新这些股票的复权因子
    - 快照时间早于 15:00 视为盘中数据，放弃快速路径
    返回已处理的股票集合。"""
    cal = _as_date(query_df("SELECT DISTINCT date FROM index_daily WHERE code = 'sh.000300' ORDER BY date").date)
    if len(cal) < 2:
        return set()
    target, prev = cal[-1], cal[-2]
    cand = [c for c in codes if last.get(c) == prev]
    if len(cand) < 100:
        return set()
    try:
        spot = sina_src.fetch_spot()
    except Exception as e:  # noqa: BLE001
        log.warning("spot snapshot failed, fall back to per-stock: %r", e)
        return set()
    if (spot.ts.astype(str) >= "15:00:00").mean() < 0.9:
        log.info("spot snapshot looks intraday, skip fast path")
        return set()
    prev_bar = query_df("SELECT code, close, float_share FROM daily_bar WHERE date = ?", [prev])
    m = spot[spot.code.isin(cand)].merge(prev_bar, on="code", suffixes=("", "_db"))
    same = (m.pre_close - m.close_db).abs() <= 0.006
    if same.mean() < 0.9:
        log.warning("spot pre_close mismatch (%.0f%% match), snapshot is not %s; fall back", same.mean() * 100, target)
        return set()
    traded = m[(m.volume > 0) & m.close.notna()].copy()
    bars = pd.DataFrame({
        "code": traded.code, "date": target, "open": traded.open, "high": traded.high, "low": traded.low,
        "close": traded.close, "volume": traded.volume, "amount": traded.amount,
        "turnover": traded.volume / traded.float_share * 100, "pct_chg": None,
        "float_share": traded.float_share, "trade_status": 1,
    })
    upsert_df("daily_bar", bars, ["code", "date"])
    ex_right = m.loc[~same, "code"].tolist()  # 除权除息：刷新复权因子
    adj = []
    for c in ex_right:
        try:
            adj.append(sina_src.fetch_adj_factor(c))
        except Exception as e:  # noqa: BLE001
            log.warning("adj factor %s failed: %r", c, e)
    if adj:
        upsert_df("adj_factor", pd.concat(adj), ["code", "date"])
    log.info("spot fast path: %s, %d bars, %d suspended, %d ex-right", target, len(bars), len(m) - len(traded),
             len(ex_right))
    return set(m.code)


def sync_prices(limit: int | None = None, batch: int = 40, workers: int = 4, scope: str = "all",
                fast: bool = True):
    """增量更新行情。大部分股票只差一天时用全市场快照（约 1 分钟），其余逐只从新浪拉取（约 3 秒/只）。
    逐只拉取时复权因子全量刷新（分红送转会改变历史因子）。"""
    codes = universe_codes(scope)
    if limit:
        codes = codes[:limit]
    last = query_df("SELECT code, max(date) d FROM daily_bar GROUP BY code")
    last = dict(zip(last.code, _as_date(last.d)))
    today = dt.date.today()
    tasks = []
    delisted = set(query_df("SELECT code FROM stock_basic WHERE status = 0").code)
    handled: set[str] = set()
    if fast and not limit:
        handled = _spot_fill([c for c in codes if c not in delisted], last)
        if handled:
            last = query_df("SELECT code, max(date) d FROM daily_bar GROUP BY code")
            last = dict(zip(last.code, _as_date(last.d)))
    latest = _as_date(query_df("SELECT max(date) d FROM index_daily").d)[0]
    for c in codes:
        if c in handled or (c in last and last[c] >= latest and c not in delisted):
            continue  # 已是最新交易日，或已由快照处理（含当日停牌）
        if c in last and c in delisted:
            continue  # 已退市且已有数据，无需再更新
        if c in last:
            if last[c] >= today:
                continue
            tasks.append((c, (last[c] + dt.timedelta(days=1)).isoformat(), True))
        else:
            tasks.append((c, PRICE_START, True))
    log.info("prices: %d stocks to update", len(tasks))
    if not tasks:
        log_etl("prices", "ok", "up to date")
        return
    bars_buf, adj_buf, errors, done = [], [], [], 0

    def flush():
        if bars_buf:
            upsert_df("daily_bar", pd.concat(bars_buf), ["code", "date"])
        if adj_buf:
            upsert_df("adj_factor", pd.concat(adj_buf), ["code", "date"])
        bars_buf.clear()
        adj_buf.clear()

    # AkShare 的新浪接口依赖 mini_racer(V8)，多线程同时首次初始化会导致进程崩溃：先在主线程同步跑一个任务完成初始化
    first = sina_src.fetch_one(tasks[0])
    with ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(sina_src.fetch_one, t) for t in tasks[1:]]
        for fut in _chain(first, as_completed(futs)):
            code, bars, adj, err = fut
            done += 1
            if err:
                errors.append(f"{code}: {err}")
            else:
                if bars is not None and not bars.empty:
                    bars_buf.append(bars)
                if adj is not None and not adj.empty:
                    adj_buf.append(adj)
            if done % batch == 0:
                flush()
                log.info("prices %d/%d (%d errors)", done, len(tasks), len(errors))
                log_etl("prices", "running", f"{done}/{len(tasks)}")
    flush()
    log_etl("prices", "ok" if not errors else "partial",
            f"{done} done, {len(errors)} errors; " + "; ".join(errors[:5]))
    log.info("prices done, %d errors", len(errors))


def sync_index_members(start_year: int = 2014):
    """每月末一次历史成分股快照；已有的月份跳过。"""
    have = query_df("SELECT DISTINCT index_code, date FROM index_member")
    have = set(zip(have.index_code, _as_date(have.date)))
    months = pd.date_range(f"{start_year}-01-01", dt.date.today(), freq="ME").date.tolist()
    if not months or months[-1] < dt.date.today():
        months.append(dt.date.today())
    todo = [(i, m) for i in ("hs300", "zz500") for m in months if (i, m) not in have or m == months[-1]]
    log.info("index members: %d snapshots", len(todo))
    if not todo:
        return
    import time as _t
    # 当月快照：先删掉旧的"今天"快照，避免累积
    with connect(read_only=False) as con:
        con.execute("DELETE FROM index_member WHERE date > last_day(current_date - INTERVAL 1 MONTH)")
    baostock_src.login()
    frames, errors = [], []
    try:
        for k, (i, m) in enumerate(todo, 1):
            for attempt in range(4):  # baostock 连接偶尔被重置：重试并重新登录
                try:
                    frames.append(baostock_src.fetch_index_members(i, m.isoformat()))
                    break
                except Exception as e:  # noqa: BLE001
                    if attempt == 3:
                        errors.append(f"{i} {m}: {e!r}"[:120])
                    _t.sleep(3 * (attempt + 1))
                    try:
                        baostock_src.logout()
                    except Exception:  # noqa: BLE001
                        pass
                    baostock_src.login()
            if k % 24 == 0 or k == len(todo):
                if frames:
                    upsert_df("index_member", pd.concat(frames), ["index_code", "date", "code"])
                    frames.clear()
                log.info("index members %d/%d (%d errors)", k, len(todo), len(errors))
    finally:
        baostock_src.logout()
    log_etl("index_members", "ok" if not errors else "partial",
            f"{len(todo)} snapshots, {len(errors)} errors; " + "; ".join(errors[:3]))


def sync_st(workers: int = 4, full: bool = False, shares_only: bool = False):
    """历史 ST 状态（baostock isST）。退市股同时用 baostock 换手率回填流通股本（新浪不提供）。
    较慢（约 1.5 秒/只/进程），默认只增量拉取上次运行之后的数据。
    shares_only: 只为"有行情但缺流通股本"的退市股回填股本（行情下载完成后运行）。"""
    from concurrent.futures import ProcessPoolExecutor

    codes = universe_codes("all")
    delisted = set(query_df("SELECT code FROM stock_basic WHERE status = 0").code)
    no_share = set(query_df("SELECT code FROM daily_bar GROUP BY code HAVING count(float_share) = 0").code) & delisted
    done = query_df("SELECT task, message FROM etl_log WHERE task = 'st'")
    since = None if full or done.empty else done.message.iloc[0].split("|")[0]
    tasks = []
    for c in codes:
        if shares_only:
            if c in no_share:
                tasks.append((c, PRICE_START, True))
            continue
        if since and c in delisted and c not in no_share:
            continue
        start = PRICE_START if (not since or c in no_share) else since
        tasks.append((c, start, c in no_share))
    log.info("st: %d stocks (since %s)", len(tasks), since or PRICE_START)
    st_buf, share_buf, errors = [], [], []

    def flush():
        if st_buf:
            upsert_df("st_daily", pd.concat(st_buf), ["code", "date"])
        for sh in share_buf:
            with connect(read_only=False) as con:
                con.register("_sh", sh)
                con.execute("""UPDATE daily_bar b SET turnover = s.turnover,
                                   float_share = CASE WHEN s.turnover > 0 THEN b.volume / (s.turnover / 100) END
                               FROM _sh s WHERE b.code = s.code AND b.date = s.date""")
                con.unregister("_sh")
        st_buf.clear()
        share_buf.clear()

    with ProcessPoolExecutor(workers, initializer=baostock_src.worker_init) as ex:
        for k, (code, st, share, err) in enumerate(ex.map(baostock_src.worker_st, tasks, chunksize=8), 1):
            if err:
                errors.append(f"{code}: {err}")
                continue
            if st:
                st_buf.append(pd.DataFrame({"code": code, "date": st}))
            if share is not None and not share.empty:
                share_buf.append(share.assign(code=code))
            if k % 200 == 0:
                flush()
                log.info("st %d/%d (%d errors)", k, len(tasks), len(errors))
    flush()
    if shares_only:
        log_etl("shares", "ok" if not errors else "partial", f"{len(tasks)} delisted stocks, {len(errors)} errors")
        return
    # message: "截至日期|说明"，下次从截至日期增量
    log_etl("st", "ok" if not errors else "partial",
            f"{dt.date.today().isoformat()}|{len(tasks)} stocks, {len(errors)} errors; " + "; ".join(errors[:3]))


def sync_financial_period(report_date: dt.date) -> int:
    df = akshare_src.fetch_report(report_date)
    cols = [c for c in query_df("SELECT * FROM financial_report LIMIT 0").columns if c in df.columns]
    return upsert_df("financial_report", df[cols], ["code", "report_date"])


def sync_financials(periods: list[dt.date] | None = None, refresh_recent: int = 2, workers: int = 3):
    """下载报告期财报。默认全部历史报告期，已有数据的期跳过（最近 refresh_recent 期总是刷新）。"""
    all_periods = periods or akshare_src.report_periods(FIN_START_YEAR)
    if periods is None:
        have = query_df("SELECT report_date, count(*) n FROM financial_report GROUP BY 1")
        have = set(_as_date(have.report_date[have.n > 1000]))
        recent = set(all_periods[-refresh_recent:])
        all_periods = [p for p in all_periods if p not in have or p in recent]
    log.info("financials: %d periods", len(all_periods))
    errors = []
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(akshare_src.fetch_report, p): p for p in all_periods}
        for f in as_completed(futs):
            p = futs[f]
            try:
                df = f.result()
                cols = [c for c in query_df("SELECT * FROM financial_report LIMIT 0").columns if c in df.columns]
                n = upsert_df("financial_report", df[cols], ["code", "report_date"])
                log.info("financial %s: %d rows", p, n)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{p}: {e!r}"[:200])
                log.warning("financial %s failed: %r", p, e)
    log_etl("financials", "ok" if not errors else "partial", f"{len(all_periods)} periods; " + "; ".join(errors[:3]))


def sync_dividends(refresh_recent: int = 4, workers: int = 2):
    """分红送配：全部历史报告期，已有的期跳过（最近几期总是刷新，方案进度会变化）。"""
    periods = akshare_src.report_periods(FIN_START_YEAR)
    have = set(_as_date(query_df("SELECT DISTINCT report_date FROM dividend").report_date))
    recent = set(periods[-refresh_recent:])
    todo = [p for p in periods if p not in have or p in recent]
    log.info("dividends: %d periods", len(todo))
    errors = []
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(akshare_src.fetch_dividend, p): p for p in todo}
        for f in as_completed(futs):
            p = futs[f]
            try:
                n = upsert_df("dividend", f.result(), ["code", "report_date"])
                log.info("dividend %s: %d rows", p, n)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{p}: {e!r}"[:200])
                log.warning("dividend %s failed: %r", p, e)
    log_etl("dividends", "ok" if not errors else "partial", f"{len(todo)} periods; " + "; ".join(errors[:3]))


def run_all(limit: int | None = None, skip_financials: bool = False, refresh_stocks: bool = False,
            scope: str = "all", with_st: bool = False):
    from backend.factors.build import build_all

    # 股票列表来自 baostock，较慢且变化少：已有数据时默认跳过，--refresh-stocks 强制刷新
    if refresh_stocks or query_df("SELECT count(*) n FROM stock_basic").n.iloc[0] == 0:
        sync_stock_list()
    sync_index()
    sync_prices(limit=limit, scope=scope)
    if with_st:
        sync_st()
        sync_st(shares_only=True)
        sync_index_members()
    if not skip_financials:
        sync_financials()
        sync_dividends()
    build_all()
