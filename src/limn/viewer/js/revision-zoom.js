/** Comparison-only geometry and rendering; no manuscript preference writes.
 * @typedef {{el:HTMLElement,page:any,base:{width:number,height:number},canvas:HTMLCanvasElement|null,task:any}} RevisionPage
 * @typedef {{el:HTMLElement,fx:number,fy:number,x:number,y:number}} RevisionAnchor
 */
const RZ={ratio:1,fit:0,gen:0,busy:0,frame:0,repaint:false,pages:/** @type {RevisionPage[]} */([]),
  anchor:/** @type {RevisionAnchor|null} */(null),resetInput:()=>{}};

/** Clamp a requested ratio, including non-finite input, to the comparison range. */
function revisionRatio(ratio){return Number.isNaN(ratio)?1:Math.max(.5,Math.min(5,ratio));}

/** Only a ready, visible comparison PDF owns PDF zoom input. */
function revisionPdfActive(){return document.body.classList.contains('revision-open')&&REV.format===DIFF_FORMAT.PDF&&RZ.pages.length>0;}

/** Synchronize the comparison toolbar without touching manuscript controls. */
function drawRevisionZoom(){
  $('#revision-zoom').hidden=REV.format!==DIFF_FORMAT.PDF;
  const ready=revisionPdfActive();
  $('#revision-zoom-value').textContent=Math.round(RZ.ratio*100)+'%';
  $('#revision-zoom-out').disabled=!ready||RZ.ratio<=.5;
  $('#revision-zoom-in').disabled=!ready||RZ.ratio>=5;
  $('#revision-fit').disabled=!ready;
}

/** Cancel a page and release its pixel allocation on zoom, eviction or exit. */
function dropRevisionPage(item){
  if(item.task){item.task.cancel();REV_PDF.tasks.delete(item.task);item.task=null;}
  if(item.canvas){item.canvas.width=item.canvas.height=0;item.canvas.remove();item.canvas=null;}
  delete item.el.dataset.state;
}

/** Invalidate asynchronous work and retained gesture anchors for a document visit. */
function disposeRevisionZoom(){
  ++RZ.gen;RZ.resetInput();RZ.repaint=false;
  if(RZ.frame){cancelAnimationFrame(RZ.frame);RZ.frame=0;}
  RZ.pages.forEach(dropRevisionPage);RZ.pages=[];RZ.anchor=null;RZ.fit=0;
  drawRevisionZoom();
}

/** Remember the nearest page and fractional position under a viewport point. */
function revisionAnchor(x,y){
  const box=$('#revision-pdf'),br=box.getBoundingClientRect();
  x=x??br.left+box.clientWidth/2;y=y??br.top+box.clientHeight/2;
  let nearest=/** @type {HTMLElement|null} */(null),distance=Infinity;
  for(const item of RZ.pages){const r=item.el.getBoundingClientRect(),d=Math.max(r.top-y,y-r.bottom,0);
    if(d<distance){nearest=item.el;distance=d;}}
  if(!nearest)return null;
  const r=nearest.getBoundingClientRect();
  return {el:nearest,fx:(x-r.left)/r.width,fy:(y-r.top)/r.height,x:x-br.left,y:y-br.top};
}

/** Restore the same page point after layout, allowing ordinary edge clamping. */
function restoreRevisionAnchor(anchor,x,y){
  if(!anchor||!anchor.el.isConnected)return;
  const box=$('#revision-pdf'),br=box.getBoundingClientRect(),r=anchor.el.getBoundingClientRect();
  box.scrollLeft+=r.left+r.width*anchor.fx-(x??br.left+anchor.x);
  box.scrollTop+=r.top+r.height*anchor.fy-(y??br.top+anchor.y);
}

/** Resize all page boxes before restoring the anchor; redraw at the new width. */
function layoutRevisionPdf(anchor){
  if(!revisionPdfActive())return;
  const box=$('#revision-pdf'),style=getComputedStyle(box);
  const fit=box.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight);
  if(fit<=0)return;
  RZ.fit=fit;++RZ.gen;RZ.pages.forEach(dropRevisionPage);
  const width=fit*RZ.ratio,group=box.firstElementChild;
  if(group instanceof HTMLElement)group.style.width=width+'px';
  for(const item of RZ.pages){item.el.style.width=width+'px';item.el.style.height=width*item.base.height/item.base.width+'px';}
  restoreRevisionAnchor(anchor);RZ.anchor=revisionAnchor();drawRevisionZoom();scheduleRevisionPaint();
}

/** Zoom around a pointer, a touch midpoint or the viewport center. */
function revisionZoomTo(ratio,x,y,anchor){
  if(!revisionPdfActive())return;
  const point=anchor||revisionAnchor(x,y);RZ.ratio=revisionRatio(ratio);
  layoutRevisionPdf(point);
  if(anchor){restoreRevisionAnchor(anchor,x,y);RZ.anchor=revisionAnchor();}
}

/** Apply the same button step as the manuscript, or restore fit width. */
function revisionZoom(action){revisionZoomTo(action==='fit'?1:RZ.ratio*(action==='in'?ZOOM_STEP:1/ZOOM_STEP));}

/** Obtain page geometry without allocating canvases; abandon stale PDF visits. */
async function mountRevisionPdf(pdf,seq,k,id){
  const gen=RZ.gen,pages=/** @type {RevisionPage[]} */([]);
  for(let n=1;n<=pdf.numPages;n++){
    const page=await pdf.getPage(n);
    if(gen!==RZ.gen||!revisionCurrent(seq,k,id))return;
    const el=document.createElement('div');el.className='revision-page';el.dataset.page=String(n);
    el.setAttribute('aria-label',tl('비교 PDF {page}쪽',{page:n}));
    pages.push({el,page,base:page.getViewport({scale:1}),canvas:null,task:null});
  }
  const group=document.createElement('div');group.className='revision-pages';
  for(const item of pages)group.append(item.el);
  $('#revision-pdf').replaceChildren(group);RZ.pages=pages;
  layoutRevisionPdf(null);drawRevisionZoom();
  if(REV.target&&REV.target.page){pages[Math.min(REV.target.page,pages.length)-1]?.el.scrollIntoView({block:'start'});revTargetNote();}
  RZ.anchor=revisionAnchor();scheduleRevisionPaint();
}

/** Coalesce scroll/layout updates and release canvases outside a viewport margin. */
function scheduleRevisionPaint(){
  if(RZ.frame||!revisionPdfActive())return;
  RZ.frame=requestAnimationFrame(()=>{RZ.frame=0;void paintRevisionPdf();});
}

/** Render near pages serially with a pixel cap; canceled work never reports errors. */
async function paintRevisionPdf(){
  if(!revisionPdfActive())return;
  if(RZ.busy===RZ.gen){RZ.repaint=true;return;}
  RZ.repaint=false;
  const gen=RZ.gen;RZ.busy=gen;
  try{
    const box=$('#revision-pdf'),br=box.getBoundingClientRect(),margin=box.clientHeight*1.5;
    const near=RZ.pages.filter(item=>{const r=item.el.getBoundingClientRect();
      const keep=r.bottom>=br.top-margin&&r.top<=br.bottom+margin;
      if(!keep)dropRevisionPage(item);return keep;});
    near.sort((a,b)=>Math.abs(a.el.getBoundingClientRect().top-br.top)-Math.abs(b.el.getBoundingClientRect().top-br.top));
    for(const item of near){
      if(gen!==RZ.gen||!revisionPdfActive())return;
      if(item.canvas||item.el.dataset.state==='error')continue;
      const r=item.el.getBoundingClientRect();
      if(r.bottom<br.top-margin||r.top>br.bottom+margin)continue;
      const canvas=document.createElement('canvas'),width=item.el.clientWidth,height=item.el.clientHeight;
      const target=vecTarget(width,height,Math.min(2,devicePixelRatio||1),VEC_PIX_CAP);
      canvas.width=target.bw;canvas.height=target.bh;item.canvas=canvas;item.el.append(canvas);item.el.dataset.state='loading';
      const viewport=item.page.getViewport({scale:width/item.base.width});
      const task=item.page.render({canvasContext:canvas.getContext('2d'),viewport,
        transform:[target.bw/width,0,0,target.bh/height,0,0]});item.task=task;REV_PDF.tasks.add(task);
      try{await task.promise;
        if(gen===RZ.gen&&item.canvas===canvas)item.el.dataset.state='ready';
      }catch(e){if(gen===RZ.gen&&item.canvas===canvas){
        item.el.dataset.state='error';$('#revision-status').textContent='일부 비교 PDF 쪽을 그리지 못했습니다. 소스 diff를 확인할 수 있습니다.';
      }}finally{REV_PDF.tasks.delete(task);if(item.task===task)item.task=null;}
    }
  }catch(e){if(gen===RZ.gen&&revisionPdfActive())
    $('#revision-status').textContent='일부 비교 PDF 쪽을 그리지 못했습니다. 소스 diff를 확인할 수 있습니다.';
  }finally{if(RZ.busy===gen){RZ.busy=0;if(RZ.repaint)scheduleRevisionPaint();}}
}

/** Comparison input stays on its scroll area; detach gesture state on document exit. */
(function revisionZoomInputs(){
  const box=$('#revision-pdf');let frame=0,acc=1,point=/** @type {number[]|null} */(null);
  let gesture=/** @type {{ratio:number,anchor:RevisionAnchor|null}|null} */(null);
  let touch=/** @type {{distance:number,ratio:number,anchor:RevisionAnchor|null}|null} */(null);
  /** Apply the composed wheel gesture only to the current comparison. */
  const flush=()=>{frame=0;const factor=acc,pt=point;acc=1;point=null;if(pt)revisionZoomTo(RZ.ratio*factor,pt[0],pt[1]);};
  RZ.resetInput=()=>{if(frame)cancelAnimationFrame(frame);frame=0;acc=1;point=null;gesture=null;touch=null;};
  box.addEventListener('wheel',e=>{if(!revisionPdfActive()||!(e.ctrlKey||e.metaKey))return;e.preventDefault();
    acc*=wheelFactor(e.deltaY,e.deltaMode);point=[e.clientX,e.clientY];if(!frame)frame=requestAnimationFrame(flush);},{passive:false});
  box.addEventListener('gesturestart',e=>{if(!revisionPdfActive())return;e.preventDefault();
    gesture={ratio:RZ.ratio,anchor:revisionAnchor(e.clientX,e.clientY)};},{passive:false});
  box.addEventListener('gesturechange',e=>{if(!gesture||touch||!revisionPdfActive()||!(e.scale>0))return;e.preventDefault();
    revisionZoomTo(gesture.ratio*e.scale,e.clientX,e.clientY,gesture.anchor);},{passive:false});
  box.addEventListener('gestureend',()=>{gesture=null;});
  /** Distance and midpoint of the two touches in viewport coordinates. */
  const points=touches=>{const a=touches[0],b=touches[1];return {distance:Math.hypot(a.clientX-b.clientX,a.clientY-b.clientY)||1,
    x:(a.clientX+b.clientX)/2,y:(a.clientY+b.clientY)/2};};
  box.addEventListener('touchstart',e=>{if(!revisionPdfActive()||e.touches.length!==2){touch=null;return;}
    if(e.cancelable)e.preventDefault();const p=points(e.touches);
    touch={distance:p.distance,ratio:RZ.ratio,anchor:revisionAnchor(p.x,p.y)};},{passive:false});
  box.addEventListener('touchmove',e=>{if(!touch||e.touches.length!==2||!revisionPdfActive())return;
    if(e.cancelable)e.preventDefault();const p=points(e.touches);
    revisionZoomTo(touch.ratio*p.distance/touch.distance,p.x,p.y,touch.anchor);},{passive:false});
  box.addEventListener('touchend',e=>{if(e.touches.length!==2)touch=null;});
  box.addEventListener('touchcancel',()=>{touch=null;});
  box.addEventListener('scroll',()=>{if(revisionPdfActive()){RZ.anchor=revisionAnchor();scheduleRevisionPaint();}},{passive:true});
  const observer=new ResizeObserver(()=>{if(!revisionPdfActive())return;
    const style=getComputedStyle(box),fit=box.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight);
    if(Math.abs(fit-RZ.fit)>.5)layoutRevisionPdf(RZ.anchor);
  });observer.observe(box);
})();
