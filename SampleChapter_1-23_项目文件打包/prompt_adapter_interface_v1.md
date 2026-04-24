# SampleChapter Prompt Adapter Interface v1 (Spec)

## 1. 目标
建立“语义层 -> 模型层”的通用转换接口，使同一份镜头记录可以渲染到：
- 不支持负向字段的模型（如 Seedance）
- 支持负向字段的模型（泛化能力）

本文件仅为规范草稿，不改动现有脚本。

## 2. 输入输出定义

### 输入
1. `record`（镜头语义记录，来源 `*_record.json`）
2. `profile`（模型能力配置，来源 `model_capability_profiles_v1.json`）
3. `render_options`（实验参数，如 variant、language_mode、strictness）

### 输出
1. `prompt.final.txt`
2. `negative_prompt.txt`（可为空文件）
3. `payload.preview.json`
4. `render_report.json`

## 3. 语义层约定（模型无关）
统一拆解为五类语义：
1. `must`: 必须出现（角色锚点、场景锚点、关键动作）
2. `prefer`: 偏好呈现（风格、节奏、摄影倾向）
3. `avoid`: 应避免（串脸、时代错位、画面缺陷）
4. `dialogue`: 台词/旁白/字幕绑定
5. `continuity`: 跨镜头连续性约束

## 4. 适配器接口（伪代码）
```text
interface PromptAdapter {
  can_handle(profile): bool
  render(record, profile, render_options) -> RenderBundle
}

RenderBundle {
  prompt_text: string
  negative_prompt_text: string  # may be empty
  payload_preview: object
  render_report: object
}
```

## 5. 两类核心实现策略

### 5.1 NonNegativeAdapter（如 Seedance）
适用条件：`supports_negative_prompt = false`

策略：
1. `must + prefer + dialogue + continuity` 直接写入正向 prompt
2. `avoid` 转为正向限制句
3. 在 `render_report` 标记弱化风险

转换示例：
- 原始 avoid: `modern clothes`
- 转换后约束: `all characters remain in ancient Han-era coarse linen clothing, no modern design elements`

### 5.2 NegativeAdapter（支持负向字段模型）
适用条件：`supports_negative_prompt = true`

策略：
1. `must + prefer + dialogue + continuity` -> 正向 prompt
2. `avoid` -> `negative_prompt`
3. `render_report` 标记为“完整映射”

## 6. Render Report 最小字段
```json
{
  "record_id": "EP01_SH02",
  "model_profile_id": "seedance2_text2video_atlas",
  "mapping_summary": {
    "must": "full",
    "prefer": "full",
    "avoid": "downgraded_to_positive_constraints",
    "dialogue": "full",
    "continuity": "full"
  },
  "downgrades": [
    {
      "type": "no_negative_field",
      "detail": "avoid list merged into positive constraints"
    }
  ],
  "requires_manual_review": true
}
```

## 7. 与当前工程的对接点（仅规划）
1. 读取 `records/EP01_SHxx_record.json`
2. 读取模型 profile（如 `seedance2_text2video_atlas`）
3. 生成四类产物到 `test/<exp>/<shot>/`
4. 继续沿用现有执行脚本触发 API（本阶段不改）

## 8. 建议的阶段推进
1. Phase A: 只实现渲染，不调用 API
2. Phase B: 对接现有 `run_seedance_test.py` 的 `--prepare-only`
3. Phase C: 增加渲染后自动 QA 打分与回写

