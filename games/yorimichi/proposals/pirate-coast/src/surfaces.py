"""Painted Brinecove surface set and the material-to-texture mapping.

The Sunburst textures live beside this proposal under ``textures/``.  They are
neutral detail maps; ``references/textures.py`` tints them to the palette in
``layout.COLORS`` so the Blender render and the exported GLB share one look.
The metre scales below are world-space tile sizes used by the mesh builder's
box-projection UVs.
"""

SURFACES = {
    'plaster': dict(
        prompt=(
            'a seamless tileable texture of warm off-white lime plaster wall, soft trowel marks, '
            'fine mineral grain, a few hairline cracks and tiny chips, faint sun-bleached stains, '
            'neutral light tone that can be tinted, flat straight-on view'),
        scale=2.8),
    'roof': dict(
        prompt=(
            'a seamless tileable texture of old clay barrel roof tiles in neat overlapping rows, '
            'chipped rounded edges, slight colour variation, a little moss in the seams, pale neutral '
            'terracotta tone that can be tinted, flat straight-on view'),
        scale=1.9),
    'stone': dict(
        prompt=(
            'a seamless tileable texture of large weathered limestone ashlar blocks with recessed '
            'mortar joints, chipped corners, salt bloom and fine pitting, pale neutral grey, flat '
            'straight-on view'),
        scale=3.2),
    'cobble': dict(
        prompt=(
            'a seamless tileable texture of irregular rounded harbour cobblestones laid in soft rows, '
            'worn smooth tops, dark joints, pale neutral grey-brown, flat straight-on view'),
        scale=2.0),
    'wood': dict(
        prompt=(
            'a seamless tileable texture of old weathered timber planks, long straight grain, a few '
            'nail holes and fine splits, silvered edges, pale neutral tan-grey, flat straight-on view'),
        scale=1.5),
    'canvas': dict(
        prompt=(
            'a seamless tileable texture of cream canvas sailcloth, clearly visible even weave, soft '
            'creases, faint salt stains and a few small patches, neutral off-white, flat straight-on view'),
        scale=2.2),
    'iron': dict(
        prompt=(
            'a seamless tileable texture of dark forged iron, fine hammer marks and sand-cast pitting, '
            'soft rust-brown patches in the recesses, neutral mid-grey, flat straight-on view'),
        scale=1.0),
    'foliage': dict(
        prompt=(
            'a seamless tileable texture of dense overlapping tropical leaves, small branches and '
            'leaf veins, varied greens with sunlit and shaded clumps, soft painterly edges, flat '
            'straight-on view'),
        scale=3.0),
    'water': dict(
        prompt=(
            'a seamless tileable texture seen straight down of sunlit turquoise sea water, gentle '
            'ripples, soft caustic highlights and tiny white foam flecks, hand-painted, no horizon, '
            'no land, flat even view'),
        scale=26.0),
    'cliff': dict(
        prompt=(
            'a seamless tileable texture of a natural sea cliff face, stratified weathered stone '
            'with vertical fissures, broken ledges, orange and grey mineral bands, dark crevices, '
            'small salt-bleached patches and sparse moss in the cracks, painterly but readable rock '
            'structure, neutral mid-tone that can be tinted, flat straight-on view'),
        scale=9.0),
    'sand': dict(
        prompt=(
            'a seamless tileable texture seen straight down of a sunlit tropical beach, fine pale '
            'sand with gentle ripple marks, scattered tiny shells and dark wet pebbles, soft painterly '
            'grain, neutral pale tone that can be tinted, flat even view'),
        scale=4.5),
}

# material key -> (base surface, metres per tile)
MATERIAL_SURFACE = {
    'plaster': ('plaster', 2.8), 'cream': ('plaster', 2.8), 'ochre': ('plaster', 2.8),
    'coral': ('plaster', 2.8), 'sage_wall': ('plaster', 2.8), 'teal_wall': ('plaster', 2.8),
    'azure_wall': ('plaster', 2.8), 'lime_wall': ('plaster', 2.8),
    'roof_terra': ('roof', 1.9), 'roof_terra_light': ('roof', 1.9), 'roof_teal': ('roof', 1.9),
    'roof_slate': ('roof', 1.9), 'roof_straw': ('roof', 1.4),
    'stone': ('stone', 3.2), 'stone_light': ('stone', 3.2), 'stone_dark': ('stone', 3.2),
    'cobble': ('cobble', 2.0), 'cobble_dark': ('cobble', 2.0),
    'wood': ('wood', 1.5), 'wood_dark': ('wood', 1.5), 'wood_light': ('wood', 1.5),
    'sail': ('canvas', 2.2), 'canvas': ('canvas', 2.2), 'canvas_red': ('canvas', 2.2),
    'sail_dark': ('canvas', 2.2),
    'canvas_teal': ('canvas', 2.2),
    'metal': ('iron', 1.0), 'gold': ('iron', 1.0),
    'water': ('water', 26.0), 'water_shallow': ('water', 18.0), 'water_mid': ('water', 22.0),
    'rock': ('cliff', 9.0), 'rock_light': ('cliff', 9.0), 'rock_dark': ('cliff', 9.0),
    'sand': ('sand', 4.5),
    'jungle': ('foliage', 3.0), 'jungle_light': ('foliage', 3.0), 'jungle_dark': ('foliage', 3.0),
    'palm': ('foliage', 3.0), 'palm_light': ('foliage', 3.0),
    'autumn_rust': ('foliage', 3.0), 'autumn_gold': ('foliage', 3.0),
    'autumn_olive': ('foliage', 3.0),
}

