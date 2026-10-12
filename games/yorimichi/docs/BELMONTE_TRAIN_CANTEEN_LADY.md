# Belmonte train: the canteen lady

The comic NPC of the shabby second-class coach at the back of the Belmonte train
([the missing vehicles](BELMONTE_TRAIN_MISSING_VEHICLES_PROMPTS.md#3-shabby-second-class-coach-with-a-canteen-required-at-the-back),
[the shell](BELMONTE_TRAIN_SHELL.md)). She stands behind the canteen counter and ladles grey, lumpy old porridge
(*bouillie*) from a huge dented pot onto tin plates. This first step is the brief and the image prompts; the owner
paints the images in ChatGPT and builds the models with their own Tripo Studio credits. No paid API call is made for
her unless the owner asks.

## Brief

**Working name.** `canteen-lady` (id); display name **Zia Pappa** ("Aunt Porridge": *pappa* is the Tuscan bread
porridge), to confirm or replace.

**Who she is.** The legend of the back of the train. She has served the same porridge on the same line for thirty
years and considers it a dish, not a punishment. Warm-grumpy: she barks "Next!", glares at anyone who sniffs at the
plate, then quietly adds an extra ladle to the thinnest passenger's plate. Proud of her pot, her ladle and her
counter, which is the only clean thing in the coach. The joke is her dignity against the food and the coach, never
her body or her class: she is competent, formidable and kind underneath, and the passengers love her.

**Scale and proportions.** 1.65 m (`height_cm = 165`), Cairo is 1.48 m, Kaede 1.68 m, the fox hunter 1.70 m, Modori
1.75 m. So she is about Kaede's height, but much wider: the broadest body in the game, roughly 1.4x Kaede's shoulder
width, a big round barrel torso with a high bosom and a wide waist, short thick legs, strong forearms and big hands.
Adult proportions (about 5 heads tall, a smaller head relative to the body than Cairo's). She reads from the far end
of a 24 m coach as one bold shape: a wide trapezoid topped by a knotted headscarf.

**Art style.** Yorimichi's own: soft, smooth, stylised 3D with a matte painted finish, chunky simplified forms, a
simple face with two plain dark oval/pill eyes, a small nose and mouth (Cairo's face language), five-fingered hands.
Big, clean shapes the Tripo workflow can model and the texture clean-up can flatten: no fine patterns, lace or small
straps. Grime and stains are a few large flat shapes, never noise ([Tripo characters](TRIPO_CHARACTERS.md): Tripo's
noise is cleaned away, so anything small is lost anyway).

**Face.** Round, rosy cheeks, a strong straight nose a little bigger than Cairo's, heavy expressive dark brows (her
main acting tool: one is always a little higher), a small firm mouth that sets into a flat line, a soft double chin.
Late fifties; a few grey curls escape the scarf at the temples. Warm peach skin like the game's other characters.

**Costume** (from top to bottom):

| Part | Look | Colour |
| --- | --- | --- |
| Headscarf | a cotton scarf tied over the hair, knotted on top at the front in two short stiff "ears"; grey-auburn curls at the temples | faded brick red with a few large off-white dots |
| Smock | short-sleeved work smock, sleeves rolled up above the elbow in thick cuffs, a simple round collar | dusty sage green, faded |
| Apron | a big bib apron, tied tight at the waist, ending at mid-thigh; two large flat stains (a grey porridge splash, a rust-brown smear) and a brass "2" badge pinned to the bib, the same crooked "2" as the coach | yellowed off-white |
| Trousers | loose cook's trousers to mid-calf | charcoal brown |
| Socks and shoes | thick rolled grey socks, sturdy black clogs with thick flat soles | grey, black |
| Extras | a tea towel tucked into the apron string (short, close to the hip) | faded blue check, drawn as 3-4 broad stripes |

**Palette in the coach.** The second-class coach is chalky faded blue, yellowed ivory, dull brass and verdigris,
peeling brown paint, scuffed linoleum. She must read against it: the brick-red scarf and the sage smock are her
accents, the off-white apron her big light shape. Nothing midnight blue, gold or walnut on her: that is first class.

**Props** (separate meshes, not part of the body; the ladle attaches to `hand_R`):

| Prop | Size (target) | Look |
| --- | --- | --- |
| Pot | 0.55 m across, 0.45 m tall (about 100 l), on the stove behind the counter, rim near 1.30 m above the coach floor | battered aluminium, two big riveted side handles, three obvious dents, a scorched black bottom, a crust of porridge dried down one side, a wisp of steam |
| Ladle | 0.70 m long, bowl 0.13 m across | dull steel, a long round handle with a hook at the end, a slight bend in the handle, a dent in the bowl |
| Tin plate | 0.25 m across | white enamelled tin with a chipped dark-blue rim (a nod to the livery), one or two black chips; a grey lumpy dollop of porridge with one suspicious big lump and a skin on top |

The counter is part of the coach build (0.92 m high like the galley worktops in
[`world/train/layout.py`](../world/train/layout.py)); the stack of plates is the plate repeated.

**Personality in motion.** Strong, readable, slightly theatrical gestures, timed with a beat of comic stillness:
she holds a pose half a second longer than needed. Heavy, planted weight; she moves her whole torso, not just her arms.

**Animations needed** (her own clips, authored in Blender like Kaede's Bow and Talk; game-local roles, the platform
roles are not redefined):

| Role | Loop | What it shows |
| --- | --- | --- |
| `Idle` | yes | fists on hips, weight shifting, a slow suspicious look around, a sniff |
| `CanteenStir` | yes | both hands on the ladle, stirring the pot with her whole body, a heave at each turn |
| `CanteenServe` | no | scoop, lift, a held beat, the *plop* onto the plate (a sound cue on the contact frame), a flick of the wrist |
| `CanteenHandOver` | no | pushes the plate across the counter with a firm slide and a nod |
| `CanteenCallNext` | no | bangs the ladle twice on the pot's rim and calls out |
| `CanteenGlare` | no | leans over the counter, brows down, ladle pointed: the answer to a complaint |
| `CanteenSoftSpot` | no | glances round, sneaks an extra ladle onto the plate, a tiny wink |
| `Talk` | yes | grumbling conversation, one hand gesturing with the ladle |

Sound cue names follow [naming](../../../platform/conventions/naming.md): `canteen.plop`, `canteen.pot_bang`,
`canteen.stir`. She does not walk on screen in the first version; the move set retarget
(`adventure/retarget.py --character canteen-lady`) can give her walking later if the scenes need it.

## ChatGPT image prompts

Paint each image in its **own request** and ask for **one figure per image**: a request for a turnaround sheet comes
back as a sheet, and Tripo Studio's multiview upload needs four single-figure views at the same scale.

Attach to the body requests, as the style reference only:
[`concepts/modori-tpose/front.jpg`](../assets/characters/concepts/modori-tpose/front.jpg) (a T-pose front in the
game's style). For the expression sheet also attach [`concepts/modori.jpg`](../assets/characters/concepts/modori.jpg)
for the sheet layout. Once the front is chosen, attach **only that front** to the back, left and right requests.

### 1. Front view, T-pose (the Tripo reference)

```text
Input image: a T-pose render of a character from our stylised 3D game Yorimichi. Use it ONLY as the authority for
the art style and the reference-sheet framing: soft smooth stylised 3D, matte painted colour, chunky simplified
shapes, a simple face with two plain dark oval eyes without whites, a small nose and mouth, hands with five fingers,
plain background, soft even light. Do not copy his identity, body, hair or clothes.

Design a NEW character in exactly that style: the canteen lady of the shabby second-class coach of a luxury train, a
comic, warm-grumpy and formidable school-canteen cook in her late fifties with her own pride. About 165 cm tall, a
big, stout, powerful build: very broad shoulders, a big round barrel torso with a wide waist, strong thick forearms,
big capable hands, short sturdy legs. Adult proportions, about five heads tall. A round face with rosy cheeks, a
strong straight nose, heavy expressive dark brows with the left one slightly raised, a small firm mouth set in a
flat line, a soft double chin, a few grey-auburn curls escaping at the temples. Dignified and funny, never ugly or
mocked.

Costume: a faded brick-red cotton headscarf with a few large off-white dots, covering her hair, knotted on top at
the front in two short stiff ends. A dusty sage-green short-sleeved work smock with a simple round collar, the
sleeves rolled up above the elbows in thick cuffs, bare forearms. A big yellowed off-white bib apron tied tightly at
the waist and ending at mid-thigh, close to the body, with two large flat stains (a grey splash and a rust-brown
smear) and a small brass badge shaped like a crooked number 2 pinned on the bib. A short faded blue-and-white
checked tea towel tucked into the apron string at her right hip. Loose charcoal-brown trousers to mid-calf, thick
rolled grey socks, sturdy black clogs with thick flat soles.

Pose: a symmetrical T-pose. Both arms straight out horizontally at shoulder height, palms facing down, fingers
together and straight, thumbs relaxed. Legs straight with a small gap between them, feet forward, flat on the floor.
Every garment fits close to the body: the apron ends at mid-thigh and does not flare, no cloth bridging the armpits
or between the legs, no loose hair. Neutral, slightly stern expression, eyes open.

Composition and light: ONE full-body FRONT view only, a true frontal orthographic-style view, no rotation, no
perspective, camera level with the chest. Whole figure centred on a square canvas with clear margin around the
fingertips, headscarf and feet. Plain white background, soft even diffuse light, minimal shadow, no ground plane, no
cast shadow. No props: no ladle, no pot, no plate, nothing held. No text, labels, borders, insets or colour swatches.
Draw exactly ONE figure, seen from the front only: never a second view or a turnaround. This is a reconstruction
reference for 3D, not an action pose.
```

Paint two or three and keep the best. If a take comes back in an A-pose, ask for "the same character, same image
scale, arms straight out horizontally"; Tripo's rigging works best from the T-pose the other characters used.

### 2. Back, left and right views (from the chosen front)

Attach only the chosen front. One request per view; the shared part first, then the view's sentence.

```text
Input image: the approved FRONT reference of the canteen lady, a character in our stylised 3D game Yorimichi, in a
T-pose. It is the sole authority for identity, proportions, costume, palette and materials: preserve exactly her
stout build, the brick-red dotted headscarf and its knot, the sage-green smock with rolled sleeves, the off-white bib
apron with its stains and brass 2 badge, the checked tea towel at the right hip, the charcoal-brown trousers, grey
socks and black clogs. Soft smooth stylised 3D, matte.

[VIEW]

Keep the same T-pose with the arms straight out horizontally, the same image scale, head height and floor baseline as
the front view. Orthographic-style projection, no perspective, camera level with the chest. Plain white background,
soft even diffuse light, no ground plane, no cast shadow. Fit the complete silhouette on the square canvas with clear
margin. Include only this one view: no labels, border, props, insets, text or extra figures.
```

- **Back:** `Create the full-body BACK reference view. She faces away from the camera: the back of the headscarf and
  its tied ends at the nape, the back of the smock, the apron strings crossed and tied in a bow at the waist, the backs
  of the arms with palms down, the heels of the clogs.`
- **Left:** `Create the full-body LEFT reference view: her own anatomical left side, a true profile in which the nose
  points to the image-left. The near (left) arm points straight toward the camera and is strongly foreshortened,
  showing the hand end-on; the far arm is hidden behind it. Show the depth of the head, the scarf knot, the round
  torso, the apron bib, the trousers and the clogs in profile.`
- **Right:** `Create the full-body RIGHT reference view: her own anatomical right side, a true profile in which the
  nose points to the image-right. The near (right) arm points straight toward the camera and is strongly
  foreshortened, showing the hand end-on; the far arm is hidden behind it. Show the depth of the head, the scarf
  knot, the round torso, the tea towel at the hip, the trousers and the clogs in profile.`

### 3. Expression and pose sheet (acting reference, not for Tripo)

Attach the chosen front and `concepts/modori.jpg` (layout only).

```text
Input images: image 1 is the approved front reference of the canteen lady from our stylised 3D game Yorimichi: the
sole authority for her identity, proportions, costume and palette. Image 2 is another character's model sheet: use it
ONLY for the sheet layout, not for its character.

Create an acting sheet for her in the same soft, smooth, matte stylised 3D. Landscape sheet, plain white background,
even light. Top row: six head close-ups of the same face, each a clear exaggerated expression: stern and proud (chin
up, eyes half-closed), shouting "next!" (mouth wide, brows up), suspicious glare (brows down, one eye squinting),
offended (a hand on her chest, mouth an O), secretly tender (a small sideways smile and a wink), big belly laugh (eyes
shut, head back). Bottom row: five full-body poses holding a long dented steel ladle: fists on hips with the ladle
like a sceptre; stirring a huge pot with both hands and her whole body; the serve, the ladle tipped over a tin plate
with a lump of grey porridge falling; leaning over a counter pointing the ladle at the viewer; banging the ladle on
the rim of the pot. Strong readable silhouettes, heavy planted weight, comic but warm and dignified, never mocked.

Same character in every drawing: the same face, build and costume. No text, labels, speech bubbles or logos, no other
characters, no background scenery, no realistic skin or cloth shading.
```

### 4. Props, one image each (isolated objects for Tripo)

No attachment needed; attach the second-class coach references once they exist so the grime matches. One request
per prop, then a second take in a three-quarter view if Tripo needs it.

```text
A single isolated game prop for a stylised 3D game (soft smooth stylised 3D, matte painted colour, chunky simplified
shapes, clean modelable forms): [PROP]. It belongs to the comically run-down canteen of the second-class coach of an
old luxury train: worn, funny and charming, not disgusting. Three-quarter view from slightly above, the whole object
visible and centred with clear margin. Plain white background, soft even diffuse light, no ground plane, no cast
shadow. Only this one object: no hands, people, table, stove, other objects, text, labels or logos.
```

- **Pot:** `a huge battered aluminium cooking pot, about 55 cm across and 45 cm tall, with two big riveted side
  handles, three obvious dents in its side, a scorched black bottom and a crust of dried grey porridge running down
  one side, filled near the rim with grey lumpy porridge, a soft wisp of steam above it`
- **Ladle:** `a long dull-steel ladle, 70 cm long, a long round handle with a hook at the end and a slight bend
  halfway, a deep round bowl 13 cm across with a dent in it, lying flat, seen from slightly above`
- **Tin plate:** `a 25 cm white enamelled tin plate with a dark-blue rim, the enamel chipped black in two places,
  holding a dollop of grey lumpy porridge with a wrinkled skin on top and one suspiciously big lump`

## Where the images go

Everything generated stays in the ignored build directory until it is chosen:

| What | Folder |
| --- | --- |
| Every take, with its prompt as `<name>.prompt.txt` (the model: ChatGPT's built-in image tool) | `build/yorimichi/characters/concepts/canteen-lady/` |
| The four chosen T-pose views for Tripo, as PNG | `build/yorimichi/characters/concepts/canteen-lady-tpose/tripo/front.png`, `back.png`, `left.png`, `right.png` |
| The expression sheet | `build/yorimichi/characters/concepts/canteen-lady/acting-sheet.png` |
| The prop references | `build/yorimichi/train-concepts/canteen-props/r01/pot.png`, `ladle.png`, `tin-plate.png` |

Once approved, the four views (as JPG) and the acting sheet come into the repository under
`assets/characters/concepts/canteen-lady-tpose/` and `assets/characters/concepts/canteen-lady.jpg`, as Modori's did.

## After the images: Tripo Studio and the Atelier pipeline

The owner's part, in Tripo Studio:

1. **Body.** Multiview image-to-3D with the four T-pose views (front, back, left, right), then Smart Mesh as a
   game-ready quad mesh (about 12,000 faces, as Modori), Smart UV, texture. Then **Rig**, the biped (Mixamo)
   skeleton. Download the textured GLB and the rigged FBX/GLB into `build/yorimichi/characters/canteen-lady/tripo-r01/`.
2. **Props.** Single-image to 3D for each prop (pot, ladle, plate), textured, a few thousand faces each; no rig.
   Download into `build/yorimichi/train-concepts/canteen-props/tripo-r01/`.

Then, in Atelier (the agent's part, following [Tripo characters](TRIPO_CHARACTERS.md)):

1. **Clean-up:** one mesh, facing +X, soles on z = 0; scaled to 1.65 m on export (`height_cm`, Tripo exports 1 m).
2. **Fingers:** `atelier.blender.tripo_fingers.add_fingers`, for the humanoid contract's 53 bones
   (`platform/conventions/rigs/humanoid.toml`, renamed from Mixamo by `mixamo_aliases`). Her big hands may need a
   wider `thumb_band` than Kaede's 0.2.
3. **Eyes, light and noise:** `tripo_character_texture` with her `face.json` (eyes, the heavy brows, the mouth),
   flat painted colour; the apron stains and the scarf dots must survive the region merge (judge them against
   `before-body.png`, lower `--merge-l` if they vanish).
4. **The apron:** it hangs to mid-thigh, past the rule that nothing hangs below the hips; it is weighted to the
   thighs and checked in the serve and stir clips. If it stretches, it becomes a second Tripo part fitted on the body,
   as Modori's coat.
5. **Her own clips** (the table above), posed in Blender, a `hand_R` socket for the ladle, the plate's contact
   frames recorded.
6. **Promote:** `promote.py canteen-lady <revision>` into `assets/characters/canteen-lady/` with its
   `character.toml` (`role = "npc"`, `height_cm = 165`), `source-manifest.json`, `face.json` and `export_unreal.py`;
   Unreal `/Game/CanteenLady`, `SK_CanteenLady`, clips `A_CanteenServe`... The props become `SM_CanteenPot`,
   `SM_CanteenLadle`, `SM_TinPlate`, placed by the second-class coach build in `world/train/`.
