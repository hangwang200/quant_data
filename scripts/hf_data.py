"""Sync data/quant.duckdb with a private Hugging Face dataset repo.

Usage:
    python scripts/hf_data.py upload     # local -> HF
    python scripts/hf_data.py download   # HF -> local

Login once first:  python -c "from huggingface_hub import login; login()"
"""
import sys
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download, whoami

REPO_NAME = "quant_data"
FILENAME = "quant.duckdb"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LOCAL_DB = DATA_DIR / FILENAME


def repo_id() -> str:
    return f"{whoami()['name']}/{REPO_NAME}"


def upload() -> None:
    wal = LOCAL_DB.with_suffix(".duckdb.wal")
    if wal.exists():
        sys.exit(f"{wal.name} exists: close every DuckDB connection (or run CHECKPOINT) first.")
    rid = repo_id()
    api = HfApi()
    api.create_repo(rid, repo_type="dataset", private=True, exist_ok=True)
    print(f"Uploading {LOCAL_DB} ({LOCAL_DB.stat().st_size / 2**30:.2f} GiB) -> {rid} ...")
    api.upload_file(
        path_or_fileobj=str(LOCAL_DB),
        path_in_repo=FILENAME,
        repo_id=rid,
        repo_type="dataset",
        commit_message="Update quant.duckdb",
    )
    print(f"Done: https://huggingface.co/datasets/{rid}")


def download() -> None:
    rid = repo_id()
    path = hf_hub_download(rid, FILENAME, repo_type="dataset", local_dir=DATA_DIR)
    print(f"Downloaded to {path}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"upload": upload, "download": download}.get(cmd, lambda: sys.exit(__doc__))()
