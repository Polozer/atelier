# Charakuru: heads and bodies made separately

[Charakuru](https://github.com/nanocle/Charakuru) (きゃらくる) is a kit that turns one character illustration into a
VRM avatar with Tripo, an image model, Blender and an AI agent (Codex). Tripo sponsors it. These notes come from its
public docs and its v1.0.3 release (8 October 2026): `AGENTS.md`, the seven Skills and the Blender scripts. Nothing from
the kit is copied into this repository. They are here for experiments with our own pipeline
([Making a character](../../../docs/CHARACTER_PIPELINE.md), [Tripo characters](TRIPO_CHARACTERS.md)).

**The main idea: the head and the body are two separate Tripo jobs.** Each has its own four views, its own mesh budget
and its own textures. They use the same Tripo model as we do (Smart Mesh P2.0); the difference is how much of every
budget the face gets.

## Why our faces come out badly

Our characters go to Tripo as one full-body T-pose turnaround with an 8,000-face limit
(`tripo_asset.py generate --faces 8000`). In that turnaround the face covers a few percent of each image, and it ends up
with a few hundred faces and a small share of one texture. Eyes, ears and mouths suffer first; the
[face fix](TRIPO_CHARACTERS.md#eyes-light-and-noise-the-fix-almost-every-tripo-character-needs) and Modori's painted
face work around it afterwards. [Modori's README](../assets/characters/modori/README.md#known-limits) also notes
about 1 mm texels behind the ears, from Tripo's UVs.

Charakuru gives the head a square image of its own in every view, up to 25,000 quads and its own 4K textures.

## The workflow, step by step

👤 marks a checkpoint where a person decides. The agent never picks a candidate and stops at every checkpoint. The kit
names the agent (Codex) but not the image model behind Codex's built-in image generation. Every Tripo step is done
by the agent clicking through the Tripo Studio website in the user's signed-in browser, not through an API.

### 1. Load the illustration

One full-body illustration. A character sheet with a face close-up or a back view helps.

### 2. Write a painting brief from finished art

**Tool:** the agent, browsing Pinterest.

- It searches for *finished* character art and close-ups ("VTuber model art close up", "Live2D face closeup"),
  not tutorials.
- It writes what it sees as place → colour, edge or highlight → how to use it here. For example: a thin warm line on
  the upper eyelid, a deeper rim on the lower lid, wider pale colour across the cheek.
- **Only the words go into prompts.** Third-party images are never passed to the image model.

### 3. Draw eight images: head and body, four views each

**Tool:** Codex's image generation.

- **One part and one view per call.** The front comes first and must be fully finished before the other views.
- **The other views are edits of the approved front.** Each prompt gives every image a role, for example "Image 1 is
  the approved front: identity, proportions and painting standard. Image 2 is a source view, used only for depth."
- **Head:** the face, the ears and *all* the hair, down to the longest tips (even waist-length hair stays with the
  head). No neck, shoulders or collar.
  - The pose is corrected: the eyes are level, the face's centre line is vertical, and the face is straight on to
    the camera.
  - The expression is neutral: lips closed, brows and eyes relaxed. The prompt says not to keep the illustration's
    smile or open mouth.
  - If long hair makes the face small, the agent also checks a zoomed-in crop. It never trims hair to enlarge the face.
- **Body:** neck down, with a bare top end to the neck "that can insert into the head", and no stand or cap on it.
  - A strict T-pose: upper arms level at shoulder height, elbows and wrists straight, feet slightly apart. The arms are
    not lowered because they overlap in the side views.
- **Left and right:** every prompt says both which side is visible and which way the face points on screen. Views are
  never mirrored, so one-sided details stay on the right side.

  | File | Visible side | Nose points | The character's left-side detail |
  |---|---|---|---|
  | front | front | at the viewer | screen right |
  | left | the character's left | screen left | nearest the viewer |
  | right | the character's right | screen right | far side, hidden as it would be |
  | back | back | away | screen left |

- **Canvas:** square, the part filling it with a margin, a real transparent background, the same scale and baseline in
  all four views.
- **Painting:** the prompts never ask for "flat colors", "single shadow tone", "no highlights" or "minimal shading".
  They describe the finish part by part: colour across the eyelids, eye corners, cheeks and mouth; coloured lashes;
  shading on the white of the eye; layered colour inside each existing hair lock without new strands; a different
  sheen for matte cloth, satin, leather and metal. They also say not to copy the front's highlight positions onto
  the side views.
- **Fixes:** name the exact place and what is missing. Shape errors and paint errors are fixed separately. **If two
  fixes in a row do not help, stop** and report what is left.
- The real prompt is saved inside each PNG's metadata.

👤 A person reviews the eight images and can ask for any one to be redone.

### 4. Make 3D candidates

**Tool:** Tripo Studio, **Smart Mesh P2.0**.

- **Quads, 25,000 faces, 4 candidates**, one job for the head and one for the body (each from its four views).
- Use the cube icon (four-view multiview), not the stacked-images icon (batch input of up to 30 images).
- Studio saves its settings automatically, so every value is checked at the start.
- Every candidate is downloaded as FBX. If the browser blocks a download, the person saves that file by hand;
  **nothing is generated again**, since it would cost credits.

👤 A person picks one head and one body.

### 5. Split into parts

**Tool:** Tripo Studio segmentation, **coarse** setting (the kit names no version); then the agent, by eye.

- The chosen head and body are first exported as **triangulated GLB** and uploaded again for segmentation.
- A script splits each mesh into its loose pieces. The agent labels every piece head, hair or body by looking at it
  from the front, side and back, never by its size or position alone.
- At most **7 texture groups** (for example skin, hair, top, waist, legs and shoes). **Head pieces and body pieces never
  share a group.**
- Swinging parts (skirt, ribbons, straps) are listed separately; they may share a texture with fixed parts.
- If a cut would have to go through joined faces, the agent shows a picture and asks. Its two options: cut it in
  Blender (described as unreliable) or regenerate or pick another candidate in Tripo (described as more reliable).

### 6. Redo the textures

**Tools:** Codex's image generation for reference paintings; Tripo Studio **Smart UV**, then Tripo's **texture**
tool.

1. For each group, a script renders a **wireframe front and back of the real mesh**.
2. The agent paints a new front and back picture of *only that group*: "Image 1 is the wire guide (shape and part
   boundaries). Images 2 onward are the approved views (colour, pattern and finish). Remove the wireframe, viewport UI
   and grey clay shading."
3. Each group is uploaded to Tripo on its own. **Smart UV runs first** (limits: 80,000 triangles or 40,000 quads,
   150 MB). Then Tripo repaints it from the two pictures at **4K, with Remove Lighting off, no remesh and no polygon
   reduction**.
4. Uploads use 0° rotation; the agent checks in Tripo's preview which way the face points and never adds a second 90°.
5. A script copies the returned UVs and texture back onto the **original mesh**. It matches faces by position (after
   undoing Tripo's move and scale), not by vertex order, and refuses the result if the shape changed, a face is
   missing, or the group does not have exactly one 4096 px base-colour image.
6. Toon materials (VRM MToon) go on here and stay to the end.

The UVs are only a container for Tripo's repaint. Nothing is painted in UV space by hand or by an image model.
**Each group gets its own 4K sheet**, so the face and skin group alone has a full 4K texture.

### 7. Put the head on the body

**Tool:** sliders in the kit's app.

- The parts arrive at standard sizes: the body 1.45 m tall, the head 0.30 m, both centred.

👤 A person moves and scales the head, hair and body until the neck sits right, from the front and the side (with an
option to move the hair with the head). The placement is then baked in; changing it later means rigging again.

### 8. Rig

**Tools:** Tripo Studio auto-rig; weights by a script in Blender 5.2.

- The head and body go to Tripo **without the hair**, with the clothes and swinging parts, as one FBX in world space.
- **Only the bone positions are kept.** Tripo's weights and rigged mesh are thrown away.
- The body's weights come from a **bundled weighted base body, stretched to fit**: the neck is the torso anchor
  (so the chest and head do not stretch), limbs are matched by bone length, width and depth corrections stay between
  0.8 and 1.2, and mirroring is off so Tripo's asymmetry is kept.
- **The head is 100% on the head bone**, a rigid shell.
- Swinging parts are pinned to the hips for now.

👤 A person watches a walk cycle: shoulders, elbows, knees and neck.

### 9. Swinging parts and export

**Tools:** Blender with Blender MCP and the VRM add-on.

- The hair goes back on, rooted to the head. Only the long hair, fringe, skirt and ribbons swing.
- Colliders on the head, chest, hips and legs.
- A scripted test turns the head, leans the body and bends the knees, and looks for jitter, clipping, roots lifting off
  and overstretching.
- It exports `avatar.vrm` and an editable `avatar.blend`, then **loads the VRM again** to check that the physics move.
  Anything it could not check is reported as a remaining issue.
- No eye bones, look-at or expressions on purpose.

👤 A person checks the result.

## How the head meets the body

Nothing is stitched. The join holds because of four choices:

1. **The neck plugs into the head.** The head ends at the chin and the back of the skull; the body keeps the whole
   neck. The top of the neck sits inside the head, so no edge shows. The image prompts forbid a cut face or a cap,
   which Tripo would otherwise close the cut with.
2. **A person places it once** (step 7), and that placement is baked in before rigging.
3. **One rig for both** (step 8), from Tripo's bone positions only.
4. **The weights make it move together.** The rigid head turns about the top of the neck, which follows the neck bone
   and stays hidden inside the shell.

Skin colour across the join is checked by eye only: the head and body are always in different texture groups.

**Where it breaks:** with a rigid head nothing deforms under the chin, so a big turn or tilt can open a gap on a bare
neck. Their anime outfits mostly have collars, which hide it (Modori's collar would too). Nothing measures how deep
the plug sits.

**Ideas for us** (not in the kit):

- Taper the top of the neck and bury it a few centimetres. Check the widest head turns and look-ups in our clips for a
  gap, as we already check clearances on Cairo.
- Instead of a fully rigid head, blend the top 2 to 3 cm of the neck from the neck bone to the head bone.
- Sample the skin under the chin and match the neck's texture to it with a script.
- Keep the head and body as separate sections of one skeletal mesh in Unreal; that also gives the face its own
  material, for a painted face and later expressions.

## Tripo's API

Charakuru uses no API. Our client (`atelier.ai.tripo_asset`) already uses Tripo's v3 API, which accepts uploaded
files: that is how we rig a cleaned GLB. No documented Smart UV endpoint turned up (October 2026). The public Python SDK
(VAST-AI-Research/tripo-python-sdk, last updated 30 June 2026) lists texturing, conversion, segmentation, smart low
poly and rigging tasks, all working from a Tripo task ID. Its only UV options are `export_uv` at generation and
`convert_model(pack_uv=True)`, which repacks existing UVs. The v3 docs site renders only in a browser, so an
undocumented route cannot be ruled out. Ask Tripo before building on Smart UV.

Our own Smart UV uses were by hand in Studio: Modori's body, and one outfit whose 407 overlapping islands became 33
([BODY_SWAP_GUIDE.md](BODY_SWAP_GUIDE.md)).

## What it does not do

- The face is neutral with a fixed gaze: eyes are painted into the texture, so there is no blinking, expression or eye
  movement.
- Its painting guide says the quality bar is a goal, not something verified to come out reliably from any model.
- There are no measurements of results, and as a Tripo-sponsored kit it says nothing about other generators.

## Which model for heads

Charakuru does not show that heads need a different model; the budget is the lever. For context, the
[Top 3D AI Season 11](https://www.top3d.ai/leaderboard/seasons/sep-26) blind vote (26 September to 1 October 2026):

| Arena | Tripo | Meshy | Hunyuan 3D v3.1 |
|---|---|---|---|
| Textured | v3.1: 1,094 (1st) | 7.1: 1,057 (3rd, 196 votes); 7: 1,050 | 1,046 (7th) |
| Geometry | v3.1: 1,146 (1st) | 7: 1,122 (3rd); 7.1: 1,041 (11th, 137 votes) | 1,079 (6th) |
| Low poly | P2.0: 1,098 (1st, 91 votes) | T2: 999 | not in the top five |

The gaps are small and some samples are thin. P2.0 is entered only in low poly. Hunyuan 3D 3.0 and 3.1 are hosted
only; the newest open weights are 2.1. Meshy 7 and 7.1 market image-matched surface detail, so Meshy is the one to
try on heads if P2 at a full head budget is still weak.

## Experiments to try

In order of cost:

1. **A head-only P2 job.** Draw a head-only four-view set for an existing character (Cairo) to the rules in step 3,
   approve it, and run `tripo_asset.py generate --references <head>/references --output <head> --faces 25000`. Compare
   the eyes, ears and mouth with the current head at the same screen size. About 120 credits.
2. **A blank face.** The same job with the face left blank, then our painted face
   ([face spec](TRIPO_CHARACTERS.md#writing-the-face-spec), Modori's `FACE` table) on its own front-projected UV
   region. This keeps a painted face clean in our low-detail style and is the only route to blinking and expressions.
3. **The join.** Put the new head on the current body with the plug and the weight blend above, and check the widest
   head turns in Cairo's clips.
4. **Meshy on heads.** If 1 is still weak, the same approved head images through Meshy 7.1.
5. **Per-group retexturing** for bodies and clothes, by hand in Studio (Smart UV, then a 4K repaint from wireframe-guided
   pictures), until there is an API for it.
