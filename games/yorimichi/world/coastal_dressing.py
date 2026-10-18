"""Rock groups and backshore groves, using the island's existing asset library."""
import numpy as np

import shorelines as coast
import coastal_surface
from skatepark.pier_site import ORIGIN, HALF_X, HALF_Y
from belmonte.terrain import OUTER as TOWN_JOIN_BOUNDS


def clear_footprint(x, y, radius):
    """@cc [owner:fontanierh,label:correctness] coastal-feature-clearance
    Coastal dressing MUST stay outside the protected occupied ground, railway
    cover, working harbor and Sunset Pier, including each feature's footprint.
    It MUST leave the separate temple islet and its crossing unchanged.
    """
    x, y, radius = np.broadcast_arrays(x, y, radius)
    safe = y-radius > -300.
    x0, y0, x1, y1 = coast.HARBOR_RECT
    safe &= (x+radius < x0) | (x-radius > x1) | (y+radius < y0) | (y-radius > y1)
    safe &= (abs(x-ORIGIN[0]) > HALF_X+radius+6.) | (abs(y-ORIGIN[1]) > HALF_Y+radius+6.)
    safe &= (x+radius < -550.) | (x-radius > 1650.) | (y+radius < -125.) | (y-radius > 500.)
    for box in coast._rail_headlands():
        safe &= coast._headland_distance(x, y, box) > radius+80.
    # The new local reach approaches the town collar and previously inland rail.
    # The Belmonte producer already plants the actual collar triangles. Leave
    # that region to its owner instead of sampling it as unconstrained country.
    tx0, ty0, tx1, ty1 = TOWN_JOIN_BOUNDS
    safe &= (x+radius < tx0) | (x-radius > tx1) | (y+radius < ty0) | (y-radius > ty1)
    safe &= coast.rail_cover_distance(x, y, maximum=100.+float(np.max(radius, initial=0.))) > radius+80.
    # A circumscribed square also keeps every edge inside an authored scenery region.
    for dx in [-1., 0., 1.]:
        for dy in [-1., 0., 1.]:
            px, py = x+dx*radius, y+dy*radius
            perimeter = coast._profile_perimeter_weight(px, py)
            old = (perimeter > .02) & (coast._profile_weight(px, py) >= perimeter*(1.-1e-6))
            safe &= old | (coast.landform_envelope(px, py) > .02)
    return safe


def landform_groves(x, y):
    """Groves follow the named ridges and rail foothill, leaving explicit valley mouths open."""
    country, headland = coast.landform_regions(x, y)
    clump = .5+.3*np.sin(x/71.+y/93.)+.2*np.sin(y/49.-x/63.)
    ridge = np.zeros_like(x)
    for c in coast.COUNTRY_RIDGES:
        axis = c['y']+c['lean']*(x-2400.)
        ridge = np.maximum(ridge, np.exp(-((y-axis)/210.)**4))
    distance = coast.rail_cover_distance(x, y, maximum=460.)
    rail_foot = coast.smooth((distance-80.)/80.)*(1.-coast.smooth((distance-260.)/200.))
    return np.maximum(country*np.maximum(ridge, rail_foot), headland)*np.clip((clump-.25)/.65, 0., 1.)


def placements(ground):
    """Deterministic coastal objects; ground is the final world-space sampler.

    Keep separate random streams from the established inland forest so a new
    cove cannot move an unrelated tree, house, path or gameplay placement.
    """
    rng = np.random.default_rng(83047)
    result = {}

    def put(name, x, y, z, scale):
        result.setdefault(str(name), []).append([round(float(x), 2), round(float(y), 2),
                                           round(float(z), 2), round(float(rng.uniform(0., 360.)), 1),
                                           round(float(scale), 3)])

    x, y = np.meshgrid(np.arange(-3130., 3131., 18.), np.arange(-230., 7001., 18.))
    x, y = x.ravel(), y.ravel()
    x += rng.uniform(-5., 5., len(x)); y += rng.uniform(-5., 5., len(y))
    d, rock = coast.field(x, y)
    scale = rng.uniform(4., 14., len(x))
    # Groups at rocky shoulders and on the first shelf. Sparse outlying slabs
    # run into the shallows; the broad sand bay centres remain open.
    groups = .5+.5*np.sin(y/73.+x/91.)
    keep = (d > -16.) & (d < 57.) & (rock > .43) & (rng.random(len(x)) < .22+.35*groups)
    keep &= clear_footprint(x, y, scale*1.8)
    x, y, scale = x[keep], y[keep], scale[keep]
    z = ground(x, y)
    names = ['SW_Boulder_A', 'SW_Boulder_B', 'SW_Boulder_C']
    for i, (xx, yy, zz, size) in enumerate(zip(x, y, z, scale)):
        if -9. < zz < 65.:
            put(names[i % len(names)], xx, yy, zz+size*.20, size)

    # Full-cell jitter and a two-dimensional clump field leave open meadows
    # between groves. The inland edge follows the rolling country transition,
    # not a constant-distance row parallel to the beach.
    x, y = np.meshgrid(np.arange(-3050., 3051., 17.), np.arange(-210., 6971., 17.))
    x, y = x.ravel(), y.ravel()
    x += rng.uniform(-8.5, 8.5, len(x)); y += rng.uniform(-8.5, 8.5, len(y))
    d, rock = coast.field(x, y)
    grove = (.52*np.sin(y/89.+x/97.)+.31*np.cos(y/63.-x/131.)
             +.17*np.sin(y/157.+x/57.))
    front = 88.-18.*rock+24.*np.sin(y/103.+x/67.)
    back = np.minimum(coast.reach(x, y)-45., 160.+.62*coast.reach(x, y)+75.*grove)
    keep = (d > front) & (d < back) & (grove > .30)
    local_grove = landform_groves(x, y)
    keep |= (d > front) & (d < coast.reach(x, y)-45.) & (local_grove > .25)
    chance = np.maximum(.35+.5*np.clip(grove, 0., 1.), .35+.5*local_grove)
    keep &= rng.random(len(x)) < chance
    keep &= clear_footprint(x, y, 13.)
    x, y = x[keep], y[keep]
    z = ground(x, y)
    slope = np.hypot((ground(x+2., y)-ground(x-2., y))/4.,
                     (ground(x, y+2.)-ground(x, y-2.))/4.)
    keep = (z > 3.) & (slope < .48)
    x, y, z = x[keep], y[keep], z[keep]
    species = ['Tree_Pine_B', 'Tree_Maple_A', 'Tree_Ginkgo', 'Tree_Cedar_B']
    for xx, yy, zz in zip(x, y, z):
        name = rng.choice(species, p=[.35, .34, .19, .12])
        put(name, xx, yy, zz-.45, rng.uniform(1.55, 2.3))
        if rng.random() < .45:
            put('Bush_Ochre_A', xx, yy, zz-.12, rng.uniform(1.2, 2.))
    shape_crowns(result)
    return result


def shape_crowns(objects):
    """@cc [owner:fontanierh,label:correctness] coastal-crown-producer-isolation
    Only this producer's headland crown trees may be reduced. Preserve all
    outside transforms and all random draws, and never filter another owner's trees.
    """
    for name,rows in objects.items():
        if not rows or not name.startswith('Tree_'):continue
        p=np.asarray(rows,float)
        on=coastal_surface.crown_zone(p[:,0],p[:,1],p[:,2])
        # Finish the original RNG stream first. This spatial postfilter cannot
        # reshuffle later trees, shrubs, or objects outside the crown masses.
        gaps=.5+.5*np.sin(p[:,0]/41.+p[:,1]/29.)
        keep=~on | (gaps > .3)
        objects[name]=[[*row[:4],round(row[4]*.55,3)] if selected else row
                       for row,selected,k in zip(rows,on,keep) if k]


def shoulder_sites():
    """@cc [owner:fontanierh,label:correctness] connected-coastal-shoulders
    Small interlocking source rocks may occupy these five existing shoulders
    only after full-footprint clearance. Preserve pier, arrival, harbor, islet,
    town and rail exclusions; do not consume the established dressing RNG.
    """
    centres=[]
    for x in [-255.,245.]:
        lo,hi=-300.,-100.
        for _ in range(30):
            mid=(lo+hi)/2.
            if coast.field(x,mid)[0]>0.:hi=mid
            else:lo=mid
        centres.append((x,(lo+hi)/2.,1.,0.,0.,1.,0.))
    for y in [4380.,5250.,6210.]:
        lo,hi=2000.,3200.
        for _ in range(30):
            mid=(lo+hi)/2.
            if coast.field(mid,y)[0]>0.:lo=mid
            else:hi=mid
        centres.append(((lo+hi)/2.,y,0.,1.,-1.,0.,90.))
    result=[]
    pattern=[(t,n) for n in [-1.,6.] for t in [-16.,-10.,-4.,3.,10.,16.]]+[(t,12.) for t in [-10.,0.,10.]]
    for ci,(cx,cy,tx,ty,nx,ny,angle) in enumerate(centres):
        for i,(t,n) in enumerate(pattern):
            size=round(float(4.1+.9*np.sin(i*1.7+ci*.8)+.35*np.cos(i*2.1)),3)
            x,y=round(cx+tx*t+nx*n,2),round(cy+ty*t+ny*n,2)
            # This radius exceeds both source meshes and their collider bounds.
            if not bool(clear_footprint(x,y,size*3.)):continue
            asset='SW_Boulder_A' if i%3 else 'SW_Boulder_B'
            yaw=round(float(angle+14.*np.sin(i*2.3+ci)),1)
            result.append((asset,x,y,size,yaw))
    return result


def append_shoulders(objects, ground):
    """Append small embedded groups after the original producer's random draws."""
    sites=shoulder_sites()
    x,y=np.asarray([(r[1],r[2]) for r in sites],float).T
    z=ground(x,y)
    assert np.isfinite(z).all(),'Missing triangle support for coastal shoulder'
    for (name,x,y,size,yaw),height in zip(sites,z):
        objects.setdefault(name,[]).append([x,y,round(float(height+size*.2),3),yaw,size])


def integrate(world, heightmap):
    from hidamari import layout
    from belmonte import terrain
    from train import earthworks
    from train.corridor import clear_instances
    # The world generator has just written this final grid. Keep the public
    # sampler on that same grid while locating the new coastal features.
    layout.H = heightmap
    # The city's street profile starts where this world's road ends. world.json is written only after this
    # step, so a fresh build has none to read yet, and an incremental one would read the previous road.
    layout.street_height.start = max(world['road'], key=lambda q: q[0])[:2]
    n = len(heightmap)

    def ground(x, y):
        x, y = np.broadcast_arrays(np.asarray(x, float), np.asarray(y, float))
        # Match the source triangles used by the coastal mesh refinement,
        # rather than bilinearly smoothing the coarse backdrop's diagonal.
        out = layout.coastal_backdrop_height(x, y, terrain.old_height(x, np.minimum(y, 3200.)))
        north = y > 3200.
        out[north] = terrain.country_height(x[north], y[north], carved=False)
        out = earthworks.carve(x, y, out)
        fine = (abs(x) <= 300.) & (abs(y) <= 300.)
        fx = np.clip((x[fine]+300.)/600.*(n-1), 0., n-1.000001)
        fy = np.clip((y[fine]+300.)/600.*(n-1), 0., n-1.000001)
        i, j = fx.astype(int), fy.astype(int); u, v = fx-i, fy-j
        a, b = heightmap[j, i], heightmap[j, i+1]
        c, d = heightmap[j+1, i+1], heightmap[j+1, i]
        out[fine] = np.where(u >= v, a+u*(b-a)+v*(c-b), a+u*(c-d)+v*(d-a))
        city = (x > 300.) & (x <= 1420.) & (y >= -300.) & (y <= 500.)
        out[city] = layout.height(x[city], y[city])
        return out

    def shoulder_ground(x,y):
        out=ground(x,y)
        north=y>3200.
        # The country exporter refines its source cells before carving. New
        # shoulders use those triangles rather than the nonlinear query height.
        def shape(qx,qy,base):
            return earthworks.carve(qx,qy,coast.height(qx,qy,base))
        if north.any():
            out[north]=coast.sample_grid_mesh(*terrain.country_grid(),x[north],y[north],shape=shape)
        fine=~north
        # Fine beach quads are not planar. Embed new rocks below either
        # possible export diagonal, without changing the ground or old dressing.
        fx=np.clip((x[fine]+300.)/600.*(n-1),0.,n-1.000001)
        fy=np.clip((y[fine]+300.)/600.*(n-1),0.,n-1.000001)
        i,j=fx.astype(int),fy.astype(int);u,v=fx-i,fy-j
        a,b,c,d=heightmap[j,i],heightmap[j,i+1],heightmap[j+1,i+1],heightmap[j+1,i]
        out[fine]=shoulder_quad_floor(a,b,c,d,u,v)
        return out

    objects = placements(ground)
    append_shoulders(objects,shoulder_ground)
    clear_instances(objects)
    for name, rows in objects.items():
        world['instances'].setdefault(name, []).extend(rows)
    counts = {name: len(rows) for name, rows in objects.items()}
    world['coastal_dressing'] = counts
    print('COASTAL FEATURES', counts, flush=True)


def shoulder_quad_floor(a,b,c,d,u,v):
    """Conservative contact height beneath either triangulation of a beach quad."""
    ac=np.where(u>=v,a+u*(b-a)+v*(c-b),a+u*(c-d)+v*(d-a))
    bd=np.where(u+v<=1.,a+u*(b-a)+v*(d-a),c+(1.-u)*(d-c)+(1.-v)*(b-c))
    return np.minimum(ac,bd)
