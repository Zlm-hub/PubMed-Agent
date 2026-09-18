"""离线预生成演示缓存：对 PRESETS 跑真实 NCBI 管线（含真实大模型综述），写 cache/<md5>.json。

现场即使 NCBI/DashScope 不可用，后端启动也会把这些结果载入内存，一键演示秒回。

用法（推荐，综述由真实大模型生成）：
    .venv/Scripts/python.exe scripts/precache.py
断网演练时改用示例综述（不调大模型，快但不体现 LLM 能力）：
    MOCK_LLM=1 .venv/Scripts/python.exe scripts/precache.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import cache, config, metrics, pipeline

CACHE_DIR = config.CACHE_DIR
MAX_RESULTS = 200


async def run_one(query: str) -> dict:
    # 与在线请求走同一个编排入口，保证离线预缓存与在线结果结构完全一致
    return await pipeline.build_payload(query, MAX_RESULTS, include_review=True)


def main():
    metrics.load()
    os.makedirs(CACHE_DIR, exist_ok=True)
    for q in config.PRESETS:
        try:
            print(f"预缓存中: {q} ...", flush=True)
            payload = asyncio.run(run_one(q))
            key = cache.cache_key(q, MAX_RESULTS, include_review=True)
            with open(os.path.join(CACHE_DIR, f"{key}.json"), "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            print(f"  ✓ 命中 {payload['total']} 篇，缓存 {len(payload['articles'])} 篇 -> {key}.json")
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ 失败: {e}")


if __name__ == "__main__":
    main()
