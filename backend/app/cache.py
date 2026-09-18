"""缓存键：一次请求的哪些参数决定一份结果。

除 query 与 max_results 外，**include_review 必须参与**：
否则「带综述」与「不带综述」的两种请求会互相命中——
前者拿到多余的 review 字段，后者拿到 review=null 却被当成「本次检索没有综述」。
"""
import hashlib


def cache_key(query: str, max_results: int, include_review: bool = True) -> str:
    return hashlib.md5(
        f"{query}|{max_results}|{int(include_review)}".encode("utf-8")
    ).hexdigest()
