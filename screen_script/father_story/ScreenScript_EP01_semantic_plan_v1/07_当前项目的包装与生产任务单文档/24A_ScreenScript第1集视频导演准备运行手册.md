# ScreenScript第1集视频导演准备运行手册

> 项目标题：你是爸爸吗

## 目标
把 planning bundle 推进到视频生成前的导演准备状态：

```text
language plan -> start keyframes -> image input map
```

本手册不生成视频，不调用 `run_seedance_test.py`，只准备下一阶段视频生成所需的 `duration_overrides.json` 和 `image_input_map.json`。

## 一键命令
```bash
python3 scripts/run_novel_video_director.py \
  --bundle screen_script/father_story/ScreenScript_EP01_semantic_plan_v1 \
  --episode EP01 \
  --experiment-prefix screenscript_ep01_director \
  --provider openai \
  --allow-data-uri-from-local \
  --shots SH01,SH02,SH03,SH04,SH05,SH06,SH07,SH08,SH09,SH10,SH11,SH12,SH13,SH14,SH15,SH16,SH17,SH18
```

## 安全预检命令
```bash
python3 scripts/run_novel_video_director.py \
  --bundle screen_script/father_story/ScreenScript_EP01_semantic_plan_v1 \
  --episode EP01 \
  --experiment-prefix screenscript_ep01_director_check \
  --provider openai \
  --allow-data-uri-from-local \
  --prepare-only \
  --shots SH01,SH02,SH03,SH04,SH05,SH06,SH07,SH08,SH09,SH10,SH11,SH12,SH13,SH14,SH15,SH16,SH17,SH18
```

## 默认策略
- keyframe phase 固定为 `start`。
- 默认不生成 end frame。
- `image_input_map.json` 允许只有 `image` 字段，不强制 `last_image`。
- 角色参考图来自 `screen_script/father_story/character_image_map.json`。

## 主要输出
```text
test/screenscript_ep01_director_language/language/duration_overrides.json
test/screenscript_ep01_director_language/language/language_plan.json
test/screenscript_ep01_director_keyframes/keyframe_manifest.json
test/screenscript_ep01_director_keyframes/image_input_map.json
test/screenscript_ep01_director_director_manifest.json
```
