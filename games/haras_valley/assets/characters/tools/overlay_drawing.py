"""overlay.py base.png cleanup.json out.png: the face sheet's lines over a front render (camera centre -0.0031, 0.352, 0.2 m frame, 1200 px)."""
import json, sys
import numpy as np; from PIL import Image
base_path, record_path, out = sys.argv[1:4]
base=Image.open(base_path).convert("RGB"); W=1200; ppm=W/0.2; cy,cz=-0.0031,0.352
pupils=json.load(open(record_path))['eyes']['pupils']
P=[(600+(y-cy)*ppm, 600-(z-cz)*ppm) for y,z in pupils]
L,R=np.array(P[0]),np.array(P[1])
sheet=np.asarray(Image.open("games/haras_valley/assets/characters/boy/references/face-six-views.png").convert("RGB")).astype(float)/255
cell=sheet[0:512,0:512]; sl=cell@[.299,.587,.114]
dL,dR=np.array([242.3,235.9]),np.array([334.9,235.8])
k=(R[0]-L[0])/(dR[0]-dL[0]); mid_m=(L+R)/2; mid_d=(dL+dR)/2
over=np.asarray(base).copy(); ys,xs=np.nonzero(sl<.33)
X=((xs-mid_d[0])*k+mid_m[0]).astype(int); Y=((ys-mid_d[1])*k+mid_m[1]).astype(int); ok=(X>=0)&(X<W-1)&(Y>=0)&(Y<W-1)
for dx in (0,1):
    for dy in (0,1): over[Y[ok]+dy,X[ok]+dx]=[230,20,20]
Image.fromarray(over).save(out); print('pupils px',np.round(L,1),np.round(R,1),'scale',round(k,3))
