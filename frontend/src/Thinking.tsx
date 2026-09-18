/** 小节标题：品牌色竖条 + 标题，与报告视图 Panel 头部同款 */
function H2({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-3 flex items-center gap-2 text-[15px] font-semibold">
      <span className="h-3.5 w-1 rounded-full bg-brand" aria-hidden="true" />
      {children}
    </h2>
  );
}

/** 取舍条目的编号徽章 */
function Num({ n }: { n: number }) {
  return (
    <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-brand/10 text-[11px] font-medium text-brand">
      {n}
    </span>
  );
}

export default function Thinking() {
  return (
    <div className="space-y-6">
      <section className="rounded-lg border border-line bg-white p-5 shadow-card">
        <H2>这个工具解决了什么问题</H2>
        <p className="text-sm leading-7 text-ink/90">
          做文献调研时，研究者通常要在 PubMed 里反复翻页、人工统计年份与期刊分布、肉眼判断影响力、再自己拼一篇综述。
          本工具把「关键词检索 → 统计 → 词云/图表 → 影响力排序 → 中文综述」做成一条龙，
          输入一个关键词即可一站式拿到可读的分析结果，且所有结论均带 PMID 溯源，可点击回到原文核对。
        </p>
      </section>

      <section className="rounded-lg border border-line bg-white p-5 shadow-card">
        <H2>三个工程取舍（为什么这么做）</H2>
        <div className="space-y-4 text-sm leading-7">
          <div>
            <div className="flex items-center gap-2 font-medium text-brand">
              <Num n={1} />
              影响因子/分区用本地指标库，而非实时 API
            </div>
            <p className="text-ink/80">
              PubMed 官方不返回 IF/分区。实时第三方 API 在现场网络下限流严重（实测触发 429 后不可用）；
              因此改为<b>构建期</b>抓取公开数据落成 SQLite 指标库随包发布：SCImago 2025 全量 32,193 条
              （含源方已发布分区）+ OpenAlex 2,709 条兜底，<b>不含任何人工录入值</b>，构建脚本可重复执行、
              抓取地址与文件校验和都留在库里可回查。
              运行时零联网依赖、稳定可控；未收录期刊如实降级显示「未知」并在概览卡给出覆盖率，不中断流程、不编造数值。
            </p>
          </div>
          <div>
            <div className="flex items-center gap-2 font-medium text-brand">
              <Num n={2} />
              检索量 cap，并在近 5 年不足时如实补足
            </div>
            <p className="text-ink/80">
              NCBI E-utilities 对大检索有限流：不挂 API key 时拉到 1000 篇直接 429，挂上 key 可正常返回（实测 5.29s）。
              单次分析默认取前 200 篇（并发 + 缓存下延迟可控，配置可调）。
              Top100 以「近 5 年 + 影响因子降序」为主序；当某些经典主题（如 Alzheimer）近 5 年样本不足 100 篇时，
              按年份就近补足至 100 篇并在表格与导出里标注「补」，而不是悄悄少给几十行。
            </p>
          </div>
          <div>
            <div className="flex items-center gap-2 font-medium text-brand">
              <Num n={3} />
              中文优先 + 单 LLM 综述，不堆 RAG/多智能体
            </div>
            <p className="text-ink/80">
              F1–F3 是确定性统计，不需要向量库/智能体；综述只用「取 Top 摘要 → 1 次 LLM 调用 → 分点中文 + 标 PMID」，
              轻量、可复现、易讲解。过早引入 RAG/多智能体只增复杂度，对本次笔试需求无收益。
            </p>
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-line bg-white p-5 shadow-card">
        <H2>数据可溯源设计</H2>
        <ul className="text-sm leading-7 text-ink/80 list-disc pl-5 space-y-1">
          <li>每张图表、每段综述都标注来源 PMID，点击直达 PubMed 原文。</li>
          <li>综述出自 Top 摘要，关键论断以 [PMID: xxxxx] 标注，降低幻觉不可核查的风险。</li>
          <li>部分PMID无摘要时如实说明，不编造结论。</li>
        </ul>
      </section>

      <section className="rounded-lg border border-line bg-white p-5 shadow-card">
        <H2>界面升级：为什么从表单改成对话</H2>
        <div className="space-y-4 text-sm leading-7">
          <div>
            <div className="flex items-center gap-2 font-medium text-brand">
              <Num n={1} />
              表单的短板不在功能，在「过程不可见」
            </div>
            <p className="text-ink/80">
              原形态是一次性提交：用户点「分析」后只有一个转圈，不知道系统在检索还是在算指标；
              结果一次性铺开，长报告里找重点全靠滚。对文献调研这种「多阶段、可信度要求高」的任务，
              <b>让过程可见本身就是功能</b>——用户能看到检索命中多少篇、指标覆盖了多少、综述引用了几处出处。
            </p>
          </div>
          <div>
            <div className="flex items-center gap-2 font-medium text-brand">
              <Num n={2} />
              升级的边界是「加一层壳」，不是「重写内核」
            </div>
            <p className="text-ink/80">
              对话式外壳只新增了左侧导航、顶部视图切换与消息流；原有的 F1–F4 报告视图
              <b>整体保留为独立视图</b>，接口调用、CSV 导出、深链行为一行未改。
              这样做的理由很直接：报告链路已经端到端验证过，为了换皮去重写它，风险与收益不成比例。
            </p>
          </div>
          <div>
            <div className="flex items-center gap-2 font-medium text-brand">
              <Num n={3} />
              能力清单不虚标
            </div>
            <p className="text-ink/80">
              左侧「快捷开始」9 项中，7 项对应真实可跑的能力；另外「选题助手」「元分析流程」两项
              显式置灰并标注「规划中」。把没做的东西列成已完成，在演示时是必然被问穿的风险项，
              不如当成路线图如实交底。
            </p>
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-line bg-white p-5 shadow-card">
        <H2>工具卡片：能说与不能说的边界</H2>
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

      <section className="rounded-lg border border-line bg-white p-5 shadow-card">
        <H2>已落地（v2）与未来可扩展方向</H2>
        <div className="text-sm leading-7 text-ink/80">
          <div className="font-medium text-brand">v2 已落地</div>
          <ul className="list-disc pl-5 space-y-1">
            <li>
              文献与分析落库：<span className="font-mono text-xs">literature.db</span> 保存检索词（含中文改写映射）、
              文献全量、命中集与分析快照——「查过就有」，历史可回放可重算。
            </li>
            <li>中文检索：术语映射表（高频词零延迟）+ 大模型改写（长尾词，检索验证护栏），结果沉淀回流。</li>
            <li>监控日志：request_id 贯穿全链每一步，双文件按天轮转，排障报码即可定位。</li>
            <li>离群值护栏：指标库 flagged 标记 + 匹配层过滤，极端值不再透出。</li>
          </ul>
          <div className="mt-3 font-medium text-brand">未来可扩展方向</div>
          <ul className="list-disc pl-5 space-y-1">
            <li>服务端 SSE 流式：把工具卡片从「前端回放」换成真实增量推送，顺带支持中途停止。</li>
            <li>受限 Agent：在固定主干上引入意图路由（多轮追问）与 0 命中自主重试，工具注册表已具雏形。</li>
            <li>会话跨设备：历史会话从浏览器 localStorage 迁到 literature.db（库表已就绪）。</li>
            <li>语义检索 / 相似文献推荐：引入向量库（ChromaDB 或 pgvector）。</li>
            <li>MeSH 中文译名映射调研：若权威数据开放可得，可作为术语映射表的增强数据源。</li>
          </ul>
        </div>
      </section>
    </div>
  );
}
