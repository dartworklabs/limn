// Closes one document - PDFDocumentProxy has no destroy of its own; loadingTask frees the worker-side resources too.
function vecClose(doc){if(!doc)return; try{doc.loadingTask.destroy();}catch(e){}}
function vecFail(msg,err){
  VEC.failed=msg; VEC.gen++; vecCancel(); vecReleaseAll();
  vecForget(VEC.doc); vecClose(VEC.doc); VEC.doc=null;
  const c=$('#vec-chip'); c.hidden=false;
  c.dataset.tip=tl('PDF를 벡터로 그리지 못해 이미지(PNG)로 보입니다 — {reason}. 확대하면 흐릴 수 있습니다',{reason:tr(msg)+(err&&err.message?' ('+String(err.message).slice(0,100)+')':'')});
}
function vecState(n){let s=VEC.st.get(n); if(!s){s={base:null,bw:0,bh:0,dt:null,reg:null,dtCw:0,dtK:0,stale:false}; VEC.st.set(n,s);} return s;}
function vecDrop(cv){if(!cv)return; cv.width=0; cv.height=0; cv.remove();}   // must shrink to 0 for Safari to release memory right away too
function vecRelease(n){if(VEC.cur&&VEC.cur.n===n)vecCancel(); const s=VEC.st.get(n); if(!s)return;
  vecDrop(s.base); vecDrop(s.dt); VEC.st.delete(n);
  const pg=document.getElementById('p'+n); if(pg)pg.classList.remove('drawn');}
function vecReleaseAll(){vecCancel(); Array.from(VEC.st.keys()).forEach(vecRelease);}
function vecCancel(){const c=VEC.cur; VEC.cur=null; if(c&&c.task){try{c.task.cancel();}catch(e){}}}
function vecObserve(){if(VEC.io)VEC.io.disconnect(); vecReleaseAll(); VEC.near.clear(); if(!window.IntersectionObserver)return;
  VEC.io=new IntersectionObserver(es=>{es.forEach(en=>{const n=+en.target.dataset.page;
      if(en.isIntersecting)VEC.near.add(n); else {VEC.near.delete(n); vecRelease(n);}}); vecSchedule(0);},
    {root:$('#left'),rootMargin:VEC_KEEP});
  $$('.pg').forEach(pg=>VEC.io.observe(pg));}
function vecSchedule(ms){clearTimeout(VEC.timer); VEC.timer=setTimeout(vecPump,ms||0);}
// Zoom, window size, or DPR changed - whatever was being drawn (the old size) is discarded and redrawn shortly after. Meanwhile, the old canvas is shown stretched.
function vecInvalidate(){if(!VEC.doc)return; vecCancel(); vecSchedule(150);}
function vecK(){const vv=window.visualViewport; return (window.devicePixelRatio||1)*Math.max(1,(vv&&vv.scale)||1);}
// The page canvas's backing size. If it exceeds the cap, it's scaled down proportionally and marked capped (the detail canvas fills in the visible portion).
function vecTarget(cw,ch,k,cap){let bw=Math.round(cw*k),bh=Math.round(ch*k),capped=false;
  if(bw*bh>cap){const f=Math.sqrt(cap/(bw*bh)); bw=Math.max(1,Math.floor(bw*f)); bh=Math.max(1,Math.floor(bh*f)); capped=true;}
  return {cw,ch,k,bw,bh,capped};}
function vecTargetOf(pg){const cw=pg.clientWidth,ch=pg.clientHeight; return cw&&ch?vecTarget(cw,ch,vecK(),VEC_PIX_CAP):null;}
// The portion of a page visible on screen (page CSS px). margin is extra room relative to the viewport size (the detail canvas is drawn a bit larger).
function vecVisible(pg,margin){const L=$('#left'),lr=L.getBoundingClientRect(),r=pg.getBoundingClientRect();
  const ox=r.left+pg.clientLeft,oy=r.top+pg.clientTop,cw=pg.clientWidth,ch=pg.clientHeight;
  const vx0=lr.left+L.clientLeft,vy0=lr.top+L.clientTop,vw=L.clientWidth,vh=L.clientHeight,mx=vw*margin,my=vh*margin;
  const x0=Math.max(0,vx0-mx-ox),y0=Math.max(0,vy0-my-oy),x1=Math.min(cw,vx0+vw+mx-ox),y1=Math.min(ch,vy0+vh+my-oy);
  return x1>x0&&y1>y0?{x:x0,y:y0,w:x1-x0,h:y1-y0,cw,ch}:null;}
function vecCovers(reg,v){return !!reg&&reg.x<=v.x/v.cw+1e-6&&reg.y<=v.y/v.ch+1e-6&&
  reg.x+reg.w>=(v.x+v.w)/v.cw-1e-6&&reg.y+reg.h>=(v.y+v.h)/v.ch-1e-6;}
// The one thing to draw next: pages within the viewport first (nearest to center), page canvas before detail canvas.
function vecNextJob(){
  if(!VEC.doc)return null;
  const L=$('#left'),lr=L.getBoundingClientRect(),top=lr.top,bot=lr.top+L.clientHeight,cy=(top+bot)/2;
  const list=[];
  VEC.near.forEach(n=>{const pg=document.getElementById('p'+n); if(!pg)return; const r=pg.getBoundingClientRect();
    list.push({n,pg,vis:r.bottom>top&&r.top<bot,d:Math.abs((r.top+r.bottom)/2-cy)});});
  list.sort((a,b)=>(b.vis-a.vis)||(a.d-b.d));
  for(const it of list){const s=vecState(it.n),t=vecTargetOf(it.pg); if(!t)continue;
    if(!s.base||s.stale||s.bw!==t.bw||s.bh!==t.bh)return {n:it.n,kind:'base'};
    if(t.capped&&it.vis){const v=vecVisible(it.pg,0);
      if(v&&(!s.dt||s.dtCw!==t.cw||s.dtK!==t.k||!vecCovers(s.reg,v)))return {n:it.n,kind:'dt'};}
    else if(s.dt){vecDrop(s.dt); s.dt=null; s.reg=null;}}
  return null;
}
async function vecPump(){
  if(VEC.pumping||!VEC.doc)return; VEC.pumping=true;
  try{for(let i=0;i<400;i++){const job=vecNextJob(); if(!job)break; await vecRun(job);}}
  finally{VEC.pumping=false;}
}
async function vecRun(job){
  const n=job.n,pg=document.getElementById('p'+n),doc=VEC.doc,gen=VEC.gen; if(!pg||!doc)return;
  if(n>doc.numPages)return;   // a defensive check - just skips a case where another document/build's doc ends up running on a new n (the vecOpen bailout above is the real fix)
  let page; try{page=await doc.getPage(n);}catch(e){if(gen===VEC.gen)vecFail('쪽을 읽지 못했습니다',e); return;}
  if(gen!==VEC.gen||!VEC.near.has(n)||!document.contains(pg))return;
  const t=vecTargetOf(pg); if(!t)return;
  const vp1=page.getViewport({scale:1}),cv=document.createElement('canvas'); let scale,tf,reg=null;
  // Width and height are fit independently (the transform's vertical scale) - the page box's aspect ratio comes from
  // the PNG pixel dimensions and differs from the PDF page's aspect ratio by less than 0.1%. Since PNG was also drawn
  // filling that same box, this is needed for the canvas's text to land at the same % position it did for PNG.
  if(job.kind==='base'){cv.width=t.bw; cv.height=t.bh; scale=t.bw/vp1.width; tf=[1,0,0,t.bh/(vp1.height*scale),0,0];}
  else{const v=vecVisible(pg,VEC_DT_MARGIN); if(!v)return; let k=t.k;
    if(v.w*v.h*k*k>VEC_PIX_CAP)k=Math.sqrt(VEC_PIX_CAP/(v.w*v.h));
    scale=t.cw*k/vp1.width; cv.width=Math.max(1,Math.round(v.w*k)); cv.height=Math.max(1,Math.round(v.h*k));
    tf=[1,0,0,t.ch*k/(vp1.height*scale),-v.x*k,-v.y*k];
    reg={x:v.x/t.cw,y:v.y/t.ch,w:v.w/t.cw,h:v.h/t.ch};}
  const ctx=cv.getContext('2d',{alpha:false}),t0=performance.now();
  const task=page.render({canvasContext:ctx,viewport:page.getViewport({scale}),transform:tf});
  VEC.cur={n,task};
  try{await task.promise;}
  catch(e){if(VEC.cur&&VEC.cur.task===task)VEC.cur=null; vecDrop(cv);
    if(e&&e.name==='RenderingCancelledException')return;
    if(gen===VEC.gen)vecFail('쪽을 그리지 못했습니다',e); return;}
  if(VEC.cur&&VEC.cur.task===task)VEC.cur=null;
  const t2=gen===VEC.gen&&VEC.near.has(n)&&document.contains(pg)?vecTargetOf(pg):null;
  if(!t2||t2.cw!==t.cw||t2.ch!==t.ch||t2.k!==t.k){vecDrop(cv); return;}   // zoom or window size changed while drawing
  VEC.stats.push({n,kind:job.kind,ms:Math.round(performance.now()-t0),w:cv.width,h:cv.height});
  if(VEC.stats.length>200)VEC.stats.splice(0,VEC.stats.length-200);
  const s=vecState(n);
  if(job.kind==='base'){vecDrop(s.base); s.base=cv; s.bw=t.bw; s.bh=t.bh; s.stale=false; cv.className='vb';
    pg.prepend(cv); pg.classList.add('drawn'); if(VEC.tFirst===null)VEC.tFirst=performance.now();}
  else{vecDrop(s.dt); s.dt=cv; s.reg=reg; s.dtCw=t.cw; s.dtK=t.k; cv.className='dt';
    Object.assign(cv.style,{left:reg.x*100+'%',top:reg.y*100+'%',width:reg.w*100+'%',height:reg.h*100+'%'});
    if(s.base)s.base.after(cv); else pg.prepend(cv);}
}
$('#left').addEventListener('scroll',()=>{if(VEC.doc)vecSchedule(120);},{passive:true});
// devicePixelRatio changes with browser zoom (Ctrl+wheel outside the PDF, etc.) or moving the window to a different screen - redraws at that scale.
(function watchDpr(){if(!window.matchMedia)return;
  matchMedia('(resolution: '+(window.devicePixelRatio||1)+'dppx)').addEventListener('change',()=>{vecInvalidate(); watchDpr();},{once:true});})();
if(window.visualViewport)visualViewport.addEventListener('resize',()=>{if(VEC.doc)vecSchedule(300);});

