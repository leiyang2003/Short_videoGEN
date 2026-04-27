# Project Instructions

Before working on this novel-to-video pipeline, read:

- `corner_case_handling.md`

Use it as the project memory for known corner cases, failed fixes, effective fixes, and future-safe handling rules. When a new corner case is discovered, append it to `corner_case_handling.md` with a timestamp.

## Core Rule

Record content is the source of truth. Keyframe metadata may supplement record intent, but must not silently override the record.

## Scripts To Treat Carefully

When modifying or running these scripts, check whether the task touches any documented corner case:

- `scripts/novel2video_plan.py`
- `scripts/run_novel_video_director.py`
- `scripts/generate_keyframes_atlas_i2i.py`
- `scripts/run_seedance_test.py`
- `scripts/assemble_episode.py`

## Known Policies

- Scene-only shots must not inherit main character anchors.
- Temporary characters such as waiter, police, and crowd should use ephemeral anchors, not main character lock profiles.
- Static props must have explicit count, position, first-frame visibility, and motion policy.
- Avoid ambiguous phrases like "scattered cups" or "散落酒杯" when the count must be fixed.
- If a model profile has no true negative prompt field, prefer positive prompt rewriting and first-frame composition over only adding negative terms.
- For scene-only OpenAI keyframes, use a scene/style reference image, not a character identity reference.
- Modern Ginza/Tokyo shots must not inherit ancient-setting negative prompts such as "no modern elements".
- When assembling mixed-generation clips, normalize dimensions and preserve audio unless explicitly asked to mute.

## Verification Expectations

- After planning changes, inspect the generated record JSON for affected shots.
- After keyframe changes, inspect the keyframe prompt and manifest provider/output path.
- After Seedance changes, inspect `prompt.final.txt`, `payload.preview.json`, and the generated clip metadata.
- After assembly, verify final video duration, dimensions, and audio stream with `ffprobe`.

