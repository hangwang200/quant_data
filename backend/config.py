from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = Path(os.environ.get("QUANT_DB", DATA_DIR / "quant.duckdb"))

# 行情起始日：回测从 2015 开始，多留一年用于计算 120 日动量等回看因子
PRICE_START = "2014-01-01"
FIN_START_YEAR = 2013

BENCHMARKS = {
    "sh.000300": "沪深300",
    "sh.000905": "中证500",
    "sh.000001": "上证指数",
}

ETL_WORKERS = int(os.environ.get("QUANT_ETL_WORKERS", "4"))
