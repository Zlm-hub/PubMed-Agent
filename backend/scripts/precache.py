"""离线预生成演示缓存：对 PRESETS 跑真实 NCBI 管线 + MOCK 综述，写 cache/<md5>.json。

现场即使 NCBI/DashScope 不可用，后端启动也会把这些结果载入内存，一键演示秒回。
用法：MOCK_LLM=1 .venv/Scripts/python.exe scripts/precache.py
"""
import asyncio
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, metrics, pipeline, pubmed

CACHE_DIR = config.CACHE_DIR
MAX_RESULTS = 200


def _key(query: str) -> str:
    return hashlib.md5(f"{query}|{MAX_RESULTS}".encode("utf-8")).hexdigest()


async def run_one(query: str) -> dict:
    total, articles = await pubmed.search_pubmed(query, MAX_RESULTS, config.NCBI_API_KEY)
    return await pipeline.build_payload(query, total, articles, include_review=True)


def main():
    metrics.load()
    os.makedirs(CACHE_DIR, exist_ok=True)
    for q in config.PRESETS:
        try:
            print(f"预缓存中: {q} ...", flush=True)
            payload = asyncio.run(run_one(q))
            key = _key(q)
            with open(os.path.join(CACHE_DIR, f"{key}.json"), "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            print(f"  ✓ 命中 {payload['total']} 篇，缓存 {len(payload['articles'])} 篇 -> {key}.json")
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ 失败: {e}")


if __name__ == "__main__":
    main()
