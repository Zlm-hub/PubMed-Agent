"""生成内置期刊指标数据集 journal_metrics.json。

数据来源：近似 2023 JCR 影响因子(IF)与 JCR 分区(Q1-Q4)，为演示用途整理，
非官方精确值。缺失期刊在 metrics.py 中降级为 unknown/None。
格式：list[{"name": 规范期刊名, "issn": ISSN, "if": float, "quartile": "Q1".."Q4"}]
"""
import json
import os

# (规范期刊名, ISSN, 近似2023 IF, JCR分区)
RAW = [
    # 综合/顶级
    ("Nature", "0028-0836", 64.8, "Q1"),
    ("Science", "0036-8075", 56.9, "Q1"),
    ("Cell", "0092-8674", 45.5, "Q1"),
    ("National Science Review", "2095-5138", 16.3, "Q1"),
    ("Proceedings of the National Academy of Sciences of the United States of America", "0027-8424", 9.4, "Q1"),
    ("Nature Communications", "2041-1723", 14.7, "Q1"),
    ("Science Advances", "2375-2548", 11.7, "Q1"),
    ("Communications Biology", "2399-3642", 5.9, "Q2"),
    ("Scientific Reports", "2045-2322", 3.8, "Q2"),
    ("PLOS ONE", "1932-6203", 2.9, "Q3"),
    ("iScience", "2589-0042", 4.7, "Q2"),

    # 综合医学
    ("The New England Journal of Medicine", "0028-4793", 96.2, "Q1"),
    ("The Lancet", "0140-6736", 98.4, "Q1"),
    ("JAMA", "0098-7484", 63.1, "Q1"),
    ("BMJ", "0959-8138", 93.6, "Q1"),
    ("The Lancet Oncology", "1470-2045", 54.4, "Q1"),
    ("The Lancet Neurology", "1474-4422", 48.0, "Q1"),
    ("The Lancet Infectious Diseases", "1473-3099", 56.3, "Q1"),
    ("Nature Medicine", "1078-8956", 82.9, "Q1"),
    ("Annals of Internal Medicine", "0003-4819", 19.6, "Q1"),
    ("JAMA Internal Medicine", "2168-6106", 22.3, "Q1"),
    ("BMC Medicine", "1741-7015", 9.3, "Q1"),
    ("EBioMedicine", "2352-3964", 9.7, "Q1"),

    # 肿瘤
    ("Cancer Cell", "1535-6108", 50.3, "Q1"),
    ("CA: A Cancer Journal for Clinicians", "0007-9235", 254.7, "Q1"),
    ("Journal of Clinical Oncology", "0732-183X", 42.1, "Q1"),
    ("Cancer Research", "0008-5472", 11.2, "Q1"),
    ("Clinical Cancer Research", "1078-0432", 10.0, "Q1"),
    ("Oncogene", "0950-9232", 6.9, "Q2"),
    ("Oncotarget", "1949-2553", 0.0, "Q4"),
    ("Cancer Letters", "0304-3835", 9.7, "Q1"),
    ("Molecular Cancer", "1476-4598", 27.7, "Q1"),
    ("British Journal of Cancer", "0007-0920", 6.4, "Q2"),
    ("Cancers", "2072-6694", 4.5, "Q2"),
    ("Frontiers in Oncology", "2234-943X", 3.5, "Q3"),
    ("OncoImmunology", "2162-4011", 6.5, "Q2"),
    ("Seminars in Cancer Biology", "1044-579X", 12.1, "Q1"),
    ("Neuro-Oncology", "1522-8517", 15.0, "Q1"),

    # 神经/精神
    ("Nature Neuroscience", "1097-6256", 25.0, "Q1"),
    ("Neuron", "0896-6273", 14.7, "Q1"),
    ("Brain", "0006-8950", 14.5, "Q1"),
    ("Alzheimer's and Dementia", "1552-5260", 14.0, "Q1"),
    ("Journal of Neuroscience", "0270-6474", 4.4, "Q2"),
    ("Molecular Psychiatry", "1359-4184", 9.6, "Q1"),
    ("Biological Psychiatry", "0006-3223", 10.6, "Q1"),
    ("American Journal of Psychiatry", "0002-953X", 14.7, "Q1"),
    ("Neuroscience", "0306-4522", 3.3, "Q3"),
    ("Translational Psychiatry", "2158-3188", 5.8, "Q2"),
    ("Acta Neuropathologica", "0001-6322", 11.9, "Q1"),
    ("Cell Death and Differentiation", "1350-9047", 12.4, "Q1"),
    ("Aging Cell", "1474-9718", 7.8, "Q1"),
    ("Neurobiology of Disease", "0969-9961", 5.8, "Q2"),

    # 免疫
    ("Nature Immunology", "1529-2908", 27.7, "Q1"),
    ("Immunity", "1074-7613", 32.4, "Q1"),
    ("Journal of Experimental Medicine", "0022-1007", 12.6, "Q1"),
    ("Nature Reviews Immunology", "1474-1733", 100.3, "Q1"),
    ("Cell Host and Microbe", "1931-3128", 20.8, "Q1"),
    ("Frontiers in Immunology", "1664-3224", 5.7, "Q2"),
    ("Journal of Immunology", "0022-1767", 3.4, "Q3"),
    ("Mucosal Immunology", "1933-0219", 7.3, "Q1"),
    ("Cellular and Molecular Immunology", "1672-7681", 21.8, "Q1"),
    ("Cancer Immunology Research", "2326-6066", 10.1, "Q1"),
    ("Seminars in Immunopathology", "1863-2297", 7.6, "Q2"),

    # 心血管
    ("Circulation", "0009-7322", 37.8, "Q1"),
    ("Circulation Research", "0009-7330", 20.8, "Q1"),
    ("European Heart Journal", "0195-668X", 39.3, "Q1"),
    ("Journal of the American College of Cardiology", "0735-1097", 24.0, "Q1"),
    ("Basic Research in Cardiology", "0304-3840", 7.5, "Q1"),
    ("Cardiovascular Research", "0008-6363", 10.8, "Q1"),

    # 遗传/分子/细胞
    ("Nature Genetics", "1061-4036", 30.7, "Q1"),
    ("Genome Biology", "1474-760X", 12.3, "Q1"),
    ("Genome Medicine", "1756-994X", 12.3, "Q1"),
    ("Nucleic Acids Research", "0305-1048", 14.9, "Q1"),
    ("Molecular Cell", "1097-2765", 14.5, "Q1"),
    ("Cell Metabolism", "1552-390X", 27.7, "Q1"),
    ("Cell Stem Cell", "1934-5909", 19.8, "Q1"),
    ("Developmental Cell", "1534-5807", 10.7, "Q1"),
    ("Genes and Development", "0890-9369", 10.5, "Q1"),
    ("EMBO Journal", "0261-4189", 9.4, "Q1"),
    ("PLoS Genetics", "1553-7390", 3.5, "Q3"),
    ("CRISPR Journal", "2573-1599", 3.9, "Q2"),
    ("The CRISPR Journal", "2573-1599", 3.9, "Q2"),
    ("Genome Research", "1088-9051", 6.5, "Q2"),

    # 微生物/病毒/感染
    ("Nature Microbiology", "2058-5276", 20.5, "Q1"),
    ("Cell Reports", "2211-1247", 7.5, "Q2"),
    ("Journal of Virology", "0022-538X", 5.4, "Q2"),
    ("Virology", "0042-6822", 2.8, "Q3"),
    ("Emerging Infectious Diseases", "1080-6040", 11.8, "Q1"),
    ("Journal of Infection", "0163-4453", 14.3, "Q1"),
    ("Antiviral Research", "0166-3542", 6.6, "Q2"),
    ("mBio", "2150-7511", 5.1, "Q2"),
    ("Frontiers in Microbiology", "1664-302X", 4.0, "Q2"),
    ("Microbiome", "2049-2618", 13.8, "Q1"),
    ("Nature Reviews Microbiology", "1740-1526", 78.3, "Q1"),
    ("Lancet Microbe", "2666-5247", 36.2, "Q1"),

    # 生化/方法
    ("Nature Methods", "1548-7091", 36.1, "Q1"),
    ("Nature Biotechnology", "1087-0156", 33.1, "Q1"),
    ("Nature Chemical Biology", "1552-4450", 12.9, "Q1"),
    ("Bioinformatics", "1367-4803", 5.8, "Q2"),
    ("Briefings in Bioinformatics", "1467-5463", 6.8, "Q2"),
    ("BMC Bioinformatics", "1471-2105", 2.9, "Q3"),
    ("Lab on a Chip", "1473-0197", 6.1, "Q2"),
    ("Analytical Chemistry", "0003-2700", 6.7, "Q2"),

    # 药理/临床
    ("Nature Reviews Drug Discovery", "1474-1776", 120.1, "Q1"),
    ("Cell Reports Medicine", "2666-3791", 11.7, "Q1"),
    ("Pharmacological Reviews", "0031-6997", 19.0, "Q1"),
    ("Drug Resistance Updates", "1368-7646", 22.0, "Q1"),
    ("Acta Pharmacologica Sinica", "1671-4083", 8.2, "Q1"),
    ("Clinical Pharmacology and Therapeutics", "0009-9236", 6.3, "Q2"),
    ("British Journal of Pharmacology", "0007-1188", 6.8, "Q2"),

    # 材料/纳米（部分交叉）
    ("Nature Nanotechnology", "1748-3387", 38.1, "Q1"),
    ("Nature Materials", "1476-1122", 37.2, "Q1"),
    ("Advanced Materials", "0935-9648", 27.4, "Q1"),
    ("Biomaterials", "0142-9612", 12.8, "Q1"),
    ("ACS Nano", "1936-0851", 15.8, "Q1"),
    ("Nano Letters", "1530-6984", 9.6, "Q1"),

    # 公共/流行病
    ("Nature Human Behaviour", "2397-3374", 15.7, "Q1"),
    ("The Lancet Public Health", "2468-2667", 36.0, "Q1"),
    ("BMC Public Health", "1471-2458", 3.0, "Q3"),
    ("Vaccine", "0264-410X", 3.9, "Q2"),
    ("Frontiers in Public Health", "2296-2565", 3.0, "Q3"),
    ("Journal of Medical Virology", "0146-6615", 5.0, "Q2"),

    # 植物/其他
    ("Nature Plants", "2055-026X", 15.8, "Q1"),
    ("The Plant Cell", "1040-4651", 10.0, "Q1"),
    ("Plant Biotechnology Journal", "1467-7644", 10.1, "Q1"),
    ("Scientific Data", "2052-4463", 9.3, "Q1"),

    # 工程/AI 交叉（近年 PubMed 也收）
    ("Nature Biomedical Engineering", "2157-846X", 26.6, "Q1"),
    ("IEEE Transactions on Medical Imaging", "0278-0062", 8.9, "Q1"),
    ("Medical Image Analysis", "1361-8415", 8.6, "Q1"),
    ("Computers in Biology and Medicine", "0010-4825", 6.0, "Q2"),
    ("Journal of Biomedical Informatics", "1532-0464", 3.5, "Q3"),
]

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "journal_metrics.json")


def main():
    seen = set()
    entries = []
    for name, issn, ifv, q in RAW:
        key = (name.lower().strip(), issn)
        if key in seen:
            continue
        seen.add(key)
        entries.append({"name": name, "issn": issn, "if": ifv, "quartile": q})
    meta = {
        "source": "approx 2023 JCR values, curated for demo (not official)",
        "year": 2023,
        "count": len(entries),
        "note": "缺失期刊在 metrics 中降级为 unknown/None。IF 为近似值，仅供演示。",
    }
    payload = {"meta": meta, "journals": entries}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"wrote {len(entries)} journals -> {os.path.abspath(OUT)}")


if __name__ == "__main__":
    main()
