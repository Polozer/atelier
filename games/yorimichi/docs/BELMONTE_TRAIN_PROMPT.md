# Belmonte luxury train — deferred concept prompt

Status: prepared brief only. Generate images only when the user explicitly asks to generate the train inspirations. This document does not authorize image generation, paid 3D calls, asset creation or map edits by itself.

## Copy-ready prompt

Design an original, exceptionally luxurious passenger train linking Belmonte, Haras Valley's Tuscan hill town, to the city in Yorimichi. Use Hidamari as the provisional destination name, subject to confirmation. The brother is integrating the Belmonte map first; other Haras Valley features will follow. This task concerns train inspiration and modelling references only, independent of that map work.

Create exactly two coach types: a restaurant coach and a first-class seated coach. Give them the same carriage body, roof profile, undercarriage, bogies, couplers, vestibules, door design and exterior livery. Do not design a locomotive, sleeper coach, station or railway route at this stage.

Art direction: the romance and extraordinary craftsmanship of an Orient Express-style journey, interpreted as an original train for this game. Early twentieth-century grand European rail travel, Belle Époque warmth and restrained Art Deco geometry. Deep midnight-blue lacquer, fine champagne-gold lining, a warm ivory window band, polished brass, a charcoal curved roof and a small original crest combining an olive branch with a sun motif. No real railway logos or copied insignia. Belmonte contributes Tuscan walnut, olive-leaf marquetry and discreet equestrian motifs; the destination contributes subtle sun patterns. Treat these as proposed design details, not established game lore.

Make it feel like an intimate travelling grand hotel: rich, elegant, welcoming and visibly expensive. Broad readable forms, carefully chosen ornament, warm light, exquisite materials. Fit the existing stylized game world with clean silhouettes, controlled surface detail and convincing proportions. Avoid both toy-like proportions and noisy photorealistic wear. Show satin lacquer, brushed and polished brass, walnut grain, velvet and woven fabric as distinct materials; preserve their readability in daylight as well as under warm lamps.

**Restaurant coach:** a walnut-panelled dining salon with olive-leaf marquetry, burgundy velvet banquettes, small tables dressed in ivory linen, porcelain, crystal glasses and individual brass lamps. Large windows frame the passing countryside. Propose four dining bays, each with a two-person table on either side of a continuous central aisle: eight tables, sixteen diners. Include a compact service bar and an enclosed galley at one end, with the service layout clearly separated from dining. Use restrained cream ceiling panels, brass ribs and a subtle patterned carpet. It must read immediately as a restaurant, with tables and seating that can actually be used.

**First-class seated coach:** an airy, peaceful salon with twelve generously spaced armchairs in a 1+1 layout, six per side of a continuous aisle. Arrange seats in sociable facing pairs around small walnut tables, with some views looking along the coach to show the rhythm. Deep emerald velvet, rounded upholstered backs, brass reading lights, elegant luggage racks, coat hooks, ivory curtains and a richly woven carpet. Include a compact luggage area and a discreet enclosed washroom at one end. This is a seated passenger coach: no beds or sleeping compartments. Luxury comes from space, craftsmanship and comfort.

Both coaches must be believable, fully enclosed, walkable game interiors. Keep a continuous clear aisle, reachable furniture, plausible ceiling height, end vestibules and connected gangway doors. Avoid loose furniture blocking circulation. Use approximately 24 m length over couplers, 3.1 m exterior width and 4.3 m height above rail as a preliminary shared envelope, with about 2.3 m clear interior height and a 0.95–1.0 m clear aisle. These are draft modelling targets, not engineering claims; revise together after checking the game's character and camera clearance. Railway gauge, platform height and curve limits remain to be agreed with the map owner.

## Generation sequence when requested

1. Recheck the brief and the local Yorimichi/Belmonte visual references. Produce one exterior three-quarter concept showing the two coaches together, one restaurant interior looking down the aisle and one first-class interior looking down the aisle. Use the same design and colour family in all three. These are the initial inspirations for the user to review.
2. After the user chooses the direction, preserve those images as references and produce an asset reference pack for each coach: separate full-length left and right side elevations, both end elevations, an exterior three-quarter view, a roof-off floor plan and a longitudinal interior cutaway. Use neutral backgrounds and restrained lighting for technical views. Show genuine asymmetry such as galley and washroom positions; do not simply mirror sides.
3. Keep the window count, doors, bogie spacing, roof profile, furniture layout and proportions consistent across views. Orthographic views have no perspective distortion; concept views may use restrained perspective. Do not bake dimensions, lettering or layout labels into images as authoritative data. Provide the measured layout separately in text.
4. Supply close-up references for a dining bay, armchair/table pair, marquetry panel and brass lamp, only if needed to resolve the chosen design. Keep each image focused; do not attempt one crowded sheet containing every view.

For image generation through Atelier, use its existing ledgered image client with `gpt-image-2.5-sunburst`, `quality=high`, and retain the exact prompt, reference image hashes, model and output hashes in provenance. If that model is unavailable, report it and ask for an alternative; do not silently substitute. Do not automatically retry uncertain paid requests. Save generated material under the game's ignored build directory, then retain approved sources in the asset library according to repository rules.

## Asset preparation after concept approval

Return a proposed modular breakdown: shared body shell and roof; two shared bogies; couplers and gangways; exterior doors; coach-specific interior panels; dining banquettes and tables; first-class armchairs and tables; galley/bar; washroom; lamps; curtains; racks; and decorative trim. Furniture, doors and collision should be separate where interaction requires it. A train interior should be authored as a modular environment, not assumed to work as one automatic image-to-3D mesh.

Use metre-based Blender dimensions with explicit conversion to Unreal centimetres, agreed axes, pivots, material slots, simple walkable collision and LODs. Preserve crisp silhouettes and use normal maps or trim textures for fine decoration where appropriate. Verify the player and third-person camera in a simple carriage blockout before detailed modelling. Confirm polygon and texture budgets with Yorimichi before production.

Stop after presenting inspirations or the requested reference pack. Wait for the user's separate command before paid 3D generation, modelling, Unreal import, rail placement or implementation. No train assets or gameplay are implied to exist yet.

## Exclusions for every image

No locomotive, sleeper cabin, modern commuter seating, aircraft interior, futuristic machinery, steampunk clutter, oversized fantasy wheels, excessive gilding, real brand logos, people hiding the design, blocked aisles, impossible doors, inconsistent windows, disconnected bogies, extreme wide-angle distortion or exterior scenery obscuring the coach silhouette.
