# Unsolved Problems

This document records issues that were investigated but not fully solved. Keep these separate from `corner_case_handling.md` so future runs do not treat an incomplete workaround as a proven fix.

## 2026-05-01 17:35 JST - EP03 shot-level audio still creates BGM/tonal-bed and boundary pause problems

### Status

Unsolved.

### Context

- Episode: EP03.
- Latest production family inspected:
  - `test/screenscript_ep03_child_state_lock_seedance/EP03_final_child_state_lock_audio_smooth_with_cover.mp4`
  - `test/screenscript_ep03_no_bgm_sh04_sh07_seedance/`
  - `test/screenscript_ep03_no_bgm_sh04_sh07_mix/`
- Test range: SH04-SH07.
- Goal: regenerate selected shots without BGM, preserve dialogue/voice/ambient sound, then add one unified BGM layer after assembly.

### Observed Problem

- EP03 has a global audio continuity issue, not only SH22 -> SH23.
- Shot-level Seedance audio often contains head silence, tail silence, or low-energy pauses.
- When clips are assembled with `audio_policy keep`, adjacent shot silences stack across hard cuts and create a perceptible pause or "stutter".
- Even after adding explicit no-BGM prompt constraints, the regenerated "no BGM" SH04-SH07 test still sounded like it had BGM or a music-like tonal bed.

### Evidence

- Global boundary audit on the current EP03 final showed suspicious low-energy or silent regions around all 22 shot-to-shot boundaries.
- SH22 -> SH23 was a concrete example:
  - Old SH22 padded tail had about 0.80s silence.
  - SH23 head had about 0.6-0.9s low-energy/silence.
  - Combined boundary produced a long perceived pause.
- No-BGM experiment:
  - Records were copied to `test/screenscript_ep03_no_bgm_experiment_records/`.
  - Execution-only overlay was added at `test/screenscript_ep03_no_bgm_experiment_records/no_bgm_execution_overlay.json`.
  - Overlay asked for Mandarin dialogue/voice/ambient/action sound only, with no background music, soundtrack, score, song, melody, piano, string, electronic bed, etc.
  - Seedance regenerated SH04-SH07 under `test/screenscript_ep03_no_bgm_sh04_sh07_seedance/`.
  - Outputs were assembled into:
    - `test/screenscript_ep03_no_bgm_sh04_sh07_mix/EP03_SH04_SH07_no_bgm_regen_concat.mp4`
    - `test/screenscript_ep03_no_bgm_sh04_sh07_mix/EP03_SH04_SH07_no_bgm_regen_unified_bgm.mp4`
    - `test/screenscript_ep03_no_bgm_sh04_sh07_mix/EP03_SH04_SH07_no_bgm_regen_unified_bgm_audible.mp4`
- User feedback:
  - The final unified-BGM test version was preferred.
  - However, the first regenerated no-BGM version still felt like it contained BGM.

### What Worked Partially

- Regenerating shots with a no-BGM prompt plus adding a unified scene-level BGM improved the subjective result.
- A stronger unified BGM test version sounded better than simply overlaying BGM on older mixed clips.
- Using unpadded/chained SH22 and trimming SH23 head silence reduced the SH22 -> SH23 boundary pause.

### What Did Not Fully Work

- Prompt-only no-BGM control did not reliably prevent Seedance from generating music-like tonal bed or emotional underscore.
- Adding BGM after the fact does not remove any model-generated music-like material already baked into each clip.
- Simple silence detection catches low-energy regions and boundary pauses, but it does not prove whether a clip contains BGM, ambient tone, room tone, or music-like soundtrack.

### Suspected Root Causes

- Seedance audio is generated per shot as a mixed final track, not as stems.
- The model may interpret "emotional scene", "cinematic", silence, or ambient constraints as permission to create sustained tonal bed.
- Generated audio has no separate dialogue, ambient, and music tracks, so post-processing cannot cleanly remove only BGM.
- Fixed shot durations encourage the model to fill unused time with pauses, ambience, or music-like sound.
- Assembly currently preserves source audio and hard-concats clips; it does not perform semantic audio cleanup or music/stem separation.

### Open Questions

- Can a stronger prompt reliably force "dialogue + natural production sound only" without tonal bed?
- Does the provider expose any audio mode that disables soundtrack/music while keeping speech?
- Is stem separation good enough for these generated clips to remove music-like material while preserving dialogue quality?
- Would `generate_audio=false` plus separate TTS/dialogue reconstruction be more reliable than Seedance mixed audio?
- Should the pipeline use scene-level or episode-level BGM only, with shot-level audio limited to dialogue/foley generated elsewhere?

### Candidate Future Experiments

- Test a stronger audio prompt that explicitly forbids sustained pitch, drones, chords, tonal pads, cinematic underscore, emotional bed, and musical ambience.
- Generate one short shot with `generate_audio=false`, then rebuild audio via TTS/dialogue plus room tone/foley, then add unified BGM.
- Run a source-separation tool on the no-BGM SH04-SH07 outputs to see if a music stem can be removed without damaging dialogue.
- Build a QA probe for "music-like tonal bed" using spectral continuity, pitch stability, and harmonic energy rather than silence alone.
- Compare three variants on the same shots:
  - Seedance audio with no-BGM prompt.
  - Seedance silent video plus external voice/TTS.
  - Seedance audio after stem separation.

### Current Recommendation

Do not treat the no-BGM prompt overlay as a solved policy. It is only a partial mitigation. The likely robust direction is to separate responsibilities:

- Shot layer: visual motion plus dialogue/foley/room tone, preferably as controllable audio or separate post-produced audio.
- Scene/episode layer: unified BGM and ducking after assembly.

