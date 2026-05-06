# Project Instructions

Before working on this novel-to-video pipeline, read:

- `corner_case_handling.md`

Use it as the project memory for known corner cases, failed fixes, effective fixes, and future-safe handling rules. When a new corner case is discovered, append it to `corner_case_handling.md` with a timestamp.

## Core Rule

Record content is the source of truth. Keyframe metadata may supplement record intent, but must not silently override the record.

## Codex Working Protocol

Use an evidence-first workflow for this pipeline.

For judgment-heavy or high-impact changes, especially planning, prompt design, visual assets, keyframes, Seedance generation, and assembly behavior:

- First reproduce or probe the issue with the smallest useful experiment.
- Before editing code, report the observed evidence, the suspected root cause, the affected layer, the expected fix, and how the result will be verified.
- Do not directly change code based only on intuition when the issue can be tested with a small probe, record inspection, prompt audit, frame extraction, or targeted rerun.
- After the user agrees on the direction, make the smallest scoped implementation change.
- After editing, verify with tests or targeted reruns and report the concrete output paths or inspected artifacts.

For planning and prompt issues, explicitly distinguish whether the problem comes from:

- source script parsing
- shot selection or merging
- record fields
- prompt rendering
- model execution
- assembly or QA

For semantic planning questions, such as visible character count, listener/addressee, action target, narration vs music cue, or prop vs scene overlay, prefer a small OpenAI/Grok probe before changing rules. The probe should use enough scene context and a character alias table; one isolated line is often insufficient.

Prefer LLM semantic recovery over accumulating mechanical restrictions. When a failure comes from compressed or ambiguous story meaning, first ask a capable model to recover the intended relationship from enough context, such as who is on which side of a door, who hears whom, whether a voice is local/offscreen/phone/voiceover, what object an action targets, and what the visible camera-side moment should be. Use the result to write a concise positive intent contract in the record or prompt. Avoid piling on long negative lists or rigid one-off rules unless a small probe shows the issue is truly a deterministic renderer or assembly bug.

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
- When a character looks at a held photo, the photo front side defaults toward the holder; only intentional show-to-another-character shots turn the front side toward that recipient.
- Avoid ambiguous phrases like "scattered cups" or "散落酒杯" when the count must be fixed.
- If a model profile has no true negative prompt field, prefer positive prompt rewriting and first-frame composition over only adding negative terms.
- For scene-only OpenAI keyframes, use a scene/style reference image, not a character identity reference.
- First-frame visible characters must show their face; do not design keyframes where characters face away from the audience.
- Modern Ginza/Tokyo shots must not inherit ancient-setting negative prompts such as "no modern elements".
- When assembling mixed-generation clips, normalize dimensions and preserve audio unless explicitly asked to mute.
- For offscreen-local, phone, remote-speaker, or voiceover dialogue with visible silent listeners, do not rely on model audio plus stronger "closed mouth" wording. Generate the listener video with `generate_audio=false`, then mux/compose the offscreen/remote dialogue audio afterward so the model cannot bind the voice to the visible listener's mouth.

## Verification Expectations

- After planning changes, inspect the generated record JSON for affected shots.
- After keyframe changes, inspect the keyframe prompt and manifest provider/output path.
- After Seedance changes, inspect `prompt.final.txt`, `payload.preview.json`, and the generated clip metadata.
- After assembly, verify final video duration, dimensions, and audio stream with `ffprobe`.
- When Codex directly generates keyframes or clips by running scripts outside the WebUI job system, also refresh the WebUI project shot asset index afterward. Trigger `sync_project_index(project_id)` or call the Shot Board API, then inspect `webui/.state/projects/<project_id>-<project_slug>/shot_asset_index.json` and the Shot Board pairing for the affected episode/shots.
