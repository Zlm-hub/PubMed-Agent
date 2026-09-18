"""FastAPI 入口：/api/health, /api/analyze（检索 + 聚合 + 中文综述）, /api/demo/presets。"""
import datetime
import glob
import hashlib
import json
import os

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import config, pipeline, pubmed

app = FastAPI(title="PubMed 文献分析", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:4173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_cache: dict[str, dict] = {}


class AnalyzeRequest(BaseModel):
    query: str
    max_results: int = 200
    include_review: bool = True


def _cache_key(query: str, max_results: int) -> str:
    return hashlib.md5(f"{query}|{max_results}".encode("utf-8")).hexdigest()


def _load_file_cache() -> None:
    """启动时把 cache/*.json 载入内存，使演示预缓存即使断网也能秒回。"""
    if not os.path.isdir(config.CACHE_DIR):
        return
    for path in glob.glob(os.path.join(config.CACHE_DIR, "*.json")):
        key = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path, encoding="utf-8") as f:
                _cache[key] = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue


def _persist_cache(key: str, payload: dict) -> None:
    try:
        os.makedirs(config.CACHE_DIR, exist_ok=True)
        with open(os.path.join(config.CACHE_DIR, f"{key}.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except OSError:
        pass


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "pubmed-analytics"}


@app.get("/api/demo/presets")
def demo_presets():
    return {"presets": config.PRESETS}


@app.post("/api/analyze")
async def api_analyze(req: AnalyzeRequest):
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query 不能为空")
    max_results = max(1, min(req.max_results, config.MAX_RESULTS))

    key = _cache_key(query, max_results)
    if key in _cache:
        return _cache[key]

    try:
        total, articles = await pubmed.search_pubmed(query, max_results, config.NCBI_API_KEY)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"PubMed 检索失败: {e}")

    payload = await pipeline.build_payload(query, total, articles, req.include_review)
    _cache[key] = payload
    _persist_cache(key, payload)
    return payload


@app.on_event("startup")
def _warm():
    import importlib

    importlib.import_module("app.metrics").load()
    _load_file_cache()


def main():
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
