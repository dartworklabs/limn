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
  let phoneSearchOpen=false,wasPhone=false;
  const coarsePointer=matchMedia('(pointer:coarse)');
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
  /** Install search before the native trailing page control; native navigation retains event ownership. */
  function installDocumentTools() {
    const nav=node('#doc-nav'),page=node('#nav-page'),position=node('#btn-pos');
    const positionHome=position.parentElement,positionNext=position.nextSibling;
    if(!positionHome)throw new Error('Missing native position-control home');
    const group=document.createElement('div');group.id='ux-doc-tools';group.setAttribute('role','search');
    const input=document.createElement('input');input.type='search';input.id='ux-body-query';input.maxLength=200;
    input.setAttribute('aria-label','원고 PDF 본문 검색');input.setAttribute('aria-keyshortcuts','Meta+F Control+F');
    input.setAttribute('aria-controls','ux-body-find');input.setAttribute('aria-expanded','false');
    const open=button('본문 검색 열기','find-open');open.id='ux-find-open';
    // This native-token PoC adds only fixed search artwork; the product's bundled icon table is unchanged.
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    for(const [name,value] of Object.entries({class:'ic',viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'2','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',focusable:'false'}))svg.setAttribute(name,value);
    const circle=document.createElementNS(svg.namespaceURI,'circle'),handle=document.createElementNS(svg.namespaceURI,'path');
    circle.setAttribute('cx','11');circle.setAttribute('cy','11');circle.setAttribute('r','8');
    handle.setAttribute('d','m21 21-4.3-4.3');svg.append(circle,handle);open.replaceChildren(svg);
    open.setAttribute('aria-controls',input.id);open.setAttribute('aria-expanded','false');
    const close=button('본문 검색 닫기','find-dismiss','x');close.id='ux-find-dismiss';
    input.addEventListener('focus',event=>{
      if(event.relatedTarget instanceof HTMLElement&&!event.relatedTarget.closest('#ux-doc-tools,#ux-body-find'))returnFocus=event.relatedTarget;
      if(!findActive)void searchBody(input.value);
    });
    input.addEventListener('input',()=>{void searchBody(input.value);});
    group.append(open,input,close);nav.insertBefore(node('#nav-side'),page);nav.insertBefore(group,page);
    /** Native settled bands, including typing holds, own relocation; restore the original node and tab order. */
    function placePosition() {
      if(document.body.classList.contains('band-phone')) {
        if(position.parentElement!==nav)nav.appendChild(position);
      }else if(positionHome&&position.parentElement!==positionHome)positionHome.insertBefore(position,positionNext);
      syncSearchDisclosure();placeFind();
    }
    /** Compact only native numeric page text; its full accessible name and page-list behavior stay native. */
    function compactPage() {
      const match=page.textContent?.match(/^\s*(\d+)\s*\/\s*(\d+)/);
      if(!match)return;
      const compact=match[1]+'/'+match[2];
      if(page.textContent!==compact)page.textContent=compact;
    }
    const bandObserver=new MutationObserver(placePosition),pageObserver=new MutationObserver(compactPage);
    bandObserver.observe(document.body,{attributes:true,attributeFilter:['class']});
    pageObserver.observe(page,{childList:true,characterData:true,subtree:true});
    placePosition();compactPage();
    coarsePointer.addEventListener('change',syncSearchDisclosure);
    window.addEventListener('pagehide',event=>{
      if(!event.persisted){bandObserver.disconnect();pageObserver.disconnect();coarsePointer.removeEventListener('change',syncSearchDisclosure);}
    });
    const panel=document.createElement('div');panel.id='ux-body-find';panel.hidden=true;
    panel.setAttribute('role','group');panel.setAttribute('aria-label','본문 검색 결과');
    const count=document.createElement('output');count.id='ux-body-count';count.setAttribute('aria-live','polite');count.textContent='0';
    const previous=button('이전 결과','find-prev','chevron-down');previous.classList.add('ux-prev');
    panel.append(count,previous,button('다음 결과','find-next','chevron-down'),button('검색 닫기','find-close','x'));
    document.body.appendChild(panel);findPanel=panel;updateFindControls();
  }
  /** Follow settled bands/media; retain active search and transfer only a close action hidden by its new band. */
  function syncSearchDisclosure() {
    const input=node('#ux-body-query'),open=node('#ux-find-open'),close=node('#ux-find-dismiss');
    if(!(input instanceof HTMLInputElement)||!(open instanceof HTMLButtonElement))return;
    const active=document.activeElement;
    const phone=document.body.classList.contains('band-phone'),revision=document.body.classList.contains('revision-open');
    if(phone&&!wasPhone&&(active===input||findActive))phoneSearchOpen=true;
    if(!phone||revision)phoneSearchOpen=false;
    wasPhone=phone;
    const hidden=phone&&!phoneSearchOpen;
    if((hidden||revision)&&active===input)input.blur();
    if(!phone&&active===open)open.blur();
    input.hidden=hidden;input.disabled=revision;open.disabled=revision;
    open.hidden=!phone||phoneSearchOpen;close.hidden=!phone||!phoneSearchOpen;
    const resultClose=document.querySelector('[data-ux=find-close]');
    if(phone&&active===resultClose&&resultClose instanceof HTMLElement){
      if(phoneSearchOpen)close.focus({preventScroll:true});else resultClose.blur();
    }
    if(!phone&&active===close){
      if(findActive&&resultClose instanceof HTMLElement)resultClose.focus({preventScroll:true});else close.blur();
    }
    open.setAttribute('aria-expanded',String(phoneSearchOpen));
    node('#ux-doc-tools').classList.toggle('ux-search-open',phoneSearchOpen);
    const shortcut=/Mac|iPhone|iPad|iPod/.test(navigator.platform)?'⌘ F':'Ctrl F';
    input.placeholder=document.body.classList.contains('compact')||phone||coarsePointer.matches?'본문 검색':'Search  '+shortcut;
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
    const rightLimit=innerWidth-findPanel.getBoundingClientRect().width-8;
    findPanel.style.right=Math.max(8,Math.min(innerWidth-rect.right,rightLimit))+'px';
  }
  /** Reveal/focus synchronously within activation, retaining native drafts; return false for unavailable rows. */
  function focusBodySearch() {
    const input=node('#ux-body-query'),nav=node('#doc-nav');
    if(!(input instanceof HTMLInputElement)||input.disabled||!nav.getClientRects().length||getComputedStyle(nav).visibility!=='visible')return false;
    const active=document.activeElement;
    if(active instanceof HTMLElement&&!active.closest('#ux-doc-tools,#ux-body-find'))returnFocus=active;
    if(document.body.classList.contains('band-phone')){phoneSearchOpen=true;syncSearchDisclosure();}
    input.focus();input.select();if(!findActive)void searchBody(input.value);
    return true;
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
    const phone=document.body.classList.contains('band-phone');
    searchRequest++;findActive=false;hits=[];if(findPanel)findPanel.hidden=true;
    phoneSearchOpen=false;syncSearchDisclosure();
    clearHits();updateFindControls();
    if(restore){
      if(phone){const open=node('#ux-find-open');if(!open.hidden)open.focus({preventScroll:true});return;}
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
    }catch(error){if(request===searchRequest)count.textContent='검색 실패';console.error('Demo body find failed',error);}
  }
  /** Paint the actual PDF hit and scroll into its page so native position agrees with the result. @param {number} index */
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
    const scroller=node('#left'),head=page.getBoundingClientRect().top-scroller.getBoundingClientRect().top;
    if(head>0)scroller.scrollTop+=head;
  }
  /** Intercept only plain find chords or active search keys before native global shortcuts. @param {KeyboardEvent} event */
  function searchKeys(event) {
    if(event.isComposing||event.keyCode===229||document.body.classList.contains('revision-open')||document.querySelector('dialog[open]'))return;
    if(event.key.toLowerCase()==='f'&&(event.ctrlKey!==event.metaKey)&&!event.altKey&&!event.shiftKey){
      if(focusBodySearch()){event.preventDefault();event.stopImmediatePropagation();}return;
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
      case 'find-open':focusBodySearch();break;
      case 'find-dismiss':hideBodySearch(true);break;
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
    syncSearchDisclosure();
  };
  /** A valid native document switch parks its own draft and invalidates only the spike's text. */
  switchDoc=async function(key){if(key&&key!==DOC&&docInfo(key)){hideBodySearch();resetExtraction();}await switchNative(key);};
  /** A native rebuild invalidates extracted text only when the displayed document/build changes. */
  refreshDoc=async function(meta){const key=documentKey();await refreshNative(meta);if(key!==documentKey()){hideBodySearch();resetExtraction();}};
  document.addEventListener('keydown',searchKeys,true);document.addEventListener('click',clickExtension,true);window.addEventListener('resize',()=>requestAnimationFrame(placeFind));
  window.addEventListener('pagehide',resetExtraction);
})();
