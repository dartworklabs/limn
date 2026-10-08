/** Bounded native-viewer spike: actual PDF text and candidate inline assignment.
 * All API effects remain in native-fixture.js; production rules are unchanged.
 */
(() => {
  'use strict';
  if(!window.LimnDemo)return;
  const pageNative=goPage,jumpNative=jumpPin,switchNative=switchDoc,refreshNative=refreshDoc;
  const applyMentionNative=mentionApply,previewNative=mentionPreview,guardNative=mentionGuard;
  const assignNative=renderAssignNew,openPopNative=openSelPop;
  let reading=false,readScroll=0,readRequest=0,searchRequest=0,extractionGeneration=0;
  /** @type {HTMLElement|null} */
  let readArticle=null;
  /** @type {HTMLElement|null} */
  let findPanel=null;
  /** @type {import('./native-pdf.mjs').TextPage[]} */
  let pages=[];
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
  /** Add direct actions inside the native main document topbar, without another row. */
  function installDocumentTools() {
    const group=document.createElement('div');group.id='ux-doc-tools';
    group.setAttribute('role','group');group.setAttribute('aria-label','본문 읽기와 찾기');
    const find=button('본문 찾기','body-search');find.id='ux-find';
    const long=document.createElement('span');long.className='ux-find-label';long.textContent='본문 찾기';
    const short=document.createElement('span');short.className='ux-find-short';short.textContent='찾기';short.setAttribute('aria-hidden','true');
    find.replaceChildren(long,short);find.setAttribute('aria-controls','ux-body-find');find.setAttribute('aria-expanded','false');
    const read=button('본문 읽기','reading','text-quote');read.id='ux-read';read.setAttribute('aria-pressed','false');
    const label=document.createElement('span');label.className='lbl';label.textContent='읽기';read.appendChild(label);
    group.append(find,read);node('#view-switch').after(group);
  }
  /** Key extracted text to the actual displayed document/build, never the authored reading fixture. */
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
        pages=result;return result;
      }finally{if(loadingTask===task)loadingTask=null;await task.destroy();}
    })();
    extraction={key,promise};return promise;
  }
  /** Create the reader on demand; plain text is selectable and never interpreted as markup. */
  function ensureReading() {
    if(readArticle)return readArticle;
    const article=document.createElement('article');article.id='ux-reading';article.hidden=true;
    article.setAttribute('aria-label','PDF 본문');node('#left').appendChild(article);readArticle=article;return article;
  }
  /** Present actual extracted runs in PDF content-stream order with real page labels. */
  function renderReading() {
    const article=ensureReading();article.replaceChildren();
    for(const page of pages) {
      const section=document.createElement('section');section.id='ux-reading-page-'+page.page;section.tabIndex=-1;
      const title=document.createElement('h2');title.textContent=page.page+'쪽';
      const paragraph=document.createElement('p');paragraph.setAttribute('translate','no');
      if(!page.runs.length)paragraph.textContent='추출 가능한 텍스트가 없습니다.';
      let end=0;
      page.runs.forEach((run,index)=>{
        paragraph.append(document.createTextNode(page.search.slice(end,run.start)));
        const span=document.createElement('span');span.id='ux-run-'+page.page+'-'+index;span.textContent=run.text;
        paragraph.appendChild(span);end=run.end;
      });
      section.append(title,paragraph);article.appendChild(section);
    }
  }
  /** Switch reading without cancelling the native selection or note; late extraction cannot switch a newer visit. @param {boolean} value */
  async function setReading(value) {
    const request=++readRequest;
    if(value&&!reading)readScroll=node('#left').scrollTop;
    reading=value;if(value){setSelMode(false);closeSelPop();}
    const article=ensureReading();article.hidden=!value;node('#doc').hidden=value;
    document.body.classList.toggle('ux-reading-mode',value);
    const action=node('#ux-read');action.setAttribute('aria-pressed',String(value));
    action.setAttribute('aria-label',value?'PDF로 돌아가기':'본문 읽기');
    const label=action.querySelector('.lbl');if(label)label.textContent=value?'PDF':'읽기';
    if(!value){node('#left').scrollTop=readScroll;if(hits.length&&findPanel&&!findPanel.hidden)gotoHit(hitIndex);return;}
    article.textContent='본문을 읽는 중입니다.';article.setAttribute('aria-busy','true');node('#left').scrollTop=0;
    try{await ensurePages();if(request!==readRequest||!reading)return;renderReading();if(hits.length)gotoHit(hitIndex);}
    catch(error){if(request===readRequest&&reading)article.textContent='본문 텍스트를 읽지 못했습니다.';console.error('Demo PDF text extraction failed',error);}
    finally{if(request===readRequest)article.removeAttribute('aria-busy');}
  }
  /** Keep the transient find panel below its current native topbar action and inside the viewport. */
  function placeFind() {
    if(!findPanel||findPanel.hidden)return;
    const rect=node('#ux-find').getBoundingClientRect();
    findPanel.style.top=rect.bottom+4+'px';
    findPanel.style.right=Math.max(8,innerWidth-node('#doc-nav').getBoundingClientRect().right)+'px';
  }
  /** Open one compact find row; its query searches only extracted PDF text. */
  function openBodySearch() {
    if(!findPanel) {
      const panel=document.createElement('div');panel.id='ux-body-find';panel.setAttribute('role','search');
      const input=document.createElement('input');input.type='search';input.id='ux-body-query';input.maxLength=200;
      input.placeholder='본문 찾기';input.setAttribute('aria-label','PDF 본문 검색');
      input.addEventListener('input',()=>{void searchBody(input.value);});
      input.addEventListener('keydown',event=>{
        if(event.isComposing)return;
        if(event.key==='Enter'||event.key==='ArrowDown'||event.key==='ArrowUp'){
          event.preventDefault();event.stopPropagation();gotoHit(hitIndex+(event.key==='ArrowUp'||event.shiftKey?-1:1));
        }else if(event.key==='Escape'){event.preventDefault();event.stopPropagation();hideBodySearch();node('#ux-find').focus();}
      });
      const count=document.createElement('output');count.id='ux-body-count';count.setAttribute('aria-live','polite');count.textContent='0';
      const previous=button('이전 결과','find-prev','chevron-down');previous.classList.add('ux-prev');
      panel.append(input,count,previous,button('다음 결과','find-next','chevron-down'),button('닫기','find-close','x'));
      document.body.appendChild(panel);findPanel=panel;
    }
    findPanel.hidden=false;node('#ux-find').setAttribute('aria-expanded','true');placeFind();
    const input=findPanel.querySelector('input');if(input instanceof HTMLInputElement){input.focus();void searchBody(input.value);}
  }
  /** Clear search paint separately from native annotation marks and selections. */
  function clearHits() {
    node('#doc').querySelectorAll('.ux-body-hit').forEach(element=>element.remove());
    readArticle?.querySelectorAll('.ux-reading-hit').forEach(element=>element.classList.remove('ux-reading-hit'));
  }
  /** Close the transient find row and its paint while retaining reading and the native draft. */
  function hideBodySearch() {
    searchRequest++;if(findPanel)findPanel.hidden=true;
    node('#ux-find').setAttribute('aria-expanded','false');clearHits();
  }
  /** Resolve every literal occurrence from actual PDF extraction; stale queries never replace newer results. @param {string} query */
  async function searchBody(query) {
    const request=++searchRequest;clearHits();hits=[];hitIndex=0;
    const count=node('#ux-body-count');count.textContent=query.trim()?'읽는 중…':'0';
    if(!query.trim())return;
    try{
      const result=await ensurePages(),text=await import('./native-pdf.mjs');
      if(request!==searchRequest||!findPanel||findPanel.hidden)return;
      hits=text.findHits(result,query);count.textContent=hits.length?'1/'+hits.length:'0';if(hits.length)gotoHit(0);
    }catch(error){if(request===searchRequest)count.textContent='읽기 실패';console.error('Demo body find failed',error);}
  }
  /** Paint matched PDF text-item bounds on the true page, or reveal the corresponding selectable reader runs. @param {number} index */
  function gotoHit(index) {
    if(!hits.length)return;clearHits();hitIndex=(index+hits.length)%hits.length;
    const hit=hits[hitIndex];node('#ux-body-count').textContent=(hitIndex+1)+'/'+hits.length+' · '+hit.page+'쪽';
    if(reading) {
      const page=pages.find(item=>item.page===hit.page);if(!page)return;
      for(const run of hit.runs)document.getElementById('ux-run-'+hit.page+'-'+page.runs.indexOf(run))?.classList.add('ux-reading-hit');
      const target=readArticle?.querySelector('.ux-reading-hit')||document.getElementById('ux-reading-page-'+hit.page);
      if(target instanceof HTMLElement)target.scrollIntoView({block:'center'});return;
    }
    const page=document.getElementById('p'+hit.page);if(!page)return;
    for(const run of hit.runs) {
      const mark=document.createElement('div');mark.className='ux-body-hit';
      const rect=run.rect;Object.assign(mark.style,{left:rect.x*100+'%',top:rect.y*100+'%',width:rect.w*100+'%',height:rect.h*100+'%'});
      page.appendChild(mark);
    }
    const target=page.querySelector('.ux-body-hit')||page;target.scrollIntoView({block:'center'});
  }
  /** Leave only the spike's reading/find surfaces before native PDF navigation. */
  function leaveReading() {void setReading(false);hideBodySearch();}
  /** Forget document-scoped text and stop a pending worker on switch/rebuild. */
  function resetExtraction() {
    extractionGeneration++;extraction=null;pages=[];hits=[];readRequest++;searchRequest++;
    if(loadingTask){void loadingTask.destroy();loadingTask=null;}
    readArticle?.replaceChildren();clearHits();
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
      case 'reading':void setReading(!reading);break;
      case 'body-search':if(findPanel&&!findPanel.hidden)hideBodySearch();else openBodySearch();break;
      case 'find-close':hideBodySearch();node('#ux-find').focus();break;
      case 'find-prev':gotoHit(hitIndex-1);break;
      case 'find-next':gotoHit(hitIndex+1);break;
    }
  }

  installDocumentTools();installInlineAssignment();
  /** Native page navigation restores PDF while retaining its selection/draft semantics. */
  goPage=function(value){leaveReading();pageNative(value);};
  /** A native pin jump restores its PDF before applying native location behavior. */
  jumpPin=function(id){leaveReading();jumpNative(id);};
  /** A valid native document switch parks its own draft and invalidates only the spike's text. */
  switchDoc=async function(key){if(key&&key!==DOC&&docInfo(key)){leaveReading();resetExtraction();}await switchNative(key);};
  /** A native rebuild invalidates extracted text only when the displayed document/build changes. */
  refreshDoc=async function(meta){const key=documentKey();await refreshNative(meta);if(key!==documentKey()){leaveReading();resetExtraction();}};
  node('#left').addEventListener('pointerdown',event=>{if(reading&&event.target instanceof Element&&event.target.closest('#ux-reading'))event.stopImmediatePropagation();},true);
  document.addEventListener('click',clickExtension,true);window.addEventListener('resize',()=>requestAnimationFrame(placeFind));
  window.addEventListener('pagehide',resetExtraction);
})();
