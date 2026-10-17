// The artwork, pins and player share one cartographic projection and one view transform.
const $=id=>document.getElementById(id);
function project(v,knots){
 if(!knots?.length)return v;
 if(v<=knots[0][0])return knots[0][1];
 for(let i=1;i<knots.length;i++)if(v<=knots[i][0]){const a=knots[i-1],b=knots[i];return a[1]+(b[1]-a[1])*(v-a[0])/(b[0]-a[0]);}
 return knots.at(-1)[1];
}
export function createMap({send,onTravel}){
 let data=null,state=null,imageSource='',scale=1,offset={x:0,y:0},base={w:1,h:1},initialized=false,gesture=null,suppressClick=false,region=null,stable=null;
 const touches=new Map();
 const dialog=$('map-dialog'),layout=$('map-layout'),frame=$('map-frame'),canvas=$('map-canvas'),img=$('map-image'),pins=$('map-pins'),list=$('map-zones'),player=$('map-player'),status=$('map-status');
 const frames=()=>data?.atlas?[data.atlas.world,...data.atlas.regions]:[];
 function frameData(){return frames().find(f=>f.key===region)||data;}
 function pct(x,y){const f=frameData(),[x0,y0,x1,y1]=f.bounds;return [((data.atlas?x:project(x,data.projection_x))-x0)/(x1-x0)*100,(y1-(data.atlas?y:project(y,data.projection_y)))/(y1-y0)*100];}
 function contains(p,x,y){let inside=false;for(let i=0,j=p.length-1;i<p.length;j=i++){const a=p[j],b=p[i],d=[b[0]-a[0],b[1]-a[1]];if(Math.abs((x-a[0])*d[1]-(y-a[1])*d[0])<1e-6&&x>=Math.min(a[0],b[0])&&x<=Math.max(a[0],b[0])&&y>=Math.min(a[1],b[1])&&y<=Math.max(a[1],b[1]))return true;if((a[1]>y)!==(b[1]>y)&&x<a[0]+(y-a[1])*d[0]/d[1])inside=!inside;}return inside;}
 function regionAt(x,y){for(const f of data?.atlas?.regions||[]){const b=f.bounds;if(x>=b[0]&&x<=b[2]&&y>=b[1]&&y<=b[3]&&contains(f.polygon,x,y))return f.key;}return 'world';}
 function currentRegion(){return state&&typeof state.x==='number'?regionAt(state.x/100,-state.y/100):data?.current_region||'world';}
 function choose(key){region=key;initialized=true;stable=null;$('map-stable-editor').hidden=true;$('map-search').value='';scale=1;offset={x:0,y:0};render();whole();}
 function apply(){
  const w=frame.clientWidth,h=frame.clientHeight,sw=base.w*scale,sh=base.h*scale;
  offset.x=sw<w?(w-sw)/2:Math.max(w-sw,Math.min(0,offset.x));
  offset.y=sh<h?(h-sh)/2:Math.max(h-sh,Math.min(0,offset.y));
  canvas.style.width=base.w+'px';canvas.style.height=base.h+'px';
  canvas.style.transform=`translate(${offset.x}px,${offset.y}px) scale(${scale})`;
  canvas.style.setProperty('--pin-scale',1/scale);
  frame.dataset.zoom=scale.toFixed(3);
  arrangeRegionCaptions(w,h);
 }
 function arrangeRegionCaptions(w,h){
  if(!data?.atlas||region!=='world')return;
  const captions=[...pins.querySelectorAll('.map-region')],placed=[];
  const west=['momiji_woods','momiji_coast','temple_island'];
  for(const pin of captions){
   const u=Number(pin.dataset.u),v=Number(pin.dataset.v);pin.style.left=u+'%';pin.style.top=v+'%';
   if(base.w*scale<500&&!$('map-search').value.trim()){
    const pw=pin.offsetWidth,ph=pin.offsetHeight,gap=ph+6,index=west.indexOf(pin.dataset.key);
    let x=offset.x+u/100*base.w*scale,y=offset.y+v/100*base.h*scale;
    if(index>=0){x=pw/2+8;y=Math.min(y,h-(west.length-index-.5)*gap-8);}
    if(pin.dataset.key==='hidamari'){x=w-pw/2-8;y=Math.min(y,h-gap*1.5-8);}
    let best=null;
    for(const cx of [x,w/2,pw/2+8,w-pw/2-8])for(let shift=-7;shift<=7;shift++){
     const px=Math.max(pw/2+4,Math.min(w-pw/2-4,cx)),py=Math.max(ph/2+4,Math.min(h-ph/2-4,y+shift*gap));
     const r={l:px-pw/2-3,r:px+pw/2+3,t:py-ph/2-3,b:py+ph/2+3};
     if(placed.some(a=>r.l<a.r&&r.r>a.l&&r.t<a.b&&r.b>a.t))continue;
     const cost=Math.abs(py-y)+Math.abs(px-x)*.5;
     if(!best||cost<best.cost)best={px,py,r,cost};
    }
    if(best){placed.push(best.r);pin.style.left=(best.px-offset.x)/(base.w*scale)*100+'%';pin.style.top=(best.py-offset.y)/(base.h*scale)*100+'%';}
   }
   const line=pins.querySelector(`svg[data-region="${pin.dataset.key}"] line`);
   if(line){line.setAttribute('x2',parseFloat(pin.style.left));line.setAttribute('y2',parseFloat(pin.style.top));}
  }
 }
 function whole(){scale=1;offset={x:0,y:0};apply();}
 function focus(){
  if(!data)return;
  if(data.atlas&&region!==currentRegion()){choose(currentRegion());}
  const z=data.zones.find(z=>z.key==='spawn')||data.zones[0];
  const [u,v]=state&&typeof state.x==='number'?pct(state.x/100,-state.y/100):pct(z.x,z.y);
  scale=1.7;offset={x:frame.clientWidth/2-u/100*base.w*scale,y:frame.clientHeight/2-v/100*base.h*scale};apply();
 }
 function fit(){
  const box=layout.getBoundingClientRect(),portrait=matchMedia('(orientation: portrait)').matches;
  const w=portrait?box.width:Math.max(100,box.width-($('map-sidebar').getBoundingClientRect().width||200)-12);
  const h=portrait?Math.max(120,box.height*.57):box.height;
  frame.style.width=Math.floor(w)+'px';frame.style.height=Math.floor(h)+'px';
  const b=frameData()?.bounds,aspect=b?(b[2]-b[0])/(b[3]-b[1]):1.5;
  base={w:Math.min(w,h*aspect),h:Math.min(h,w/aspect)};apply();
 }
 function zoom(factor,point={x:frame.clientWidth/2,y:frame.clientHeight/2}){
  const next=Math.max(1,Math.min(6,scale*factor)),ratio=next/scale;
  offset={x:point.x-(point.x-offset.x)*ratio,y:point.y-(point.y-offset.y)*ratio};scale=next;apply();
 }
 function render(){
  if(!data)return;
  if(data.atlas&&region===null)region=currentRegion();
  const f=frameData(),source=data.atlas?'/map/'+f.image:data.image;
  if(imageSource!==source){imageSource=source;img.src=source;}
  $('map-title').textContent=data.atlas?f.name:'The World';
  $('map-back').hidden=!data.atlas||region==='world';
  pins.replaceChildren();list.replaceChildren();
  const query=$('map-search').value.trim().toLowerCase();
  function row(z,index,type='zone'){
   const match=!query||z.name.toLowerCase().includes(query);if(!match)return;
   const [l,t]=pct(z.x,z.y),pin=document.createElement('button');
   const action=()=>{if(suppressClick)return;if(type==='region')choose(z.key);else if(type==='stable'){stable=z;$('map-stable-name').value=z.name;$('map-stable-editor').hidden=false;$('map-stable-name').focus();}else travel(z);};
   pin.className='map-pin '+(type==='region'?'map-region':type==='stable'?'map-estate':'');pin.dataset.key=z.key;pin.style.left=l+'%';pin.style.top=t+'%';pin.textContent=type==='region'?z.name:type==='stable'?'◇':z.key.startsWith('marker_')?'M':index+1;pin.setAttribute('aria-label',(type==='region'?'Open ':type==='stable'?'Rename ':'Travel to ')+z.name);pin.onclick=action;
   if(type==='region'){pin.dataset.u=l;pin.dataset.v=t;}
   if(type!=='region'){const name=document.createElement('span');name.className='map-pin-label';name.textContent=z.name;pin.append(name);}
   if(l>=0&&l<=100&&t>=0&&t<=100&&(region!=='world'||type==='region'||z.region==='world'||query))pins.append(pin);
   const li=document.createElement('li'),button=document.createElement('button');button.dataset.key=z.key;
   const n=document.createElement('b');n.textContent=type==='region'?'›':type==='stable'?'◇':index+1;
   const name=document.createElement('span');name.textContent=z.name;
   const hint=document.createElement('small');hint.textContent=type==='region'?'Open region':type==='stable'?'Select to rename':z.hint||'';name.append(hint);button.append(n,name);button.onclick=action;li.append(button);list.append(li);
  }
  if(data.atlas&&region==='world')data.atlas.regions.forEach((r,i)=>{
   if(query&&!r.name.toLowerCase().includes(query))return;
   const b=r.bounds,c=[(b[0]+b[2])/2,(b[1]+b[3])/2],p=r.label||c;
   {const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg'),line=document.createElementNS(ns,'line'),a=pct(...c),z=pct(...p);svg.dataset.region=r.key;svg.classList.add('map-region-link');svg.setAttribute('viewBox','0 0 100 100');svg.setAttribute('preserveAspectRatio','none');for(const [key,v]of Object.entries({x1:a[0],y1:a[1],x2:z[0],y2:z[1],stroke:'#d4b774','stroke-width':.15}))line.setAttribute(key,v);svg.append(line);pins.append(svg);}
   row({...r,x:p[0],y:p[1]},i,'region');
  });
  data.zones.forEach((z,i)=>{if(!data.atlas||region==='world'||query||z.region===region)row(z,i);});
  if(data.atlas&&(region!=='world'||query))(data.atlas.landmarks||[]).forEach((z,i)=>{if(z.region===region||query)row(z,i,'stable');});
  status.textContent=data.atlas?.error||(data.atlas?'Select a destination to travel. Drag or pinch to explore.':'Drag or pinch to explore. Tap a place to travel.');fit();
  if(!initialized){if(data.atlas)whole();else focus();initialized=true;}update(state);
 }
 function update(s){
  state=s;if(!data||!s||typeof s.x!=='number'){player.hidden=true;return;}
  const [l,t]=pct(s.x/100,-s.y/100);player.hidden=l<0||l>100||t<0||t>100;player.style.left=l+'%';player.style.top=t+'%';player.style.setProperty('--heading',`${s.yaw||0}deg`);
 }
 function travel(z){status.textContent=`Travelling to ${z.name}…`;send({action:'teleport',zone:z.key});dialog.close();onTravel?.(z);}
 function local(e){const b=frame.getBoundingClientRect();return {x:e.clientX-b.x,y:e.clientY-b.y};}
 function startGesture(){
  const p=[...touches.values()];
  gesture=p.length>=2?{pinch:true,distance:Math.hypot(p[1].x-p[0].x,p[1].y-p[0].y),center:{x:(p[0].x+p[1].x)/2,y:(p[0].y+p[1].y)/2}}:{point:p[0],start:p[0],moved:false};
 }
 frame.addEventListener('pointerdown',e=>{touches.set(e.pointerId,local(e));startGesture();if(touches.size>1){suppressClick=true;frame.setPointerCapture(e.pointerId);}});
 frame.addEventListener('pointermove',e=>{
  if(!touches.has(e.pointerId)||!gesture)return;
  touches.set(e.pointerId,local(e));const p=[...touches.values()];
  if(p.length>=2){
   const center={x:(p[0].x+p[1].x)/2,y:(p[0].y+p[1].y)/2},distance=Math.hypot(p[1].x-p[0].x,p[1].y-p[0].y);
   if(!gesture.pinch){startGesture();return;}
   zoom(distance/Math.max(1,gesture.distance),gesture.center);offset.x+=center.x-gesture.center.x;offset.y+=center.y-gesture.center.y;apply();gesture={pinch:true,distance,center};
  }else{
   const q=p[0];if(gesture.pinch){startGesture();return;}
   if(Math.hypot(q.x-gesture.start.x,q.y-gesture.start.y)>5){gesture.moved=true;suppressClick=true;frame.setPointerCapture(e.pointerId);}
   if(gesture.moved){offset.x+=q.x-gesture.point.x;offset.y+=q.y-gesture.point.y;apply();}
   gesture.point=q;
  }
 });
 function end(e){touches.delete(e.pointerId);if(touches.size)startGesture();else{gesture=null;setTimeout(()=>suppressClick=false,100);}}
 frame.addEventListener('pointerup',end);frame.addEventListener('pointercancel',end);
 frame.addEventListener('click',e=>{if(suppressClick){e.preventDefault();e.stopPropagation();}},true);
 frame.addEventListener('wheel',e=>{e.preventDefault();zoom(Math.exp(-e.deltaY*.002),local(e));},{passive:false});
 $('map-plus').onclick=()=>zoom(1.4);$('map-minus').onclick=()=>zoom(1/1.4);$('map-you').onclick=focus;$('map-whole').onclick=whole;
 img.onload=()=>{fit();if(!data?.atlas&&initialized)focus();};
 $('map-back').onclick=()=>choose('world');$('map-search').oninput=render;
 $('map-stable-editor').onsubmit=e=>{e.preventDefault();if(stable)send({action:'renameStable',key:stable.key,name:$('map-stable-name').value});};
 addEventListener('resize',()=>{if(dialog.open)fit();});
 return {open(connected){dialog.showModal();fit();if(!connected){status.textContent='Connect to the game to load the map';return;}if(data){if(data.atlas)choose(currentRegion());else{region=null;render();focus();}}else{status.textContent='Loading the map…';}send({action:'map'});},receive(msg){data=msg;if(dialog.open)render();},update,get data(){return data;}};
}
