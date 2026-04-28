# I2V Prompt Design Rules

> Created: 2026-04-27

This document records the current design rules for generating I2V prompts in the novel-to-video pipeline. It is intended to guide planning records, keyframe prompts, and `prompt.final.txt` rendering.

## Core Principle

The record is the source of truth. `prompt.final.txt` should be a compiled artifact from structured record fields, not a second free-form source of truth.

LLM should be used to improve structured intent, shot blocking, dialogue ownership, prop contracts, and motion constraints. The renderer should then compile those fields into a stable final prompt.

## Pipeline Placement

I2V prompt control should start at the planning record level or earlier.

Many I2V failures cannot be fixed reliably at final prompt time:

- overloaded shots
- two speakers competing for lip sync
- complex action chains
- ambiguous static props
- unclear first-frame composition
- negative safety terms that trigger provider filters

Therefore, the planner should produce I2V-aware records, and the final prompt renderer should enforce those records.

## One Shot, One Task

Each shot should have one primary I2V task:

- dialogue
- reaction
- action
- prop display
- establishing scene
- transition

If one shot tries to solve multiple hard tasks, split the shot.

Examples:

- Speaking + walking + picking up a prop: split.
- Door opening + entering + dialogue: split.
- Two people exchanging lines: split into speaker and reaction shots.
- Prop close-up + emotional reaction: usually split unless one is clearly secondary.

## Dialogue Policy

### Default Rule

One shot should have only one active speaker.

Two people may appear in the first frame, but only one person may own the speech task.

### Required Dialogue Fields

For any shot with dialogue, the record should define:

- `active_speaker`
- `first_speaker`
- `speaker_visual_priority`
- `silent_visible_characters`
- `lip_sync_policy`

Suggested structure:

```json
{
  "dialogue_blocking": {
    "active_speaker": "A",
    "first_speaker": "A",
    "speaker_visual_priority": "center_face",
    "silent_visible_characters": ["B"],
    "lip_sync_policy": "single_active_speaker"
  }
}
```

### Two-Person First Frame

If two people are visible in the first frame, the prompt must either:

1. explicitly specify who speaks first, or
2. make the first speaker the visual center of the first frame.

The active speaker should be the centered visible face, not merely the foreground body.

Good:

```text
A's face is centered and sharp. B is visible as a silent listener in the foreground shoulder. A is the only speaker. B has no lip movement.
```

Risky:

```text
Two people talk to each other in an over-the-shoulder shot.
```

### Over-The-Shoulder Shots

For over-the-shoulder shots, specify both the viewpoint and the speaking face.

Template:

```text
Over-the-shoulder shot from B. A's face is centered and sharp; A is the active speaker. B is only a foreground shoulder/listening silhouette. B remains silent with no lip movement.
```

Avoid ambiguous phrases like "front person speaks" because the foreground shoulder may be misread as the speaker.

### Speaker Changes

If the active speaker changes inside the same shot, mark the shot as high risk and usually split it.

Preferred structure:

- A speaks, B silent/listening.
- B reaction, no lip movement.
- B speaks, A silent/listening.
- A reaction, no lip movement.

Only allow two onscreen speakers in one shot when intentionally accepting risk, and mark it for manual review.

### Phone Dialogue

Phone dialogue must distinguish remote audio from onscreen speech.

If the shot is listening to a remote phone voice:

- the onscreen listener must be visible
- the onscreen listener must hold or face the phone naturally
- the onscreen listener stays silent with no lip movement
- only the remote caller's voice is heard
- the remote caller must not be visualized in the same frame unless the shot is intentionally split-screen, which should be avoided for production

If the onscreen listener replies:

- the shot becomes the listener's speaking shot
- the onscreen listener is now the active speaker
- the remote caller is silent or heard only before/after the reply, not simultaneously
- no double speaking

Preferred phone-dialogue split:

- remote caller speaks; onscreen listener silently listens, no lip movement
- onscreen listener replies; onscreen listener is the only active speaker
- remote caller speaks again; onscreen listener returns to silent listening

Template for listening:

```text
Phone audio comes from the remote caller. A is visible holding the phone and listening silently. A has no lip movement. The remote caller is not visible. No split screen.
```

Template for replying:

```text
A holds the phone and is the only active speaker, replying into the call with natural lip movement. The remote caller is not visible and does not speak at the same time.
```

## First-Frame Contract

Every record should contain a clear first-frame contract. The first frame must be a single stable visual state.

It should define:

- location
- visible characters
- visual center
- character positions
- key props
- prop count and position
- initial action pose
- whether anyone is speaking
- whether camera motion is allowed

The first frame must not combine multiple locations, time jumps, or sequential actions.

Bad:

```text
He walks from the street into the hallway, opens the door, and confronts her.
```

Good:

```text
First frame: He stands in the apartment hallway, right hand near the door handle, body paused before entering.
```

## Scene Detail Library

Every episode bundle should include one `scene_detail.txt` file that defines all recurring scene locations.

The file uses block format:

```text
【Location Name】
Pure environment description...
```

Scene detail text must be pure location information:

- architecture
- fixed furniture
- materials
- light and shadow
- scent
- sound
- temperature
- spatial scale
- environmental texture

Scene detail text must not include:

- people
- character names
- pronouns referring to people
- dialogue
- character actions
- relationship beats
- emotion arcs
- shot-specific story events

Each shot record should reference the same base scene information:

```json
{
  "scene_anchor": {
    "scene_id": "EP06_LIVINGROOM_RELICS",
    "scene_name": "健一公寓客厅",
    "scene_detail_ref": "scene_detail.txt",
    "scene_detail_key": "健一公寓客厅",
    "scene_detail": "该客厅以现代日本都市悬疑为视觉基线..."
  }
}
```

The scene detail is the stable environment canon. Shot-specific character blocking, emotion, dialogue, and props should be layered on top of it, not mixed into it.

## Action Policy

Complex physical actions should be reduced or split.

If an action includes multiple physical steps, use separate shots or a start/result structure.

Examples:

- walking to door
- hand reaches toward handle
- door already half open
- person passes through door

Avoid showing the most fragile contact moment unless necessary.

For action shots, avoid dialogue unless the action is tiny and the speaker remains visually stable.

## Prop Policy

Important props must be explicit and stable.

### Prop Library Rule

Any important prop must be registered in a prop library the first time it appears.

On first appearance, define the prop's canonical profile:

- name
- count
- approximate size
- length / width / height when relevant
- color
- material
- shape / structure
- first-frame position
- first-frame visibility
- motion policy
- who controls it, if anyone

After the prop has been registered, any later shot using the same prop must reuse the same canonical prop description from the prop library. Do not let the LLM invent a new size, color, material, shape, or structure for the same story prop.

Suggested structure:

```json
{
  "prop_library": {
    "AYAKA_LIGHT_BLUE_SCARF": {
      "display_name": "彩花的浅蓝丝巾",
      "size": "约120cm x 18cm，薄长条布料",
      "color": "浅蓝色，低饱和",
      "material": "柔软丝质或仿丝布料，微弱反光",
      "structure": "长条形围巾，两端自然垂落，无图案或只有极浅纹理",
      "canonical_motion_policy": "除非角色明确拿起，否则全程静止，不自行滑动、漂移或变形"
    }
  }
}
```

Later shot records should reference the prop id and reuse the same profile:

```json
{
  "prop_contract": [
    {
      "prop_id": "AYAKA_LIGHT_BLUE_SCARF",
      "position": "田中健一膝前地板中间偏右",
      "first_frame_visible": true,
      "motion_policy": "全程静止，不被拿起或拖动"
    }
  ]
}
```

The renderer should expand `prop_id` into the full canonical description in `prompt.final.txt`.

For each important prop, define:

- count
- approximate size or dimensions
- color
- material
- structure
- position in this shot
- first-frame visibility in this shot
- whether it moves in this shot
- who controls it, if anyone

Avoid vague count terms:

- scattered
- several
- some
- many
- a few
- 散落
- 散乱
- 数个
- 若干

Use exact terms instead:

```text
3 photos lie flat on the lower-left floor, all visible in the first frame, static throughout the shot.
```

For mobile phones, screens, paper, cups, handles, and thin devices, describe structure and handling explicitly.

### Photo Side Visibility

Photos are two-sided props. A prompt must not rely on the model to infer which side is visible.

Whenever a shot includes looking at, holding, pointing at, handing over, flipping, or displaying a photo, the record must define:

- prop id
- count
- size and thickness
- material
- front-side content
- back-side appearance
- current visible side
- orientation to viewer or character
- whether flipping is allowed
- whether extra photos are allowed

Default photo profile:

```json
{
  "prop_library": {
    "SAKURA_SCHOOL_PHOTO": {
      "display_name": "佐藤樱子的校服照片",
      "count": "1张",
      "size": "约10cm x 15cm x 0.3mm",
      "material": "半光泽相纸",
      "front_description": "正面是佐藤樱子的清晰照片影像，低饱和照片色调，白色细边",
      "back_description": "背面是纯白或浅白色相纸，无图像、无文字、无花纹",
      "structure": "单张矩形薄照片，正反面清楚，不是照片堆",
      "canonical_motion_policy": "除非角色明确翻面，否则保持同一可见面，不新增照片副本"
    }
  }
}
```

If the audience should see the image:

```text
SAKURA_SCHOOL_PHOTO front side faces the camera/audience. The photo image is visible. The white back side is not visible.
```

If only the character should see the image:

```text
SAKURA_SCHOOL_PHOTO front side faces the character. The audience sees only the plain white back side. Do not generate an image on the back.
```

Avoid:

```text
She looks at scattered photos.
```

Prefer:

```text
One 10cm x 15cm photo lies flat on the lower-center floor. Its front side faces upward toward the camera, showing Sakura's portrait. No other photos appear.
```

### Phone Prop Orientation

For phone-call shots, the phone screen should usually face inward toward the holder, not outward toward the camera.

This avoids the model treating the phone screen as a second visual scene, subtitle surface, or unstable glowing prop.

Phone prop contract should define:

- who holds the phone
- which hand holds it, if important
- where it is held, such as near the ear or in front of the chest
- screen orientation
- whether the screen content is visible

Default phone-call rule:

```text
One smartphone held by A near the ear, screen facing inward toward A, screen content not visible to camera.
```

If the story requires the screen to be visible, define the exact content and keep it minimal.

## Motion Policy

Each shot should define allowed motion and forbidden motion.

Dialogue shots should prefer:

- static or near-static camera
- subtle head movement
- natural breathing
- small eye movement
- no walking
- no prop handoff
- no large gesture

Action shots may allow movement, but should usually suppress speech and complex prop interaction.

Scene-only shots should not inherit main character anchors.

## Safety Wording

Prefer positive safety wording over negative sexual or unsafe terms.

Good:

```text
Characters are fully clothed and keep ordinary social distance.
```

Avoid:

```text
No nudity or sexual suggestion.
```

Provider safety systems may still react to negative terms, even when the intent is prohibition.

## Final Prompt Shape

`prompt.final.txt` should be structured into predictable blocks.

Recommended blocks:

```text
SCENE:

FIRST FRAME:

SHOT TASK:

CAMERA:

PERFORMANCE:

DIALOGUE / LIP SYNC:

PROPS:

MOTION CONSTRAINTS:

CONTINUITY:

POSITIVE SAFETY / STABILITY:
```

The final prompt should be concise, concrete, and control-oriented. It should read like director blocking, not novel prose.

## Example Library

The examples in this section are reusable prompt patterns adapted from `I2V_prompt_enginnering.md`. They should be treated as building blocks, not as free-form replacements for record fields.

### Dialogue: Active Speaker With Silent Listener

Use when two people are visible, but one person owns the speech task.

```text
SCENE:
Cinematic realistic interior, stable character design.

FIRST FRAME:
A's face is centered and sharp in medium close-up. B is visible only as a silent foreground shoulder/listening profile.

SHOT TASK:
Single-speaker dialogue shot.

CAMERA:
Over-the-shoulder shot from B, static camera, clear eye line.

PERFORMANCE:
A speaks calmly with natural lip movement and subtle head movement. B listens silently and remains still.

DIALOGUE / LIP SYNC:
Only A speaks. B has no lip movement. No double speaking. No extra mouth motion.
```

### Dialogue: Reverse Speaker Shot

Use after an A-speaking shot when B now owns the speech task.

```text
SCENE:
Same interior and same character placement as the previous shot.

FIRST FRAME:
B's face is centered and sharp in medium close-up. A is visible only as a silent foreground shoulder/listening profile.

SHOT TASK:
Reverse single-speaker dialogue shot.

CAMERA:
Reverse over-the-shoulder shot from A, static camera, consistent eye line.

PERFORMANCE:
B is the only speaker, with clear natural lip movement. A listens with a subtle reaction.

DIALOGUE / LIP SYNC:
Only B speaks. A has no lip movement. No double speaking. Stable facial features.
```

### Dialogue: Silent Reaction Insert

Use between two speaker shots to stabilize rhythm and avoid speaker switching inside one generation.

```text
SCENE:
Same conversation space and same lighting.

FIRST FRAME:
B is framed in close-up, looking toward A.

SHOT TASK:
Silent listening reaction.

CAMERA:
Static close-up, no camera move.

PERFORMANCE:
B listens silently, slight eye movement, small controlled nod, no speech.

DIALOGUE / LIP SYNC:
No one speaks in this shot. B has no lip movement.
```

### Prop: Thin Display Or Phone-Like Device

Use when a screen, phone, tablet, paper, or thin object is important and shape stability matters.

```text
PROPS:
One slim modern device, ultra-thin body, about 8mm thickness, narrow black bezel, flat glass surface, lightweight metal frame, correct proportions.

MOTION CONSTRAINTS:
The device maintains a thin side profile during movement. No large rotation. No bulky thickness. No brick-like shape. No toy-like proportions.
```

### Action: Door Opening Split

Use multiple shots instead of asking one generation to perform the whole action chain.

Shot 1:

```text
FIRST FRAME:
A stands in the hallway facing a closed apartment door, right hand beginning to move toward the silver handle.

SHOT TASK:
Approach and reach only.

PERFORMANCE:
A slows down naturally and reaches toward the handle. No speaking.

MOTION CONSTRAINTS:
Realistic body mechanics, stable hands, stable anatomy, smooth motion.
```

Shot 2:

```text
FIRST FRAME:
Close shot of the apartment door already half open inward, silver handle slightly turned down.

SHOT TASK:
Show result of door opening.

PERFORMANCE:
The door continues a small smooth inward movement.

MOTION CONSTRAINTS:
Correct door geometry, realistic hinge motion, no distorted hand, no broken motion.
```

Shot 3:

```text
FIRST FRAME:
A stands beside the half-open door, body turned sideways, ready to pass through.

SHOT TASK:
Pass through the doorway.

PERFORMANCE:
A turns sideways and walks through the half-open doorway naturally. No speaking.

MOTION CONSTRAINTS:
Realistic spacing between body and door frame, smooth continuous movement, stable joints.
```

### Full Dialogue Prompt Example

This is an example of the preferred structured `prompt.final.txt` style for a two-person first-frame dialogue shot.

```text
SCENE:
Modern Ginza office at night, vertical cinematic realism, low saturation, realistic light.

FIRST FRAME:
Ayaka's face is centered and sharp in medium close-up. Kenichi is visible only as a silent foreground shoulder on the right side. Ayaka is the first and only speaker in this shot.

SHOT TASK:
Single-speaker dialogue. No walking, no prop handoff, no speaker change.

CAMERA:
Over-the-shoulder shot from Kenichi, static camera, stable eye line.

PERFORMANCE:
Ayaka speaks calmly with controlled facial movement. Kenichi listens silently without turning toward camera.

DIALOGUE / LIP SYNC:
Only Ayaka speaks. Kenichi has no lip movement. No double speaking. No extra mouth movement.

PROPS:
One closed folder lies flat on the desk in the lower-left frame, visible in the first frame, static throughout the shot.

MOTION CONSTRAINTS:
Subtle head movement and natural breathing only. No walking. No large hand gesture. No moving the folder.

CONTINUITY:
Same office layout, clothing, and lighting as the previous shot.

POSITIVE SAFETY / STABILITY:
Characters are fully clothed and keep ordinary social distance. Stable face, stable hands, realistic proportions.
```

## QA Rules

Before video generation, inspect the rendered record and `prompt.final.txt` for:

- more than one active onscreen speaker
- speaker not visually dominant in first frame
- visible non-speaker missing no-lip-movement policy
- first frame containing multiple locations or sequential actions
- shot containing speaking + walking + prop interaction
- vague static prop count
- important prop missing position or first-frame visibility
- negative sexual safety terms
- scene-only shot inheriting main character anchors
- keyframe metadata silently overriding record fields

If any of these appear, fix the record first when possible, then re-render the final prompt.

## Working Summary

Use LLM as planner and refiner. Use deterministic rendering as compiler. Use QA as gatekeeper.

The practical hierarchy is:

1. source novel facts
2. structured episode and shot records
3. I2V contracts inside records
4. keyframe metadata as supplement only
5. compiled `prompt.final.txt`
6. provider payload

Never let a polished final prompt silently override the record.
