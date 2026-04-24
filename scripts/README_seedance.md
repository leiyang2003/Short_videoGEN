# Seedance Test Script Usage

## 1) Install deps

```bash
pip3 install -r requirements.txt
```

## 2) Configure API key

Copy `.env.example` to `.env`, then fill:

```bash
ATLASCLOUD_API_KEY=...
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

## 4) Actual generation (calls Atlas Cloud API)

```bash
python3 scripts/run_seedance_test.py --shots SH02,SH10
```

Notes:
- API mode now uses rendered `payload.preview.json` as single source of truth.
- API mode currently supports one profile at a time (Atlas profile). Do not combine with multi `--profile-ids`.
- Character locking is loaded from `--character-lock-profiles`; each role in records can reference `lock_profile_id` to avoid repeated appearance/costume blocks.

## 5) Output structure

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
