export default function Thinking() {
  return (
    <div className="space-y-6">
      <section className="rounded-lg border border-line bg-white p-5">
        <h2 className="font-semibold mb-2">这个工具解决了什么问题</h2>
        <p className="text-sm leading-7 text-ink/90">
          做文献调研时，研究者通常要在 PubMed 里反复翻页、人工统计年份与期刊分布、肉眼判断影响力、再自己拼一篇综述。
          本工具把「关键词检索 → 统计 → 词云/图表 → 影响力排序 → 中文综述」做成一条龙，
          输入一个关键词即可一站式拿到可读的分析结果，且所有结论均带 PMID 溯源，可点击回到原文核对。
        </p>
      </section>

      <section className="rounded-lg border border-line bg-white p-5">
        <h2 className="font-semibold mb-3">三个工程取舍（为什么这么做）</h2>
        <div className="space-y-4 text-sm leading-7">
          <div>
            <div className="font-medium text-brand">1. 影响因子/分区用内置数据集，而非实时 API</div>
            <p className="text-ink/80">
              PubMed 官方不返回 IF/分区。实时第三方 API 在现场网络下限流严重（实测触发 429 后不可用）；
              因此改为<b>构建期</b>生成一份 1300+ 期刊的指标数据集随包发布：数据来自 OpenAlex 开放数据（近 2 年篇均被引作为 IF 近似），
              并补齐印刷 + 电子 ISSN、对高频缺失刊做策展补录。运行时零联网依赖、稳定可控；
              未收录期刊如实降级显示「未知」并在概览卡给出覆盖率，不中断流程、不编造数值。
            </p>
          </div>
          <div>
            <div className="font-medium text-brand">2. 检索量 cap，并在近 5 年不足时如实补足</div>
            <p className="text-ink/80">
              NCBI E-utilities 对大检索有限流，实测拉到 1000 篇会触发 429。因此单次分析取前 200 篇（并发 + 缓存下延迟可控，配置可调）。
              Top100 以「近 5 年 + 影响因子降序」为主序；当某些经典主题（如 Alzheimer）近 5 年样本不足 100 篇时，
              按年份就近补足至 100 篇并在表格与导出里标注「补」，而不是悄悄少给几十行。
            </p>
          </div>
          <div>
            <div className="font-medium text-brand">3. 中文优先 + 单 LLM 综述，不堆 RAG/多智能体</div>
            <p className="text-ink/80">
              F1–F3 是确定性统计，不需要向量库/智能体；综述只用「取 Top 摘要 → 1 次 LLM 调用 → 分点中文 + 标 PMID」，
              轻量、可复现、易讲解。过早引入 RAG/多智能体只增复杂度，对本次笔试需求无收益。
            </p>
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-line bg-white p-5">
        <h2 className="font-semibold mb-3">数据可溯源设计</h2>
        <ul className="text-sm leading-7 text-ink/80 list-disc pl-5 space-y-1">
          <li>每张图表、每段综述都标注来源 PMID，点击直达 PubMed 原文。</li>
          <li>综述出自 Top 摘要，关键论断以 [PMID: xxxxx] 标注，降低幻觉不可核查的风险。</li>
          <li>部分PMID无摘要时如实说明，不编造结论。</li>
        </ul>
      </section>

      <section className="rounded-lg border border-line bg-white p-5">
        <h2 className="font-semibold mb-3">界面升级：为什么从表单改成对话</h2>
        <div className="space-y-4 text-sm leading-7">
          <div>
            <div className="font-medium text-brand">1. 表单的短板不在功能，在「过程不可见」</div>
            <p className="text-ink/80">
              原形态是一次性提交：用户点「分析」后只有一个转圈，不知道系统在检索还是在算指标；
              结果一次性铺开，长报告里找重点全靠滚。对文献调研这种「多阶段、可信度要求高」的任务，
              <b>让过程可见本身就是功能</b>——用户能看到检索命中多少篇、指标覆盖了多少、综述引用了几处出处。
            </p>
          </div>
          <div>
            <div className="font-medium text-brand">2. 升级的边界是「加一层壳」，不是「重写内核」</div>
            <p className="text-ink/80">
              对话式外壳只新增了左侧导航、顶部视图切换与消息流；原有的 F1–F4 报告视图
              <b>整体保留为独立视图</b>，接口调用、CSV 导出、深链行为一行未改。
              这样做的理由很直接：报告链路已经端到端验证过，为了换皮去重写它，风险与收益不成比例。
            </p>
          </div>
          <div>
            <div className="font-medium text-brand">3. 能力清单不虚标</div>
            <p className="text-ink/80">
              左侧「快捷开始」8 项中，6 项对应真实可跑的能力；另外「选题助手」「元分析流程」两项
              显式置灰并标注「规划中」。把没做的东西列成已完成，在演示时是必然被问穿的风险项，
              不如当成路线图如实交底。
            </p>
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-line bg-white p-5">
        <h2 className="font-semibold mb-3">工具卡片：能说与不能说的边界</h2>
        <ul className="text-sm leading-7 text-ink/80 list-disc pl-5 space-y-1">
          <li>
            卡片名称与入参直接对齐后端真实函数：<span className="font-mono text-xs">pubmed.esearch</span> /
            <span className="font-mono text-xs"> pubmed.efetch</span> /
            <span className="font-mono text-xs"> metrics.annotate</span> /
            <span className="font-mono text-xs"> analyze.aggregate</span> /
            <span className="font-mono text-xs"> review.generate</span>，顺序即真实执行顺序。
          </li>
          <li>卡片上的数值全部取自 <span className="font-mono text-xs">/api/analyze</span> 的真实响应，不编造、不估算。</li>
          <li>
            需要如实说明的一点：当前后端是<b>一次性返回</b>，因此卡片的「逐步点亮」是前端按真实阶段做的回放，
            不是服务端推送；汇总行上的耗时是<b>接口真实往返</b>，不是播放时长。
          </li>
          <li>下一步：后端改 SSE 增量推送（每个阶段 yield 一次），即可去掉回放层。这是实现细节，不影响当前功能完整度。</li>
        </ul>
      </section>

      <section className="rounded-lg border border-line bg-white p-5">
        <h2 className="font-semibold mb-3">未来可扩展方向</h2>
        <ul className="text-sm leading-7 text-ink/80 list-disc pl-5 space-y-1">
          <li>服务端 SSE 流式：把工具卡片从「前端回放」换成真实增量推送，顺带支持中途停止。</li>
          <li>任务编排：把一次分析拆成可追踪的子任务清单，支持长任务与失败重试。</li>
          <li>技能包目录化：把提示词与快捷入口从代码常量改为 <span className="font-mono text-xs">skills/*/SKILL.md</span> 目录驱动，新增分析场景无需改前端。</li>
          <li>会话持久化：当前历史会话存在浏览器 localStorage，后续落库以支持跨设备。</li>
          <li>语义检索 / 相似文献推荐：引入向量库（ChromaDB 或 pgvector）。</li>
          <li>用户多轮追问：升级为 RAG 问答或多智能体协作。</li>
          <li>持久化分析历史：引入 PostgreSQL 存储结果（已附数据模型设计）。</li>
        </ul>
      </section>
    </div>
  );
}
