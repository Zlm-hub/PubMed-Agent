"""FastAPI 入口：/api/health, /api/analyze（检索 + 聚合 + 中文综述）, /api/demo/presets, /api/logs。"""
import glob
import json
import os

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import cache, config, monitor, pipeline

app = FastAPI(title="PubMed 文献分析", version="0.4.0")

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


@app.get("/api/logs")
def api_logs(tail: int = 100):
    """查看最近的监控日志（决策 D2）：返回当前 app 日志最后 N 行，便于现场排障。"""
    tail = max(1, min(tail, 500))
    log_dir = config.LOG_DIR
    files = sorted(glob.glob(os.path.join(log_dir, "app*.log")))
    if not files:
        return {"file": None, "lines": []}
    latest = files[-1]
    try:
        with open(latest, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return {"file": os.path.basename(latest), "lines": []}
    return {"file": os.path.basename(latest), "lines": [ln.rstrip("\n") for ln in lines[-tail:]]}


@app.post("/api/analyze")
async def api_analyze(req: AnalyzeRequest, request: Request):
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query 不能为空")
    max_results = max(1, min(req.max_results, config.MAX_RESULTS))

    # request_id 贯穿本次请求的所有日志；响应体也带上，排障时报这个码即可
    rid = monitor.set_request_id()
    monitor.step("api", "request.start", query=query, retmax=max_results,
                 review=req.include_review, client=request.client.host if request.client else None)

    key = cache.cache_key(query, max_results, req.include_review)
    if key in _cache:
        # 命中预缓存：保留生成时的真实 trace，仅标记来源，前端据此显示「预缓存秒回」
        monitor.step("api", "cache.hit", key=key)
        return {**_cache[key], "cached": True, "request_id": rid}

    # 全流程交给 pipeline，接口层只负责参数校验与缓存
    try:
        payload = await pipeline.build_payload(query, max_results, req.include_review)
    except Exception as e:  # noqa: BLE001
        monitor.step("api", "pipeline.failed", ok=False, exc=True, query=query, error=str(e))
        raise HTTPException(status_code=502, detail=f"分析流水线失败（request_id: {rid}）: {e}")

    _cache[key] = payload
    # 0 命中的结果只进内存缓存（重启即失效），不落文件——否则空结果被固化，
    # 后续改进（如中文改写上线）也永远轮不到跑，实测踩过的坑。
    if payload.get("total", 0) > 0:
        _persist_cache(key, payload)

    payload["request_id"] = rid
    monitor.step("api", "request.done", total=payload.get("total"),
                 cached=False, elapsed_ms=payload.get("trace") and sum(
                     t.get("ms", 0) for t in payload["trace"]))
    return payload


@app.on_event("startup")
def _warm():
    import importlib

    monitor.setup(
        level=config.LOG_LEVEL,
        log_dir=config.LOG_DIR,
        retention_app=config.LOG_RETENTION_DAYS_APP,
        retention_error=config.LOG_RETENTION_DAYS_ERROR,
    )
    monitor.step("api", "startup", presets=config.PRESETS,
                 query_rewrite=config.QUERY_REWRITE)
    importlib.import_module("app.metrics").load()
    _load_file_cache()


def main():
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
