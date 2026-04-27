# Seedance Test Script Usage

## 1) Install deps

```bash
pip3 install -r requirements.txt
```

## 2) Configure API key

Copy `.env.example` to `.env`, then fill:

```bash
ATLASCLOUD_API_KEY=...
NOVITA_API_KEY=...
OPENAI_API_KEY=...
XAI_API_KEY=...

# Image keyframe/character image provider selector:
# openai | atlas-openai | grok
IMAGE_MODEL=openai

# Image-to-video provider selector:
# atlas-seedance1.5 | novita-seedance1.5
VIDEO_MODEL=atlas-seedance1.5
```

## 3) Prepare files only (no API call)

```bash
python3 scripts/run_seedance_test.py --prepare-only
```

Run selected shots only:

```bash
python3 scripts/run_seedance_test.py --prepare-only --shots SH02,SH10
```

Use custom record/profile source:

```bash
python3 scripts/run_seedance_test.py \
  --prepare-only \
  --shots SH02,SH10 \
  --records-dir SampleChapter_项目文件整理版/06_当前项目的视觉与AI执行层文档/records \
  --model-profiles SampleChapter_项目文件整理版/06_当前项目的视觉与AI执行层文档/30_model_capability_profiles_v1.json \
  --character-lock-profiles SampleChapter_项目文件整理版/06_当前项目的视觉与AI执行层文档/35_character_lock_profiles_v1.json \
  --model-profile-id seedance2_text2video_atlas
```

Batch profile A/B (prepare-only):

```bash
python3 scripts/run_seedance_test.py \
  --prepare-only \
  --shots SH02,SH10 \
  --profile-ids seedance2_text2video_atlas,generic_t2v_with_negative_example
```

## 4) Actual generation (calls provider API)

```bash
python3 scripts/run_seedance_test.py --shots SH02,SH10
```

Use Novita Seedance 1.5 I2V:

```bash
python3 scripts/run_seedance_test.py \
  --shots SH02,SH10 \
  --video-model novita-seedance1.5
```

Notes:
- API mode now uses rendered `payload.preview.json` as single source of truth.
- API mode currently supports one profile at a time. Do not combine with multi `--profile-ids`.
- Provider is selected from `--video-model` / `VIDEO_MODEL`, or from `--model-profile-id` / `--profile-ids` via the profile catalog.
- `--video-model atlas-seedance1.5` maps to `seedance15_i2v_atlas`.
- `--video-model novita-seedance1.5` maps to `seedance15_i2v_novita` and calls `https://api.novita.ai/v3/async/seedance-v1.5-pro-i2v`.
- Novita payload defaults include `fps=24`, `seed=42`, `ratio=9:16`, `resolution=480p`, `watermark=false`, `camera_fixed=false`, `service_tier=default`, `generate_audio=true`, and `execution_expires_after=172800`.
- Character locking is loaded from `--character-lock-profiles`; each role in records can reference `lock_profile_id` to avoid repeated appearance/costume blocks.
- Model audio is ON by default. Use `--no-audio` when you want silent clips.
- Subtitle hint is OFF by default. Use `--enable-subtitle-hint` only when you want to inject `subtitle_overlay_hint` into prompts.
- Video generation is one-by-one by default (single shot request each time) with built-in retries.
- You can tune runtime pacing with `--max-retries`, `--retry-wait-sec`, `--inter-shot-wait`.

Use duration overrides generated from language plan:

```bash
python3 scripts/run_seedance_test.py \
  --shots SH01,SH02,SH03 \
  --model-profile-id seedance15_i2v_atlas \
  --duration-overrides test/<language_experiment>/language/duration_overrides.json \
  --image-input-map test/<keyframe_experiment>/image_input_map.json
```

## 5) Language plan (solve subtitle/speech mismatch + early cut risk)

Build unified subtitle and duration plan:

```bash
python3 scripts/build_episode_language_plan.py \
  --shots SH01,SH02,SH03,SH04,SH05,SH06,SH07,SH08,SH09,SH10,SH11,SH12,SH13 \
  --subtitle-source dialogue
```

Outputs:
- `test/<language_experiment>/language/episode.srt`
- `test/<language_experiment>/language/shot_srt/SHxx.srt`
- `test/<language_experiment>/language/duration_overrides.json`
- `test/<language_experiment>/language/language_plan.json`

## 6) IMAGE_MODEL i2i keyframes (for identity-consistent start/end frames)

Keyframe and character-image scripts can use the global `IMAGE_MODEL` env var:

```bash
IMAGE_MODEL=openai        # direct OpenAI image API
IMAGE_MODEL=atlas-openai  # Atlas-hosted OpenAI image model
IMAGE_MODEL=grok          # xAI grok-imagine-image
```

You can override it per run with `--image-model openai|atlas-openai|grok`.

For character references, `scripts/character_image_gen.py --image-model grok --overwrite`
uses the existing character image as the Grok edit source when the target image already exists.
If no target image exists yet, it bootstraps from text-to-image.

Prepare per-shot start/end keyframe requests (no API call):

```bash
python3 scripts/generate_keyframes_atlas_i2i.py \
  --prepare-only \
  --shots SH02,SH12 \
  --character-image-map /tmp/character_image_map_ep01.json
```

Actual keyframe generation (calls Atlas generateImage):

```bash
python3 scripts/generate_keyframes_atlas_i2i.py \
  --image-model atlas-openai \
  --shots SH01,SH02,SH03,SH04,SH05,SH06,SH07,SH08,SH09,SH10,SH11,SH12,SH13 \
  --character-image-map /tmp/character_image_map_ep01.json
```

Use OpenAI image edits directly:

```bash
python3 scripts/generate_keyframes_atlas_i2i.py \
  --image-model openai \
  --openai-model gpt-image-2 \
  --shots SH01,SH02,SH03,SH04,SH05,SH06,SH07,SH08,SH09,SH10,SH11,SH12,SH13 \
  --character-image-map /tmp/character_image_map_ep01.json
```

Use Grok image edits directly:

```bash
python3 scripts/generate_keyframes_atlas_i2i.py \
  --image-model grok \
  --xai-model grok-imagine-image \
  --shots SH01,SH02,SH03,SH04,SH05,SH06,SH07,SH08,SH09,SH10,SH11,SH12,SH13 \
  --character-image-map /tmp/character_image_map_ep01.json
```

Use Atlas first and auto-fallback to OpenAI on retryable 429/5xx/network errors:

```bash
python3 scripts/generate_keyframes_atlas_i2i.py \
  --provider auto \
  --atlas-retries-before-fallback 2 \
  --openai-model gpt-image-2 \
  --shots SH01,SH02,SH03,SH04,SH05,SH06,SH07,SH08,SH09,SH10,SH11,SH12,SH13 \
  --character-image-map /tmp/character_image_map_ep01.json
```

Notes:
- Default behavior generates independent start/end frames for every shot.
- If you want chain reuse (N end -> N+1 start), add `--reuse-next-start-from-prev-end`.
- Keyframe image generation is one-by-one by default (single frame request each time) with built-in retries.
- You can tune runtime pacing with `--max-retries`, `--retry-wait-sec`, `--request-interval`.
- `--openai-api-key` can override env key; otherwise `OPENAI_API_KEY` is used.
- `--xai-api-key` can override env key; otherwise `XAI_API_KEY` is used.

Build `image_input_map` from generated keyframes:

```bash
python3 scripts/build_image_input_map.py \
  --manifest test/<keyframe_experiment>/keyframe_manifest.json \
  --out test/<keyframe_experiment>/image_input_map.json
```

Then run Seedance 1.5 image-to-video with map input:

```bash
python3 scripts/run_seedance_test.py \
  --shots SH01,SH02,SH03,SH04,SH05,SH06,SH07,SH08,SH09,SH10,SH11,SH12,SH13 \
  --model-profile-id seedance15_i2v_atlas \
  --image-input-map test/<keyframe_experiment>/image_input_map.json
```

Prompt renderer notes for I2V:
- When `--image-input-map` points to a keyframe experiment folder, the script now auto-loads `<shot_id>/start/prompt.txt` from the same folder and inherits scene anchors into the video prompt.
- You can also set `--keyframe-prompts-root test/<keyframe_experiment>` explicitly if the prompt files live elsewhere.
- Dialogue shots now render with a structured prompt template (`场景 / 角色锁定 / 台词与嘴型必须严格对应 / 禁止`) instead of the old one-line `本镜头绑定台词`.
- Record audio mapping is source-of-truth: if a record has only `dialogue_lines`, the final prompt must include dialogue; if it has only `narration_lines`, the final prompt must include narration; if it has both, dialogue wins and narration is suppressed.
- Planning records should prefer role dialogue over narration. Onscreen dialogue speakers must be present in the keyframe; phone/offscreen dialogue must set `source=phone/offscreen` and `listener`, with the listener visible in the keyframe.
- Narration-only shots render narration as `画外旁白音轨播放` and bind visible characters to closed-mouth/no-lip-sync behavior in the same timeline line, so model audio is less likely to turn narration into character dialogue.
- If a record camera movement is explicitly `固定机位` / fixed camera and the provider supports a `camera_fixed` payload field, the payload now sends `camera_fixed=true` unless `global_settings.camera_fixed` is explicitly set.
- When a mobile phone appears in the rendered prompt, the final prompt must specify who controls the phone, who the screen faces, and that the display content matches the story.
- See [Sample_I2V_Prompt.md](/Users/leiyang/Desktop/Coding/Short_videoGEN/Sample_I2V_Prompt.md) for the canonical format.

Or use the same `image_input_map` with Novita:

```bash
python3 scripts/run_seedance_test.py \
  --shots SH01,SH02,SH03,SH04,SH05,SH06,SH07,SH08,SH09,SH10,SH11,SH12,SH13 \
  --model-profile-id seedance15_i2v_novita \
  --image-input-map test/<keyframe_experiment>/image_input_map.json
```

Transition note:
- When adjacent shots share the same boundary frame (previous `last_image` == next `image`), prefer hard cut and avoid visual transition effects.

## 7) Episode assemble + transition policy

Assemble with boundary-aware transitions:

```bash
python3 scripts/assemble_episode.py \
  --concat-file test/concat_EP01_SH01_SH13.txt \
  --image-input-map test/<keyframe_experiment>/image_input_map.json \
  --episode EP01 \
  --cover-page-dir novel/ginza_night/assets/cover_page \
  --cover-duration-sec 1 \
  --audio-policy keep \
  --out episode_01_v2.mp4
```

Rules:
- Shared boundary frame: hard cut (no visual transition).
- Non-shared boundary frame: lightweight fade in/out.
- When `--cover-page-dir` is set, the script prepends the numbered cover matching `--episode` (for example EP01 -> `*_cover_01.png`) for 1 second with silent audio.
- `--audio-policy keep` preserves generated clip audio after the silent cover page. Use `mute` only when you intentionally want a silent episode.

## 8) QA report for 4 issues

```bash
python3 scripts/qa_episode_sync.py \
  --language-plan test/<language_experiment>/language/language_plan.json \
  --concat-file test/concat_EP01_SH01_SH13.txt \
  --image-input-map test/<keyframe_experiment>/image_input_map.json \
  --assembly-report ./assembly_report.json \
  --out test/<language_experiment>/language/qa_sync_report.json
```

## 9) Output structure

```text
test/<experiment_name>/
  run_manifest.json
  SH02/
    prompt.final.txt
    prompt.txt
    negative_prompt.txt
    duration_used.txt
    payload.preview.json
    render_report.json
    record.snapshot.json
    request_payload.preview.json (prepare-only mode)
    generate_request_response.json (API mode)
    final_status.json (API mode)
    output_url.txt (API mode)
    output.mp4 (API mode)

# multi-profile prepare-only layout
test/<experiment_name>/
  run_manifest.json
  <profile_id>/
    profile_manifest.json
    SH02/
      prompt.final.txt
      payload.preview.json
      render_report.json
```
