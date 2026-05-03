# ScreenScript第5集视频导演准备运行手册

> 项目标题：星辉幼儿园

## 目标
把 planning bundle 推进到视频生成前的导演准备状态：

```text
language plan -> start keyframes -> image input map
```

本手册不生成视频，不调用 `run_seedance_test.py`，只准备下一阶段视频生成所需的 `duration_overrides.json` 和 `image_input_map.json`。

## 一键命令
```bash
python3 scripts/run_novel_video_director.py \
  --bundle screen_script/father_story/ScreenScript_EP05_llm_rules_fullrun_20260502_v5 \
  --episode EP05 \
  --experiment-prefix screenscript_ep05_director \
  --provider openai \
  --allow-data-uri-from-local \
  --enable-high-confidence-shot-chaining \
  --shots SH01,SH02,SH03,SH04,SH05,SH06,SH07,SH08,SH09,SH10,SH11,SH12,SH13,SH14,SH15,SH16,SH17,SH18,SH19,SH20,SH21,SH22,SH23,SH24,SH25,SH26,SH27,SH28,SH29,SH30,SH31,SH32,SH33,SH34,SH35,SH36,SH37,SH38,SH39,SH40,SH41,SH42,SH43,SH44,SH45,SH46,SH47,SH48
```

## 安全预检命令
```bash
python3 scripts/run_novel_video_director.py \
  --bundle screen_script/father_story/ScreenScript_EP05_llm_rules_fullrun_20260502_v5 \
  --episode EP05 \
  --experiment-prefix screenscript_ep05_director_check \
  --provider openai \
  --allow-data-uri-from-local \
  --prepare-only \
  --enable-high-confidence-shot-chaining \
  --shots SH01,SH02,SH03,SH04,SH05,SH06,SH07,SH08,SH09,SH10,SH11,SH12,SH13,SH14,SH15,SH16,SH17,SH18,SH19,SH20,SH21,SH22,SH23,SH24,SH25,SH26,SH27,SH28,SH29,SH30,SH31,SH32,SH33,SH34,SH35,SH36,SH37,SH38,SH39,SH40,SH41,SH42,SH43,SH44,SH45,SH46,SH47,SH48
```

## 默认策略
- keyframe phase 固定为 `start`。
- 默认不生成 end frame。
- `image_input_map.json` 允许只有 `image` 字段，不强制 `last_image`。
- `shot_chain_plan.json` 只标记 high-confidence 相邻镜头；实际链式 I2V 由 `scripts/run_chained_seedance.py` 执行。
- 角色参考图来自 `screen_script/father_story/character_image_map.json`。

## 主要输出
```text
test/screenscript_ep05_director_language/language/duration_overrides.json
test/screenscript_ep05_director_language/language/language_plan.json
test/screenscript_ep05_director_keyframes/keyframe_manifest.json
test/screenscript_ep05_director_keyframes/image_input_map.json
test/screenscript_ep05_director_shot_chain_plan.json
test/screenscript_ep05_director_director_manifest.json
```
