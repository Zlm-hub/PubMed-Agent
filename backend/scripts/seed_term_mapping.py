"""预置中文→英文术语映射表（L0，交付期一次性）。

条目由 LLM 起草 + 人工复核固化（status=approved）。术语均为医学规范译名，
主流词都对应 MeSH 规范名或 PubMed 高频写法。运行期还会持续回流候选
（llm-reflow），经回译/试搜校验后人工确认升级 approved。

用法：
    .venv/Scripts/python.exe scripts/seed_term_mapping.py            # 只补空缺
    .venv/Scripts/python.exe scripts/seed_term_mapping.py --force    # 覆盖已有
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import literaturedb  # noqa: E402

# (中文词, 英文检索词, [同义词])
SEED = [
    ("渐冻症", "amyotrophic lateral sclerosis", ["motor neuron disease"]),
    ("肌萎缩侧索硬化", "amyotrophic lateral sclerosis", []),
    ("渐冻人症", "amyotrophic lateral sclerosis", []),
    ("糖尿病", "diabetes mellitus", []),
    ("1型糖尿病", "type 1 diabetes mellitus", []),
    ("2型糖尿病", "type 2 diabetes mellitus", []),
    ("妊娠糖尿病", "gestational diabetes mellitus", []),
    ("高血压", "hypertension", []),
    ("阿尔茨海默", "alzheimer disease", []),
    ("阿尔茨海默病", "alzheimer disease", []),
    ("老年痴呆", "dementia", ["alzheimer disease"]),
    ("帕金森", "parkinson disease", []),
    ("帕金森病", "parkinson disease", []),
    ("癌症", "cancer", ["neoplasms"]),
    ("肿瘤", "neoplasms", ["tumor"]),
    ("肺癌", "lung cancer", ["lung neoplasms"]),
    ("胃癌", "gastric cancer", ["stomach neoplasms"]),
    ("肝癌", "liver cancer", ["liver neoplasms", "hepatocellular carcinoma"]),
    ("乳腺癌", "breast cancer", ["breast neoplasms"]),
    ("结直肠癌", "colorectal cancer", ["colorectal neoplasms"]),
    ("宫颈癌", "cervical cancer", ["uterine cervical neoplasms"]),
    ("前列腺癌", "prostate cancer", ["prostatic neoplasms"]),
    ("白血病", "leukemia", []),
    ("淋巴瘤", "lymphoma", []),
    ("黑色素瘤", "melanoma", []),
    ("新冠", "covid-19", ["SARS-CoV-2"]),
    ("新冠肺炎", "covid-19", []),
    ("流感", "influenza", []),
    ("肺炎", "pneumonia", []),
    ("肺结核", "tuberculosis", []),
    ("乙肝", "hepatitis b", ["hepatitis b virus"]),
    ("脂肪肝", "fatty liver", ["non-alcoholic fatty liver disease"]),
    ("冠心病", "coronary artery disease", ["coronary heart disease"]),
    ("中风", "stroke", []),
    ("脑卒中", "stroke", []),
    ("脑梗", "cerebral infarction", ["ischemic stroke"]),
    ("心梗", "myocardial infarction", []),
    ("心肌梗死", "myocardial infarction", []),
    ("心力衰竭", "heart failure", []),
    ("房颤", "atrial fibrillation", []),
    ("哮喘", "asthma", []),
    ("慢阻肺", "chronic obstructive pulmonary disease", ["COPD"]),
    ("肺气肿", "pulmonary emphysema", []),
    ("肾衰竭", "kidney failure", ["renal failure"]),
    ("尿毒症", "uremia", ["renal insufficiency"]),
    ("肾炎", "nephritis", []),
    ("红斑狼疮", "lupus erythematosus", ["systemic lupus erythematosus"]),
    ("类风湿", "rheumatoid arthritis", []),
    ("类风湿关节炎", "rheumatoid arthritis", []),
    ("强直性脊柱炎", "ankylosing spondylitis", []),
    ("痛风", "gout", []),
    ("甲亢", "hyperthyroidism", []),
    ("甲减", "hypothyroidism", []),
    ("贫血", "anemia", []),
    ("白内障", "cataract", []),
    ("青光眼", "glaucoma", []),
    ("近视", "myopia", []),
    ("抑郁症", "depression", ["depressive disorder"]),
    ("焦虑症", "anxiety", ["anxiety disorders"]),
    ("精神分裂症", "schizophrenia", []),
    ("自闭症", "autism", ["autism spectrum disorder"]),
    ("多动症", "attention deficit hyperactivity disorder", ["ADHD"]),
    ("癫痫", "epilepsy", []),
    ("偏头痛", "migraine", []),
    ("失眠", "sleep initiation and maintenance disorders", ["insomnia"]),
    ("骨质疏松", "osteoporosis", []),
    ("颈椎病", "cervical spondylosis", []),
    ("腰椎间盘突出", "lumbar disc herniation", []),
    ("前列腺炎", "prostatitis", []),
    ("子宫肌瘤", "uterine fibroids", ["uterine leiomyoma"]),
    ("多囊卵巢", "polycystic ovary syndrome", ["PCOS"]),
    ("不孕不育", "infertility", []),
    ("化疗", "chemotherapy", ["drug therapy"]),
    ("放疗", "radiotherapy", ["radiation therapy"]),
    ("免疫治疗", "immunotherapy", []),
    ("干细胞", "stem cells", []),
    ("基因治疗", "gene therapy", []),
    ("肠道菌群", "gut microbiota", ["gut microbiome"]),
    ("疫苗", "vaccine", ["vaccination"]),
    ("肥胖", "obesity", []),
    ("衰老", "aging", []),
]


def main(force: bool = False) -> None:
    conn = literaturedb.connect()
    inserted = skipped = 0
    try:
        for cn, en, syn in SEED:
            row = literaturedb.lookup_mapping(conn, cn)
            # approved 已存在的跳过（幂等）；--force 才覆盖
            if row and not force:
                skipped += 1
                continue
            literaturedb.upsert_mapping(
                conn, cn, en, syn, source="seed", status="approved"
            )
            inserted += 1
        total = conn.execute(
            "SELECT COUNT(*) c FROM term_mapping WHERE status='approved'"
        ).fetchone()["c"]
    finally:
        conn.close()
    print(f"[seed] 新增 {inserted} 条 · 跳过已有 {skipped} 条 · 正式映射共 {total} 条")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
