"""补录高频缺失期刊（离线策展，幂等）。

背景：OpenAlex 按「出刊量/被引」抓取的 1200 本未覆盖到一批常见刊
（如 Journal of Alzheimer's Disease 在 Alzheimer 样例里占了 25 篇），
而这些刊在演示里出现频次高、直接影响 F1c 分区图与 F3 Top100 的可读性。

本脚本把一份人工整理的补充表合并进 data/journal_metrics.json：
  - 仅补充「归一化刊名不存在」的条目，绝不覆盖已有数据（幂等可重复执行）；
  - 每条都带印刷 + 电子 ISSN，提升 ISSN 命中率；
  - IF/分区为 2023 JCR 近似值，与主数据集同样标注为演示用途。
运行：.venv/Scripts/python.exe scripts/add_curated_extras.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.metrics import _norm_name  # noqa: E402

DATA_PATH = os.path.join(ROOT, "data", "journal_metrics.json")

# (刊名, 印刷 ISSN, 电子 ISSN, IF, JCR 分区)  IF/分区为 2023 JCR 近似值，仅供演示
EXTRAS = [
    ("Journal of Alzheimer's Disease", "1387-2877", "1875-8908", 3.4, "Q2"),
    ("Aging", "", "1945-4589", 4.2, "Q2"),
    ("Neurodegenerative Disease Management", "1758-2024", "1758-2032", 2.4, "Q3"),
    ("Alzheimer's Research & Therapy", "", "1758-9193", 7.9, "Q1"),
    ("Current Alzheimer Research", "1567-2050", "1875-5828", 2.2, "Q3"),
    ("International Psychogeriatrics", "1041-6102", "1741-203X", 4.5, "Q2"),
    ("Brain Research Bulletin", "0361-9230", "1873-2747", 3.8, "Q2"),
    ("Clinical Biochemistry", "0009-9120", "1873-2933", 2.5, "Q3"),
    ("Biomarkers in Medicine", "1752-0363", "1752-0371", 2.3, "Q3"),
    ("Ageing Research Reviews", "1568-1637", "1872-9649", 12.5, "Q1"),
    ("European Journal of Neurology", "1351-5101", "1468-1331", 4.5, "Q2"),
    ("Dialogues in Clinical Neuroscience", "1294-8322", "1958-5969", 4.2, "Q2"),
    ("Medicina", "1010-660X", "1648-9144", 2.4, "Q3"),
    ("Clinical Medicine", "1470-2118", "1473-4893", 3.6, "Q2"),
    ("Medical Clinics of North America", "0025-7125", "1557-9859", 3.8, "Q2"),
    ("Nursing Clinics of North America", "0029-6465", "1558-1357", 1.8, "Q3"),
    ("Nursing Outlook", "0029-6554", "1528-3968", 3.1, "Q2"),
    ("Journal of Integrative Neuroscience", "0219-6352", "1757-448X", 2.5, "Q3"),
    ("QJM", "1460-2725", "1460-2393", 4.4, "Q2"),
    ("Journal of the National Cancer Institute", "0027-8874", "1460-2105", 5.0, "Q1"),
    ("Nature Protocols", "1754-2189", "1750-2799", 13.1, "Q1"),
    ("Trends in Cancer", "2405-8033", "2405-8025", 18.4, "Q1"),
    ("Cancer Discovery", "2159-8274", "2159-8290", 29.7, "Q1"),
    ("Cell Genomics", "", "2666-979X", 11.1, "Q1"),
    ("Briefings in Functional Genomics", "2041-2649", "2041-2657", 2.3, "Q3"),
    ("Human Vaccines & Immunotherapeutics", "2164-5515", "2164-554X", 4.8, "Q2"),
    ("Expert Review of Vaccines", "1476-0584", "1744-8395", 5.0, "Q2"),
    ("Cellular & Molecular Biology Letters", "1425-8153", "1689-1392", 8.3, "Q1"),
    ("BioTechniques", "0736-6205", "1940-9818", 2.2, "Q3"),
    ("Science China Life Sciences", "1674-7305", "1869-1889", 8.0, "Q1"),
    ("Molecular Biology Reports", "0301-4851", "1573-4978", 2.8, "Q3"),
    ("Cancer Gene Therapy", "0929-1903", "1476-5500", 5.1, "Q2"),
    ("Journal of Travel Medicine", "1195-1982", "1708-8305", 7.0, "Q1"),
    ("Internal Medicine Journal", "1444-0903", "1445-5994", 1.8, "Q3"),
    ("Asian Journal of Psychiatry", "1876-2018", "1876-2026", 3.9, "Q2"),
    ("Journal of Neuro-Ophthalmology", "1070-8022", "1536-5166", 2.0, "Q3"),
    ("Cellular Oncology", "2211-3428", "2211-3436", 6.6, "Q1"),
    ("Autophagy", "1554-8627", "1554-8635", 14.6, "Q1"),
    ("Leukemia", "0887-6924", "1476-5551", 12.8, "Q1"),
    ("Advanced Drug Delivery Reviews", "0169-409X", "1872-8294", 15.2, "Q1"),
    ("Trends in Immunology", "1471-4906", "1471-4914", 13.1, "Q1"),
    ("Cell Death & Disease", "", "2041-4889", 8.1, "Q1"),
    ("Journal of Hematology & Oncology", "", "1756-8722", 29.5, "Q1"),
    ("Annual Review of Immunology", "0732-0582", "1545-3278", 28.3, "Q1"),
    ("Drug Discovery Today", "1359-6446", "1878-5832", 6.5, "Q1"),
    ("Trends in Molecular Medicine", "1471-4914", "1471-499X", 12.8, "Q1"),
    ("Trends in Pharmacological Sciences", "0165-6147", "1873-3735", 13.5, "Q1"),
    ("Molecular Metabolism", "", "2212-8778", 7.0, "Q1"),
    ("Cell Systems", "2405-4712", "2405-4720", 9.0, "Q1"),
    ("Nature Cancer", "", "2662-1347", 23.5, "Q1"),
    ("Protein & Cell", "1674-800X", "1674-8018", 13.6, "Q1"),
    ("International Journal of Biological Sciences", "", "1449-2288", 8.2, "Q1"),
    ("Cancer Medicine", "", "2045-7634", 4.0, "Q2"),
    ("Journal of Advanced Research", "2090-1232", "2090-1224", 11.4, "Q1"),
    ("Molecules and Cells", "1016-8478", "0219-1032", 3.7, "Q2"),
    ("Advanced Healthcare Materials", "2192-2640", "2192-2659", 10.0, "Q1"),
    ("Biomolecules", "", "2218-273X", 5.5, "Q2"),
    ("Applied Biochemistry and Biotechnology", "0273-2289", "1559-0291", 3.3, "Q2"),
    ("Molecular Biotechnology", "1073-6085", "1559-0305", 2.6, "Q3"),
    ("Clinical and Translational Medicine", "", "2001-1326", 7.9, "Q1"),
    ("Journal of Biomedical Science", "1021-7770", "1423-0127", 9.0, "Q1"),
    ("Life Science Alliance", "", "2575-1077", 4.1, "Q2"),
    ("Cancer Metastasis Reviews", "0167-7659", "1573-7233", 7.2, "Q1"),
    ("Anti-Cancer Agents in Medicinal Chemistry", "1871-5206", "1875-5992", 2.4, "Q3"),
    ("Current Pharmaceutical Biotechnology", "1389-2010", "1873-4316", 2.4, "Q3"),
    ("Human Gene Therapy", "1043-0342", "1557-7422", 4.2, "Q2"),
    ("Glycobiology", "0959-6658", "1460-2423", 3.4, "Q2"),
    ("Probiotics and Antimicrobial Proteins", "1867-1306", "1867-1314", 4.9, "Q2"),
    ("Biotechnology Journal", "1860-6768", "1860-7314", 3.8, "Q2"),
    ("Current Issues in Molecular Biology", "", "1467-3045", 3.0, "Q3"),
    ("Cancer Science", "1347-9032", "1349-7006", 4.5, "Q2"),
    ("Genes and Immunity", "1466-4879", "1476-5470", 4.9, "Q2"),
    ("Oral Oncology", "1368-8375", "1879-0593", 5.4, "Q2"),
    ("Clinical Microbiology and Infection", "1198-743X", "1469-0691", 10.9, "Q1"),
    ("Journal of Cellular Physiology", "0021-9541", "1097-4652", 4.5, "Q2"),
    ("Medical Oncology", "1357-0560", "1559-131X", 2.8, "Q3"),
    ("Clinical & Translational Oncology", "1699-048X", "1699-3055", 2.9, "Q3"),
    ("Australasian Psychiatry", "1039-8562", "1440-1665", 1.6, "Q3"),
    ("Expert Review of Respiratory Medicine", "1747-6348", "1747-6356", 3.4, "Q2"),
    ("Future Oncology", "1479-6694", "1744-8301", 3.0, "Q3"),
    ("Medical Principles and Practice", "1011-7571", "1423-0151", 2.6, "Q3"),
    ("Nanomedicine", "1743-5889", "1748-6963", 4.7, "Q2"),
    ("Neurobiology of Aging", "0197-4580", "1558-1497", 4.2, "Q2"),
    ("Journal of Psychiatric Research", "0022-3956", "1879-1379", 4.2, "Q2"),
    ("Psychiatry Research", "0165-1781", "1872-7123", 4.2, "Q2"),
    ("Cortex", "0010-9452", "1973-8102", 3.6, "Q2"),
    ("NeuroImage", "1053-8119", "1095-9572", 4.7, "Q2"),
    ("Journal of Neurology", "0340-5354", "1432-1459", 4.8, "Q1"),
    ("Neurology", "0028-3878", "1526-632X", 7.7, "Q1"),
    ("Brain", "0006-8950", "1460-2156", 10.6, "Q1"),
    ("Alzheimer Disease and Associated Disorders", "0893-0341", "1546-4156", 2.0, "Q3"),
    ("Dementia and Geriatric Cognitive Disorders", "1420-8008", "1421-9824", 2.4, "Q3"),
    ("Journal of Geriatric Psychiatry and Neurology", "0891-9887", "1552-5708", 2.6, "Q3"),
    ("Journal of the American Geriatrics Society", "0002-8614", "1532-5415", 4.3, "Q1"),
    ("BMC Geriatrics", "", "1471-2318", 3.4, "Q2"),
    ("Journal of Nutrition Health and Aging", "1279-7707", "1760-4788", 4.0, "Q2"),
]


def main():
    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)
    journals = data["journals"]
    existing = {_norm_name(j.get("name", "")) for j in journals}

    added, skipped = 0, 0
    for name, pissn, eissn, ifv, q in EXTRAS:
        key = _norm_name(name)
        if not key or key in existing:
            skipped += 1
            continue
        issns = [x for x in (pissn, eissn) if x]
        journals.append({
            "name": name,
            "issn": ",".join(issns),
            "if": ifv,
            "quartile": q,
            "source": "curated-extra",
        })
        existing.add(key)
        added += 1

    data["meta"]["count"] = len(journals)
    data["meta"]["source"] = (
        "curated(JCR 近似) + OpenAlex sources API（真实引文指标，开放数据）+ curated-extra（高频缺失刊补录）"
    )
    data["meta"]["curated_extra"] = added
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"补录 {added} 本，跳过已存在 {skipped} 本；数据集共 {len(journals)} 本")


if __name__ == "__main__":
    main()
