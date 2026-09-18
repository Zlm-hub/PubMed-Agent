"""NCBI E-utilities 检索：esearch 拿 PMID，efetch(medline/xml) 批量取元数据。"""
import asyncio
import datetime
import re
import xml.etree.ElementTree as ET

import httpx

from . import config

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
EFETCH_BATCH = 150


def _local(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _find_text(el, local: str):
    for child in el.iter():
        if _local(child.tag) == local and child.text and child.text.strip():
            return child.text.strip()
    return None


def _findall_text(el, local: str):
    out = []
    for child in el.iter():
        if _local(child.tag) == local and child.text and child.text.strip():
            out.append(child.text.strip())
    return out


def _year_from_pubdate(pubdate_el) -> int | None:
    if pubdate_el is None:
        return None
    y = pubdate_el.findtext("Year")
    if y and y.isdigit():
        return int(y)
    md = pubdate_el.findtext("MedlineDate")
    if md:
        m = re.search(r"\d{4}", md)
        if m:
            return int(m.group())
    return None


def _parse_article(article_el) -> dict:
    pmid = _find_text(article_el, "PMID")
    title = _find_text(article_el, "ArticleTitle") or ""

    # 摘要（可能多段 / 有 Label）
    abs_parts = []
    for ab in article_el.iter():
        if _local(ab.tag) == "AbstractText":
            label = ab.attrib.get("Label")
            txt = (ab.text or "").strip()
            if label and txt:
                abs_parts.append(f"{label}: {txt}")
            elif txt:
                abs_parts.append(txt)
    abstract = " ".join(abs_parts)

    # 作者
    authors = []
    for au in article_el.iter():
        if _local(au.tag) == "Author":
            last = au.findtext("LastName")
            init = au.findtext("Initials")
            if last:
                authors.append(f"{last} {init or ''}".strip())
    authors = authors[:8]

    # 期刊
    journal_title = _find_text(article_el, "Title")
    issn = _find_text(article_el, "ISSN")
    iso = _find_text(article_el, "ISOAbbreviation")

    # 年份
    year = None
    for jiss in article_el.iter():
        if _local(jiss.tag) == "JournalIssue":
            year = _year_from_pubdate(jiss.find("PubDate"))
            break
    if year is None:
        year = _year_from_pubdate(article_el.find(".//PubDate"))
    pubdate = str(year) if year else ""

    # Mesh + 关键词
    mesh = _findall_text(article_el, "DescriptorName")
    keywords = _findall_text(article_el, "Keyword")

    # 出版类型
    pub_types = _findall_text(article_el, "PublicationType")

    return {
        "pmid": pmid,
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "journal": journal_title or iso or "",
        "issn": issn or "",
        "year": year,
        "pubdate": pubdate,
        "mesh": mesh,
        "keywords": keywords,
        "article_types": pub_types,
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
    }


async def _esearch(query: str, max_results: int, api_key: str | None) -> tuple[int, list[str]]:
    params = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": str(max_results),
        "sort": "relevance",
        "tool": config.NCBI_TOOL,
        "email": config.NCBI_EMAIL,
    }
    if api_key:
        params["api_key"] = api_key
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{BASE}/esearch.fcgi", params=params)
        r.raise_for_status()
        data = r.json()
    res = data.get("esearchresult", {})
    count = int(res.get("count", 0))
    pmids = res.get("idlist", [])
    return count, pmids


async def _efetch_batch(pmids: list[str], api_key: str | None) -> list[dict]:
    if not pmids:
        return []
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "rettype": "medline",
        "retmode": "xml",
        "tool": config.NCBI_TOOL,
        "email": config.NCBI_EMAIL,
    }
    if api_key:
        params["api_key"] = api_key
    async with httpx.AsyncClient(timeout=60) as client:
        headers = {"Accept": "application/xml"}
        r = await client.get(f"{BASE}/efetch.fcgi", params=params, headers=headers)
        r.raise_for_status()
        content = r.text
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []
    articles = []
    for art in root.iter():
        if _local(art.tag) == "PubmedArticle":
            parsed = _parse_article(art)
            if parsed.get("pmid"):
                articles.append(parsed)
    return articles


async def search_pubmed(query: str, max_results: int, api_key: str | None = None) -> tuple[int, list[dict]]:
    """返回 (命中总数, 文章元数据列表)。"""
    api_key = api_key or config.NCBI_API_KEY
    count, pmids = await _esearch(query, max_results, api_key)
    pmids = pmids[:max_results]
    if not pmids:
        return count, []
    # 并发分桶
    batches = [pmids[i : i + EFETCH_BATCH] for i in range(0, len(pmids), EFETCH_BATCH)]
    results = await asyncio.gather(*[_efetch_batch(b, api_key) for b in batches])
    articles = [a for sub in results for a in sub]
    return count, articles
