"""Author one label-free atlas painting with an exclusive paid-call receipt.

Prepare exact plans with build_map.py --atlas-reference KEY first. Normal game
builds only validate and stage the committed paintings; they never call an API.
"""
import argparse
import hashlib
import json
from pathlib import Path

import atlas


SCENES = {
    'world': 'The complete existing landmasses and water gaps, small southern autumn settlements and temple islet, the eastern city, wooded foothills, broad snowy volcanic caldera and northern pastoral country. Keep their very different true scales and their exact outer edges.',
    'momiji_coast': 'An autumn coastal countryside: a winding road, small fishing cove, timber docks, shoreline houses and the precisely shaped concrete skate pier. Maple groves meet a turquoise sea.',
    'momiji_woods': 'Deep autumn woodland, winding footpaths, a hidden irregular lake with a cabin and jetty, a small traditional hamlet, and the two separated timber ramp sections. Dense rounded tree crowns, warm gold and moss green.',
    'hidamari': 'A compact Japanese coastal town: preserve the entire street grid, blue-grey roofs, market arcade, clock square, harbor quays, canal, temple hillside, green park and railway station. Fine, readable roof-plan detail.',
    'temple_island': 'A small rocky forested temple islet in the turquoise sea, with a sheltered landing, winding stone stair and summit shrine. Preserve the exact island outline, trail and temple roof footprint.',
    'northern_foothills': 'Wooded mountain foothills with the precisely drawn canyon skate park, winding access trails, racecourse and the lower slopes of the volcanic highlands. Small structures stay in their exact footprints.',
    'volcanic_highlands': 'A large volcanic massif with an accurately circular caldera seen vertically from above, snowy ridges, dark basalt, conifer slopes and the intricate concrete skate park on its crater floor. Preserve the exact railway alignment and every rail curve; keep sea and land exactly as the plan and mask show.',
    'brinecove': 'A sheltered pirate cove opening south onto the turquoise sea: a horseshoe harbour with timber piers and a shipyard slip, a cobbled market square, a waterfront of colourful plastered houses climbing in terraces up the hill, a watchtower on the ridge, a red-and-white lighthouse on the western headland, and a river gorge with a two-tier waterfall on the eastern headland. Tropical jungle and palms on the headlands. Preserve the exact cove outline, piers, streets and roof footprints. All water stays open sea: no ships, boats, rocks or islets anywhere outside the land of the mask; the game draws its moored galleons and sea stacks itself.',
    'haras_valley': 'Lush equestrian countryside around a terracotta-roofed river town. Preserve the exact oval racecourse, training arenas, seven estate/stable compounds, hedged pastures, river, stone bridge and curving railway. Fine olive tree crowns, honey-coloured tracks and green meadows.',
}


def prompt(key):
    return f'''Use case: stylized-concept. Asset: production fantasy RPG atlas texture.
Image 1 is the authoritative exact top-down geographical plan. Image 2, if present, is ONLY a painterly style reference; ignore all its text, layout, symbols and geography.
Paint this plan as a beautiful, richly detailed hand-painted adventure atlas, with the clarity and craft of a classic World of Warcraft regional map. Warm parchment undertones, fine ink contours, softly shaded olive forests, earth and ochre paths, delicate roof plans, turquoise water with subtle coastal depth. An elegant, cohesive painted world, not a satellite photograph.
Scene: {SCENES[key]}
STRICT CAMERA: orthographic TOP VIEW, north up, looking vertically down. No oblique view, no perspective, no horizon, no isometric buildings or mountain silhouettes. Mountain relief is shaded contour/rock texture seen directly from overhead. Circles remain circles. No camera rotation, recentering, zoom, crop or changed scale.
GEOMETRY: preserve the first image's exact frame, coastline, land/water mask, river courses, road and rail alignments, islands, building positions and landmark footprints. Keep the empty sea where shown. Paint detail within those shapes; do not invent towns, bridges, rivers, islands, roads or mountains. Rectangular tint boundaries in the plan are rendering-layer seams: blend their colours naturally while preserving contours and physical geography. The first image always overrides the style reference.
WATER SEMANTICS: only clearly saturated blue/cyan shapes in the plan are water. Muted grey/green/brown closed contour rings are DRY HILLTOPS, never lakes. White is snow or concrete, never water. Do not turn any northern contour depression or the volcanic caldera into a blue lake. Do not extend the river beyond its precise drawn course. Preserve exact roof/park geometry rather than inventing rock towers.
NO TEXT OF ANY KIND: no letters, numbers, place names, stable names, title, legend, compass rose, banners, scrolls, map pins, icons, badges, borders or UI. All names and destinations will be rendered by the game as editable live overlays. Fill the entire image with the map terrain; no decorative margins. High finish, subtle fine paper grain, crisp paths, restrained contrast, clear terrain at game UI scale.'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('key', choices=SCENES)
    parser.add_argument('--references', type=Path, required=True, help='directory containing KEY/rough.png and KEY/map.json')
    parser.add_argument('--style', type=Path)
    parser.add_argument('--coast-mask', type=Path, help='exact white-land/black-water mask, in the production frame')
    args = parser.parse_args()
    from atelier.ai.images import paint
    from atelier.env import load
    load()
    plan = args.references / args.key / 'rough.png'
    info = json.loads((plan.parent / 'map.json').read_text())
    expected = atlas.WORLD_BOUNDS if args.key == 'world' else next(r['bounds'] for r in info['atlas']['regions'] if r['key'] == args.key)
    if info['bounds'] != expected:
        raise ValueError('Prepare a reference with exactly the production frame before painting')
    inputs = [plan, *([args.coast_mask] if args.coast_mask else []), *([args.style] if args.style else [])]
    request = prompt(args.key)
    if args.coast_mask:
        request = request.replace('Image 2, if present, is ONLY a painterly style reference; ignore all its text, layout, symbols and geography.',
                                  'Image 2 is the authoritative coast mask. Image 3, if present, is ONLY a painterly style reference; ignore all its text, layout, symbols and geography.')
        request += '''\nSHORELINE CORRECTION: Image 2 is an authoritative binary terrain mask: WHITE is solid ground, BLACK is water. Match its silhouette at the exact same pixel positions; do not enlarge, shrink, recenter or rotate the island. Paint terrain only inside the white footprint. Surf is water, not extra dry ground. Every bay, headland and small rock must retain the mask outline. Keep the shore within one source pixel. If image 3 is present, it is STYLE ONLY: its enlarged shoreline is wrong and must not be copied. Preserve the path and temple positions of image 1. The binary mask overrides all artistic interpretation of the coast.\n'''
    target = atlas.ASSETS / f'{args.key}.png'
    if target.exists():
        raise FileExistsError('Preserve the existing painting and its receipt before authoring a new revision')
    print(f'PAINT {args.key}: one Sunburst high call; no automatic retry', flush=True)
    result = paint(target, request, '1536x1536' if args.key == 'world' else '1536x1024', inputs,
                   record=target.with_suffix('.json'), metadata=dict(
                       bounds=expected, labels_baked=False, geography=atlas.geography_signature(), prompt=request,
                       inputs=[dict(role='exact geography' if i == 0 else 'exact coast mask' if args.coast_mask and i == 1 else 'style only', sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                               for i, p in enumerate(inputs)]))
    print(f"DONE {args.key}: {result['output_sha256']} in {result['elapsed_seconds']}s", flush=True)


if __name__ == '__main__':
    main()
