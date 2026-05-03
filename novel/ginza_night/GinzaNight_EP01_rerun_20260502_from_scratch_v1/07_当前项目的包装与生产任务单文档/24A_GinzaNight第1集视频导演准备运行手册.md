# GinzaNight第1集视频导演准备运行手册

> 项目标题：银座的夜晚与隐藏的温柔（1-6章）

## 目标
把 planning bundle 推进到视频生成前的导演准备状态：

```text
language plan -> start keyframes -> image input map
```

本手册不生成视频，不调用 `run_seedance_test.py`，只准备下一阶段视频生成所需的 `duration_overrides.json` 和 `image_input_map.json`。

## 一键命令
```bash
python3 scripts/run_novel_video_director.py \
  --bundle novel/ginza_night/GinzaNight_EP01_rerun_20260502_from_scratch_v1 \
  --episode EP01 \
  --experiment-prefix ginzanight_ep01_director \
  --provider openai \
  --allow-data-uri-from-local \
  --enable-high-confidence-shot-chaining \
  --shots SH01
```

## 安全预检命令
```bash
python3 scripts/run_novel_video_director.py \
  --bundle novel/ginza_night/GinzaNight_EP01_rerun_20260502_from_scratch_v1 \
  --episode EP01 \
  --experiment-prefix ginzanight_ep01_director_check \
  --provider openai \
  --allow-data-uri-from-local \
  --prepare-only \
  --enable-high-confidence-shot-chaining \
  --shots SH01
```

## 默认策略
- keyframe phase 固定为 `start`。
- 默认不生成 end frame。
- `image_input_map.json` 允许只有 `image` 字段，不强制 `last_image`。
- `shot_chain_plan.json` 只标记 high-confidence 相邻镜头；实际链式 I2V 由 `scripts/run_chained_seedance.py` 执行。
- 角色参考图来自 `novel/ginza_night/character_image_map.json`。

## 主要输出
```text
test/ginzanight_ep01_director_language/language/duration_overrides.json
test/ginzanight_ep01_director_language/language/language_plan.json
test/ginzanight_ep01_director_keyframes/keyframe_manifest.json
test/ginzanight_ep01_director_keyframes/image_input_map.json
test/ginzanight_ep01_director_shot_chain_plan.json
test/ginzanight_ep01_director_director_manifest.json
```
