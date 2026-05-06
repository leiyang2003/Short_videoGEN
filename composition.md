# Composition Notes

## Two Visible Characters, One Active Speaker

Use these templates when a shot requires two characters in the first frame but only one character speaks. The core rule is:

```text
single active speaker does not mean single visible character
```

The active speaker needs clear face and mouth visibility. The silent listener must still appear when listed in `visible_characters`, with a visible face and closed mouth.

### A. Speaker-Led Two-Shot

The speaker is centered or slightly forward. The silent listener is beside or slightly behind the speaker.

- Use for ordinary dialogue and stable relationship beats.
- Speaker: face and mouth clear, front or three-quarter face.
- Listener: side or three-quarter face visible, mouth closed, no lip movement.
- Good default for most two-person dialogue shots.

Prompt shape:

```text
Two-person medium shot. ACTIVE_SPEAKER is the visual center, face and mouth clearly visible while speaking. SILENT_LISTENER stands beside or slightly behind, face visible in three-quarter view, mouth closed, listening silently.
```

### B. Over-Shoulder Toward Speaker

The camera looks past the silent listener toward the speaker.

- Use when the speaker's line has pressure, intimacy, persuasion, or testing.
- Speaker: front or three-quarter face clear.
- Listener: shoulder, side face, or partial face visible; must be identifiable, not a background extra.
- Strong fit for whispered or emotionally loaded dialogue.

Prompt shape:

```text
Over-the-shoulder two-person composition from SILENT_LISTENER's side toward ACTIVE_SPEAKER. ACTIVE_SPEAKER faces the camera side with clear mouth while speaking. SILENT_LISTENER remains in the near foreground with visible side face or profile, mouth closed, listening silently.
```

### C. Side-Facing Dialogue Two-Shot

The two characters face each other from left and right.

- Use for direct questions, confrontation, negotiation, or distance.
- Speaker: mouth side must be clear.
- Listener: face visible, mouth closed.
- Higher lip-sync risk than A/B; use explicit silent-listener constraints.

Prompt shape:

```text
Two characters face each other in a side-facing dialogue composition. ACTIVE_SPEAKER's face and mouth are clearly visible while speaking. SILENT_LISTENER's face is visible from the side or three-quarter angle, mouth fully closed, no lip movement.
```

### D. Speaker Close-Up With Listener Edge Reaction

The speaker occupies most of the frame. The listener appears near the edge or softly in the background.

- Use when the line content and speaker emotion matter most.
- Listener must remain identifiable and story-required.
- Do not let the listener disappear into generic background.

Prompt shape:

```text
ACTIVE_SPEAKER dominates the frame in close medium shot, face and mouth clear while speaking. SILENT_LISTENER remains visible at the frame edge or background, identifiable, face visible, mouth closed, listening silently.
```

### E. Reflection Composition

One character is visible directly and the other through a mirror, window, or dark reflection.

- Use for suspense, manipulation, or emotional distance.
- Higher generation risk: reflections can create duplicates or distorted faces.
- Avoid as default unless the record explicitly benefits from reflection imagery.

Prompt shape:

```text
ACTIVE_SPEAKER is directly visible with clear speaking mouth. SILENT_LISTENER is visible through a stable mirror or window reflection, identifiable, face visible, mouth closed, listening silently. No duplicate characters.
```

### F. Prop-Foreground Two-Shot

A key prop sits in the foreground while both faces remain visible.

- Use when dialogue is tied to a prop such as a tie, phone, photo, glass, or letter.
- Higher complexity: prop, hands, and faces must all remain stable.
- The prop must not hide the speaker's mouth or remove the listener.

Prompt shape:

```text
Key prop PROP_ID is visible in the foreground. ACTIVE_SPEAKER and SILENT_LISTENER are both visible behind or beside the prop. ACTIVE_SPEAKER's face and mouth are clear while speaking. SILENT_LISTENER's face is visible, mouth closed, listening silently.
```

## Recommended Defaults

Prefer these for WebUI/keyframe generation unless the record asks for something more specific:

```text
A. Speaker-Led Two-Shot
B. Over-Shoulder Toward Speaker
C. Side-Facing Dialogue Two-Shot
```

Use D/F only when the shot has a clear reason. Use E sparingly.

## Prompt Safety Rules

- Do not write constraints that allow the model to remove the listener, such as "if both faces conflict, prioritize the speaker" without also requiring the listener to remain visible.
- If `visible_characters` contains two characters, every named character needs:
  - a position
  - face visibility
  - speaking or silent state
  - whether mouth is open or closed
- The silent listener is not an extra person. Write this explicitly when the prompt also says "no extra characters."
- Character lock/reference guidance should include all first-frame visible named characters, not only the active speaker.

## SH05 Example

For EP02 SH05, a stable choice is:

```text
Over-the-shoulder two-person composition from Tanaka Kenichi's side toward Sato Ayaka. Sato Ayaka is the active speaker, centered in three-quarter face with clear mouth while speaking. Tanaka Kenichi is the required silent listener in the near foreground, side face visible, mouth closed, listening silently. Both are in the Ginza hotel suite first frame.
```
