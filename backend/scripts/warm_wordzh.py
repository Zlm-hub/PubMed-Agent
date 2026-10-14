"""预热词云中文词典：把 cache/*.json 里出现的英文词与 MeSH 主题词一次性翻好落库。

为什么要预热：词云/主题词的中文化是「词典命中 0ms、未命中一次批量机翻」。
预缓存的关键词（现场演示用的那几个）若先预热一轮，演示时全程零延迟、零 LLM 调用。

用法（在 backend 目录下）：
    .venv/Scripts/python.exe -m scripts.warm_wordzh
    .venv/Scripts/python.exe -m scripts.warm_wordzh --dry   # 只看要翻哪些词，不落库
"""
import asyncio
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, wordzh  # noqa: E402


def collect_terms() -> dict[str, set[str]]:
    """返回 {缓存文件: 该文件需要的词集合}。"""
    out: dict[str, set[str]] = {}
    for path in sorted(glob.glob(os.path.join(config.CACHE_DIR, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        out[os.path.basename(path)] = set(wordzh.payload_terms(payload))
    return out


async def main() -> None:
    dry = "--dry" in sys.argv
    per_file = collect_terms()
    all_terms = sorted({t for terms in per_file.values() for t in terms})
    print(f"缓存文件 {len(per_file)} 个，去重后待翻译词 {len(all_terms)} 个")
    if not all_terms:
        print("没有可预热的词（cache/ 为空？）")
        return

    if dry:
        for name, terms in per_file.items():
            print(f"  {name}: {len(terms)} 词")
        print("（--dry 模式，不调用模型、不落库）")
        return

    # wordzh.MAX_TERMS 是「单次调用」的防御上限；预热要覆盖全部词，因此按批推进
    zh: dict[str, str] = {}
    batch = 200
    for i in range(0, len(all_terms), batch):
        part = all_terms[i : i + batch]
        got = await wordzh.translate_terms(part)
        zh.update(got)
        print(f"  [{min(i + batch, len(all_terms))}/{len(all_terms)}] 本批译出 {len(got)}/{len(part)}")

    hit = len(zh)
    print(f"译名 {hit}/{len(all_terms)}（命中率 {round(100 * hit / len(all_terms))}%）")
    miss = [t for t in all_terms if t not in zh]
    if miss:
        print(f"未翻到 {len(miss)} 个（缩写/生僻词等，展示层会回退英文）：{miss[:20]}")


if __name__ == "__main__":
    asyncio.run(main())
