/** Bounded native-viewer spike: actual PDF find and candidate inline assignment.
 * All API effects remain in native-fixture.js; production rules are unchanged.
 */
(() => {
  'use strict';
  if(!window.LimnDemo)return;
  const pageNative=goPage,jumpNative=jumpPin,switchNative=switchDoc,refreshNative=refreshDoc,viewNative=setViewMode;
  const applyMentionNative=mentionApply,previewNative=mentionPreview,guardNative=mentionGuard;
  const assignNative=renderAssignNew,openPopNative=openSelPop;
  let searchRequest=0,extractionGeneration=0,findActive=false;
  /** @type {HTMLElement|null} */
  let findPanel=null;
  /** @type {HTMLElement|null} */
  let returnFocus=null;
  /** @type {import('./native-pdf.mjs').TextHit[]} */
  let hits=[];
  /** @type {{key:string,promise:Promise<import('./native-pdf.mjs').TextPage[]>}|null} */
  let extraction=null;
  /** @type {any} */
  let loadingTask=null;
  let hitIndex=0;

  /** Require an existing native seam; missing markup is a prototype defect. @param {string} selector */
  function node(selector) {
    const element=document.querySelector(selector);
    if(!(element instanceof HTMLElement))throw new Error('Missing native viewer element: '+selector);
    return element;
  }
  /** Require one native textarea so shared note/hint ownership cannot silently drift. @param {string} selector */
  function field(selector) {
    const element=node(selector);
    if(!(element instanceof HTMLTextAreaElement))throw new Error('Missing native textarea: '+selector);
    return element;
  }
  /** Create a native-token button with an accessible action name. @param {string} label @param {string} action @param {string} [icon] */
  function button(label,action,icon) {
    const element=document.createElement('button');
    element.type='button';element.className='btn-sm btn-ghost';element.dataset.ux=action;
    element.setAttribute('aria-label',label);
    if(icon)setHtml(element,ic(icon));else element.textContent=label;
    return element;
  }
  /** Install one persistent PDF search field and an on-demand results strip at the document's right edge. */
  function installDocumentTools() {
    const group=document.createElement('div');group.id='ux-doc-tools';group.setAttribute('role','search');
    const input=document.createElement('input');input.type='search';input.id='ux-body-query';input.maxLength=200;
    input.placeholder='본문 찾기';input.setAttribute('aria-label','원고 PDF 본문 검색');input.setAttribute('aria-keyshortcuts','Meta+F Control+F');
    input.setAttribute('aria-controls','ux-body-find');input.setAttribute('aria-expanded','false');
    input.addEventListener('focus',event=>{
      if(event.relatedTarget instanceof HTMLElement&&!event.relatedTarget.closest('#ux-doc-tools,#ux-body-find'))returnFocus=event.relatedTarget;
      if(!findActive)void searchBody(input.value);
    });
    input.addEventListener('input',()=>{void searchBody(input.value);});
    group.append(input);node('#doc-nav').appendChild(group);
    const panel=document.createElement('div');panel.id='ux-body-find';panel.hidden=true;
    panel.setAttribute('role','group');panel.setAttribute('aria-label','본문 검색 결과');
    const count=document.createElement('output');count.id='ux-body-count';count.setAttribute('aria-live','polite');count.textContent='0';
    const previous=button('이전 결과','find-prev','chevron-down');previous.classList.add('ux-prev');
    panel.append(count,previous,button('다음 결과','find-next','chevron-down'),button('검색 닫기','find-close','x'));
    document.body.appendChild(panel);findPanel=panel;updateFindControls();
  }
  /** Key extracted text to the actual displayed document/build, never the authored source-location fixture. */
  function documentKey() { return (DOC||'main')+'|'+(META?.pages_build||''); }
  /** Extract actual PDF bytes once per displayed build; destroy this spike's worker after projection. */
  async function ensurePages() {
    const key=documentKey();if(extraction?.key===key)return extraction.promise;
    const generation=extractionGeneration;
    const promise=(async()=>{
      // PDF.js has no declarations in the native viewer; its module remains an I/O seam.
      const module='/vendor/pdfjs/pdf.min.mjs',lib=await import(module);
      const text=await import('./native-pdf.mjs');
      lib.GlobalWorkerOptions.workerSrc='/vendor/pdfjs/pdf.worker.min.mjs';
      const response=await fetch('/pdf?doc='+encodeURIComponent(DOC||'main')+'&build='+encodeURIComponent(META?.pages_build||''));
      if(!response.ok)throw new Error('Demo PDF HTTP '+response.status);
      const bytes=await response.arrayBuffer();if(bytes.byteLength>20*1024*1024)throw new Error('Demo PDF byte limit exceeded');
      if(generation!==extractionGeneration||key!==documentKey())return [];
      const task=lib.getDocument({data:new Uint8Array(bytes),isEvalSupported:false,useWasm:false,enableXfa:false});loadingTask=task;
      try {
        const pdf=await task.promise,result=await text.extractPages(pdf,lib.Util);
        if(generation!==extractionGeneration||key!==documentKey())return [];
        return result;
      }finally{if(loadingTask===task)loadingTask=null;await task.destroy();}
    })();
    extraction={key,promise};return promise;
  }
  /** Keep the transient results below the field and inside its current document/viewport edge. */
  function placeFind() {
    if(!findPanel||findPanel.hidden)return;
    const rect=node('#ux-body-query').getBoundingClientRect();
    findPanel.style.top=rect.bottom+4+'px';
    findPanel.style.right=Math.max(8,innerWidth-rect.right)+'px';
  }
  /** Select a retained query without replacing native draft or region selection. */
  function focusBodySearch() {
    const active=document.activeElement;
    if(active instanceof HTMLElement&&!active.closest('#ux-doc-tools,#ux-body-find'))returnFocus=active;
    const input=node('#ux-body-query');
    if(input instanceof HTMLInputElement){input.focus();input.select();if(!findActive)void searchBody(input.value);}
  }
  /** Synchronize disabled result actions and field disclosure with the actual search state. */
  function updateFindControls() {
    if(!findPanel)return;
    findPanel.querySelectorAll('[data-ux=find-prev],[data-ux=find-next]').forEach(element=>{
      if(element instanceof HTMLButtonElement)element.disabled=!hits.length;
    });
    node('#ux-body-query').setAttribute('aria-expanded',String(!findPanel.hidden));
  }
  /** Clear search paint separately from native annotation marks and selections. */
  function clearHits() {node('#doc').querySelectorAll('.ux-body-hit').forEach(element=>element.remove());}
  /** Dismiss results/paint, retain query, and optionally restore a connected visible prior control. @param {boolean} [restore] */
  function hideBodySearch(restore=false) {
    searchRequest++;findActive=false;hits=[];if(findPanel)findPanel.hidden=true;
    clearHits();updateFindControls();
    if(restore){
      if(returnFocus?.isConnected&&returnFocus.getClientRects().length&&getComputedStyle(returnFocus).visibility==='visible')returnFocus.focus({preventScroll:true});
      if(document.activeElement!==returnFocus){
        if(returnFocus?.classList.contains('sp-note')&&field('#note').getClientRects().length)field('#note').focus({preventScroll:true});
        else if(document.activeElement instanceof HTMLElement)document.activeElement.blur();
      }
    }
  }
  /** Resolve every literal occurrence from actual PDF extraction; stale queries never replace newer results. @param {string} query */
  async function searchBody(query) {
    const request=++searchRequest;clearHits();hits=[];hitIndex=0;
    const count=node('#ux-body-count');findActive=Boolean(query.trim());
    if(findPanel)findPanel.hidden=!findActive;updateFindControls();placeFind();
    count.textContent=findActive?'읽는 중…':'0';if(!findActive)return;
    try{
      const result=await ensurePages(),text=await import('./native-pdf.mjs');
      if(request!==searchRequest||!findActive)return;
      hits=text.findHits(result,query);count.textContent=hits.length?'1/'+hits.length:'0';updateFindControls();if(hits.length)gotoHit(0);
    }catch(error){if(request===searchRequest)count.textContent='읽기 실패';console.error('Demo body find failed',error);}
  }
  /** Paint whole matched PDF text-item bounds on the actual page and bring that result into view. @param {number} index */
  function gotoHit(index) {
    if(!findActive||!hits.length)return;clearHits();hitIndex=(index+hits.length)%hits.length;
    const hit=hits[hitIndex];node('#ux-body-count').textContent=(hitIndex+1)+'/'+hits.length+' · '+hit.page+'쪽';
    const page=document.getElementById('p'+hit.page);if(!page)return;
    for(const run of hit.runs) {
      const mark=document.createElement('div');mark.className='ux-body-hit';
      const rect=run.rect;Object.assign(mark.style,{left:rect.x*100+'%',top:rect.y*100+'%',width:rect.w*100+'%',height:rect.h*100+'%'});
      page.appendChild(mark);
    }
    const target=page.querySelector('.ux-body-hit')||page;target.scrollIntoView({block:'center'});
  }
  /** Intercept only plain find chords or active search keys before native global shortcuts. @param {KeyboardEvent} event */
  function searchKeys(event) {
    if(event.isComposing||event.keyCode===229||document.body.classList.contains('revision-open')||document.querySelector('dialog[open]'))return;
    if(event.key.toLowerCase()==='f'&&(event.ctrlKey!==event.metaKey)&&!event.altKey&&!event.shiftKey){
      event.preventDefault();event.stopImmediatePropagation();focusBodySearch();return;
    }
    if(!(event.target instanceof Element)||!event.target.closest('#ux-doc-tools,#ux-body-find'))return;
    if(event.key==='Escape'){
      event.preventDefault();event.stopImmediatePropagation();hideBodySearch(true);
    }else if(event.target.id==='ux-body-query'&&event.key==='Enter'&&!event.altKey&&!event.ctrlKey&&!event.metaKey){
      event.preventDefault();event.stopImmediatePropagation();gotoHit(hitIndex+(event.shiftKey?-1:1));
    }
  }
  /** Forget document-scoped text and stop a pending worker on switch/rebuild. */
  function resetExtraction() {
    extractionGeneration++;extraction=null;hideBodySearch();
    if(loadingTask){void loadingTask.destroy();loadingTask=null;}
  }
  /** Sync both native note surfaces and login hints, preserving their one-draft ownership. @param {HTMLTextAreaElement} source */
  function syncSharedNote(source) {
    const note=field('#note'),popover=field('#sel-pop textarea'),other=source===note?popover:note;
    other.value=source.value;other._mentions=new Set(mentionHints(source));
    autoGrow(note);renderAssignNew();mentionPreview(note);mentionPreview(popover);
    qHint(node('#c-qhint'),note.value,KIND_NEW);saveDraftSoon();placeSelPop();
  }
  /** Add native autocomplete to the selection-local field and preview the pending assignment rule. */
  function installInlineAssignment() {
    const popover=field('#sel-pop textarea'),preview=document.createElement('div');
    preview.className='m-preview';preview.setAttribute('aria-live','polite');preview.hidden=true;popover.after(preview);
    /** The candidate picks only the first resolved non-self colleague; no tag retains agent. */
    defaultAssignee=function(text,kind,hints){return mentionScan(text,hints).hit.find(login=>login!==meLogin())||ASSIGNEE_AGENT;};
    /** A hidden choice row cannot retain a previous override in this inline-only candidate. */
    renderAssignNew=function(){ASSIGN_NEW.touched=false;assignNative();};
    /** Keep reply/edit previews native; new notes use existing preview space for assignment/FYI. */
    mentionPreview=function(ta){
      previewNative(ta);if(!ta||(ta.id!=='note'&&!ta.classList.contains('sp-note')))return;
      const box=ta.nextElementSibling;if(!(box instanceof HTMLElement)||!box.classList.contains('m-preview'))return;
      const resolved=mentionScan(ta.value,new Set(mentionHints(ta))).hit.filter(login=>login!==meLogin());
      if(!resolved.length)return;
      const assignment=document.createElement('span');assignment.className='m-lab';assignment.textContent='담당 '+peopleName(resolved[0]);
      const context=document.createElement('span');context.className='m-note';
      context.textContent=resolved.length>1?'· 참고 '+resolved.slice(1).map(peopleName).join(', '):'';
      const warning=Array.from(box.querySelectorAll('.mention-bad,.m-note')).filter(element=>!element.classList.contains('m-note')||element.textContent==='등록된 사람이 아님');
      box.replaceChildren(assignment,context,...warning);box.hidden=false;
    };
    /** The popover's existing save/handoff actions are protected by native mention placement. */
    mentionGuard=function(ta){return ta.classList.contains('sp-note')?node('#sel-pop .sp-acts'):guardNative(ta);};
    /** Picking on either note copies both visible text and exact autocomplete login hint. */
    mentionApply=function(index){const ta=MENTION.ta;applyMentionNative(index);if(ta&&(ta.id==='note'||ta.classList.contains('sp-note')))syncSharedNote(ta);};
    /** Opening the native popover restores the shared selection's login hints alongside its text. */
    openSelPop=function(box){popover._mentions=new Set(mentionHints(field('#note')));openPopNative(box);mentionPreview(popover);placeSelPop();};
    popover.addEventListener('input',()=>{syncSharedNote(popover);mentionUpdate(popover);});
    popover.addEventListener('focus',()=>{popover._mentions=new Set(mentionHints(field('#note')));mentionPreview(popover);});
    field('#note').addEventListener('input',()=>syncSharedNote(field('#note')));
    ['keyup','click','focusout'].forEach(type=>popover.addEventListener(type,()=>{setTimeout(()=>mentionPreview(popover),0);}));
    new ResizeObserver(()=>{placeSelPop();if(MENTION.ta===popover&&!node('#mention-pop').hidden)mentionUpdate(popover);}).observe(node('#sel-pop'));
  }
  /** Dispatch only spike controls; actual native handlers keep every existing viewer action. @param {MouseEvent} event */
  function clickExtension(event) {
    if(!(event.target instanceof Element))return;
    const control=event.target.closest('[data-ux]');if(!(control instanceof HTMLElement))return;
    event.preventDefault();event.stopImmediatePropagation();
    switch(control.dataset.ux) {
      case 'find-close':hideBodySearch(true);break;
      case 'find-prev':gotoHit(hitIndex-1);break;
      case 'find-next':gotoHit(hitIndex+1);break;
    }
  }

  installDocumentTools();installInlineAssignment();
  /** Native page navigation dismisses search while retaining its selection/draft semantics. */
  goPage=function(value){hideBodySearch();pageNative(value);};
  /** A native pin jump restores its PDF before applying native location behavior. */
  jumpPin=function(id){hideBodySearch();jumpNative(id);};
  /** Revision search is outside this candidate; keep hidden manuscript hits and shortcuts inactive. */
  setViewMode=function(mode){
    hideBodySearch();viewNative(mode);
    const input=node('#ux-body-query');
    if(input instanceof HTMLInputElement){
      input.disabled=document.body.classList.contains('revision-open');
      input.placeholder=input.disabled?'원고에서 찾기':'본문 찾기';
    }
  };
  /** A valid native document switch parks its own draft and invalidates only the spike's text. */
  switchDoc=async function(key){if(key&&key!==DOC&&docInfo(key)){hideBodySearch();resetExtraction();}await switchNative(key);};
  /** A native rebuild invalidates extracted text only when the displayed document/build changes. */
  refreshDoc=async function(meta){const key=documentKey();await refreshNative(meta);if(key!==documentKey()){hideBodySearch();resetExtraction();}};
  document.addEventListener('keydown',searchKeys,true);document.addEventListener('click',clickExtension,true);window.addEventListener('resize',()=>requestAnimationFrame(placeFind));
  window.addEventListener('pagehide',resetExtraction);
})();
