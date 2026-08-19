---
name: iceberg-evaluator
description: 基于冰山模型评估单个管培生或候选人的软性素质。用于在硬性条件初筛后，输入简历与可选结构化面试问答，输出一份包含冰山上前置匹配、动机/特质/自我认知/价值观四维、成功内化管培生画像相似度、优势、风险、追问和处理建议的完整HTML综合评估报告。仅处理单候选人；适用于招聘前置识别与单候选人深度评估参考，不用于自动录用、自动淘汰或敏感属性推断。
---

# 冰山模型软性素质评估

## 定位

只处理**一名候选人**、只输出**一份可直接打开或下载的完整 HTML 综合评估报告**。不做多候选人比较、自动排名或批量评估。

- 冰山上（教育、经历、项目、成果等外显事实）用于寻访与简历前置识别。
- 冰山下（动机、特质、自我认知、价值观四维）用于面试补证与单候选人深度评估。
- 处理建议只用于安排补证与人工复核，不是录用或淘汰结论；不使用或推断年龄、性别、民族、籍贯、婚育、健康、宗教、家庭背景等非工作信息。

## 输入

| 文件 | 内容 | 要点 |
|---|---|---|
| 简历 `.txt` | 脱敏的教育、经历、项目、职责、行动和成果。 | 支撑冰山上；可形成冰山下初步假设。 |
| 面试 `.json` | `candidate_name`、`position`、可选结构化问答。 | `interview_qa` 可为 `[]`；**candidate_name 优先使用匿名代号**。 |
| 画像 `.json` | 成功内化管培生基准。 | 使用 `templates/benchmark_profile.example.json`；须写明成功定义、成功样本基础、适用范围、冰山上指标和四维锚点。 |

面试文件最小格式：

```json
{
  "candidate_name": "候选人匿名代号",
  "position": "应聘岗位",
  "interview_qa": [
    {"question_id": "Q1", "question": "请描述一次……", "answer": "候选人回答"}
  ]
}
```

## 强制执行顺序

1. 读取 `references/evidence_rules.md`；
2. 校验输入（interview / benchmark 全字段契约，敏感字段拦截）；
3. `--dry-run` 输入校验（不调用模型）；
4. 正式评估；
5. 验证证据状态与 HTML（证据原文可追溯、逐维证据阶段、置信度、探索性标识、完整追问、越界结论兜底）。

## 关键约束

- **分数与置信度互不决定**：`score` 表示材料对画像锚点的**探索性支持度**；`confidence` 表示**证据充分性**。两者由不同规则独立确定，基准差值不用于计算置信度。
- **低置信度不形成确定性基准判断**：`low` 置信度时不显示「优秀/良好/一般/较弱」，也不显示「高于/低于/符合基准」，只显示「当前证据不足，暂不判断是否达到画像基准」。
- **证据校验失败不得输出强结论**：未能通过来源/原文校验的证据会被移除并记入报告；处理建议限制为「建议补证」或「人工重点复核」。
- **探索性标识**：`draft` 画像、仅简历阶段、或存在证据校验问题时，综合分与画像相似度标注为「探索性」，不能作为录用或淘汰依据。
- **逐维降级**：每个维度独立判定「简历初步假设 / 面试已补证」，单个维度的问答证据不得解除其他维度的低置信度。
- **总体阶段由四维实际证据阶段决定**，不只看 `interview_qa` 是否为空。
- **追问必须是 HR 可直接使用的完整问题**，不得只给 `Q1/Q2` 编号；模型漏填时由规则兜底生成完整追问。
- **决策边界**：录用、淘汰、薪酬、职级或培养资源决策必须由招聘与业务负责人作出。

## 运行

```bash
python scripts/iceberg_evaluator.py \
  --resume candidate_resume.txt \
  --interview candidate_interview.json \
  --benchmark confirmed_benchmark.json \
  --html candidate_evaluation.html
```

仅校验输入、不调用模型：

```bash
python scripts/iceberg_evaluator.py \
  --resume candidate_resume.txt \
  --interview candidate_interview.json \
  --html validation.html \
  --dry-run
```

## 文件说明

- `scripts/iceberg_evaluator.py`：单候选人、仅输出一份完整 HTML 报告的评估脚本。
- `templates/`：画像 / 简历 / 面试样例。
- `references/evidence_rules.md`：证据、置信度、基准比较、追问与总体阶段等详细规则。
- `requirements.txt`：运行依赖（仅真实调用路径使用 openai SDK）。
- `tests/`：离线自动化测试（unittest，不访问网络）。
