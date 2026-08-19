# 证据、置信度、基准比较与追问口径

## 证据强度

| 强度 | 定义 | 对评分的作用 |
|---|---|---|
| `strong` | 有具体情境、候选人行动和结果，且来源可定位到简历或问答编号。 | 可显著支持对应维度结论。 |
| `medium` | 有行动或结果，但缺少情境、结果、职责边界或外部佐证的一部分。 | 形成暂定判断，并输出追问。 |
| `weak` | 关键词、自我评价、笼统表态或难以定位的描述。 | 只能形成假设，不支撑高置信度。 |
| `missing` | 当前材料未提供相关事实。 | 标记为待验证；不能反向判定候选人不足。 |

`counter_evidence` 只能使用材料中明确存在、与工作相关的反证或矛盾行为。不得用材料缺失、非工作相关信息或主观印象作为反证。

## 证据索引与原文校验

- 证据索引只包含两类来源：`"简历"`（脱敏后的简历文本）、每个真实 `question_id`（对应回答文本）。
- 每条证据 `source` 必须存在于索引；`excerpt` 必须非空，且经保守归一化后是对应原文的**真实子串**（不允许语义相似代替原文）。
- `evidence` 列表 `polarity` 必须为 `supportive`；`counter_evidence` 列表必须为 `counter`；`strength=missing` 不算有效证据。
- 无效证据被移除并记入 `evidence_validation_issues`，不得简单删除后保留原高分。

## 分数与置信度互不决定

- `score`（0–100）表示**当前材料对画像锚点的探索性支持度**，不是人格高低或未来表现预测。
- `confidence` 表示**证据充分性**（当前判断的证据可靠程度）。
- 两者由不同规则独立确定；**基准差值、overall_score、similarity 均不参与置信度计算**。

## 确定性置信度规则（初始证据充分度规则，后续可由业务校准）

置信度**只**由证据充分性决定，不信任模型返回的 confidence 字段。阈值常量集中配置，可读、可调。

### 低置信度 low

满足任一条件：

- 该维没有有效支持性证据；
- 该维有效支持性证据全部来自简历（无经过原文校验的面试问答证据）；
- 存在未解决的证据校验问题（无效证据已移除）；
- 存在强反向证据且尚未完成补证。

规则：没有有效证据时 coverage=0；只有简历证据时 coverage 上限 55；不得输出确定性画像匹配结论。

### 中置信度 medium

同时满足：

- 至少 1 条经过原文校验的面试问答证据；
- 该证据 strength 为 medium 或 strong；
- coverage 在 60–79 之间；
- 不存在强反向证据；
- 不存在证据校验问题。

### 高置信度 high

同时满足：

- 至少 2 条经过原文校验的面试问答证据；
- 证据来自至少 2 个不同 question_id；
- 至少 1 条证据 strength 为 strong；
- coverage 不低于 80；
- 不存在强反向证据；
- 不存在证据校验问题。

### 每维确定性字段

`confidence`、`confidence_reason`、`valid_resume_evidence_count`、`valid_interview_evidence_count`、`distinct_interview_source_count`。HTML 中 low/medium/high 显示为「低/中/高」并附简短原因。

## 基准比较状态 benchmark_comparison_status

| 状态 | 条件 | 页面显示 |
|---|---|---|
| `not_comparable` | confidence=low，或无有效面试证据，或 coverage<60 | 「当前证据不足，暂不判断是否达到画像基准。」不得出现高于/低于/达到/符合基准。 |
| `exploratory` | confidence 非 low，但 benchmark_status=draft | 「当前材料与草案画像的差异仅供探索性参考。」可显示分数与基准分，但禁止「已达到/优于/符合成功画像」等确定性措辞。 |
| `comparable` | confirmed + confidence medium/high + 有面试证据 + coverage≥60 + 无校验问题 | 可显示探索性分数差值，但不得解释为录用或淘汰结论。 |

### 等级显示规则

- `draft` 或 `confidence=low`：不显示「优秀/良好/一般/较弱」，改为「探索性材料支持度：分数」，分数视觉弱化。
- 仅 `confirmed` 且 confidence medium/high 时显示等级。
- 雷达图保留；draft 或 low 时继续标明探索性。

## 追问（validation_questions）

结构化对象数组，每项：

```json
{
  "question": "完整、可直接向候选人提出的问题",
  "purpose": "该问题准备验证什么证据缺口",
  "expected_evidence": ["情境", "个人行动", "结果或影响", "反思或调整"],
  "source_question_id": ""
}
```

- `question` 不能为空，不能只是 `Q1/Q2` 编号；
- `purpose` 不能为空；`expected_evidence` 至少 2 项；`source_question_id` 可为空；
- 若引用已有 Q1/Q2，必须从 interview 解析并展示原始问题全文，不得只显示编号。

### 兜底规则

模型漏填或返回非法问题时，代码根据该维 `behavioral_anchors`、`benchmark_gap`、缺失证据与维度名生成确定性兜底问题：

> 请描述一次能够体现"{待验证行为锚点}"的具体工作、实习或项目经历。请说明当时情境、你本人采取的行动、结果以及事后反思。

四维默认兜底方向：

- 动机：主动承担、高挑战投入、持续推进；
- 特质：变化、压力、协作、任务拆解；
- 自我认知：职责边界、反馈、具体改进；
- 价值观：速度与质量冲突、风险呈报、短期与长期取舍。

兜底问题标记 `generated_by_rule: true`；模型正常生成的问题标记 `false`。每个维度至少 1 个完整追问，low 维度必须有追问。

## 总体评估阶段

由四个维度的 `evidence_stage` 决定，不只看 `interview_qa` 是否为空：

| 四维状态 | 总体阶段 |
|---|---|
| 均无 interview_supported | `简历前置识别（结构化问答待补充）` |
| 部分 interview_supported | `简历与部分结构化面试补证`（并列出已补证 / 待补证维度） |
| 全部 interview_supported | `简历与结构化面试补证` |

## 优先追问

「下一轮优先追问」最多显示 4 个，每项展示：维度、完整问题、验证目的、期望证据、是否规则兜底。排序：

1. confidence=low 优先；
2. coverage 最低；
3. 与画像锚点证据缺口最大；
4. 存在反向证据待澄清。

## 输出安全兜底

只检查模型生成或派生的判断字段（`llm_report`、`key_strengths`、`risk_flags`、`benchmark_gap`、`next_step_action`、`recommendation`），不检查固定免责声明。

若出现「建议录用 / 建议淘汰 / 应当录用 / 应当淘汰 / 不予录用 / 自动录用 / 自动淘汰」等自动决策表述，则不生成正式报告并返回明确错误；不自动改写成其他结论。

固定声明「本报告不构成自动录用或淘汰决定」必须允许出现。

## 模型提供方配置

- 不硬编码密钥，不读取或输出密钥值；密钥不得写入 HTML、日志、测试或审计信息。
- 通过环境变量或 CLI 传入：`OPENAI_MODEL`、`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`DASHSCOPE_API_KEY`、`LLM_STRUCTURED_OUTPUT_MODE`。
- 默认代码仍可使用 OpenAI；仅当 `OPENAI_BASE_URL` 明确指向 DashScope 时才使用 `DASHSCOPE_API_KEY`。不因存在 `DASHSCOPE_API_KEY` 就静默切换提供方。
- `LLM_STRUCTURED_OUTPUT_MODE` 支持 `json_schema` 与 `json_object`；不假设 DashScope 一定支持 strict JSON Schema；即使仅保证 JSON 对象，也必须执行本地结构与语义校验。
- OpenAI SDK 延迟导入到真实调用路径，`--dry-run` 与离线测试不依赖真实 API。
