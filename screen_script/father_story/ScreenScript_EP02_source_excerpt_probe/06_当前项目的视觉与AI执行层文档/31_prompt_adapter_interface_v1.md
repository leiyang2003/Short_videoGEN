# ScreenScript_EP02 prompt adapter interface v1

## 目标
把 `records/*.json` 渲染成下游视频生成脚本可用的 prompt、duration、dialogue/subtitle 输入。

## 约定
- `record_header.shot_id` 是镜头唯一 ID。
- `prompt_render.positive_prefix` + `prompt_render.shot_positive_core` 组成正向提示词。
- `prompt_render.negative_prompt` 是通用负向约束。
- `dialogue_language` 供语言计划、TTS、字幕流程消费。
