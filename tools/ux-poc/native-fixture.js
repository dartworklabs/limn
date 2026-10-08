/** Anonymous native-viewer fixture. All API writes terminate in this tab's memory;
 * only allowlisted same-origin GET assets reach the dedicated static demo server.
 */
(() => {
  'use strict';
  const realFetch = window.fetch.bind(window);
  const DATA = window.LimnDemoReading;
  const ME = {login:'alice@example.com',name:'Alice',role:'owner'};
  const COLLEAGUE = {login:'demo-colleague@example.com',name:'동료',role:'editor'};
  const ROBINS = [{login:'robin.one@example.com',name:'Robin Lee',role:'editor'},
    {login:'robin.two@example.com',name:'Robin Lee',role:'editor'}];
  const AGENT = {login:'agent:demo',name:'에이전트',role:'agent'};
  const COMMIT = 'a15b9e4a15b9e4a15b9e4a15b9e4a15b9e4a15b9e4';
  const SHORT_COMMIT = COMMIT.slice(0,7);
  const PARENT = 'b16c8f5b16c8f5b16c8f5b16c8f5b16c8f5b16c8f5';
  /** @type {Pin[]} */
  let pins = seedPins();
  /** @type {Pin[]} */
  let dropped = [];
  let revision = 1, buildSeq = 1;
  let stale = new URLSearchParams(location.search).get('stale') === '1';
  /** @type {{started:number,doc:string}|null} */
  let runningBuild = null;

  /** Return a JSON-safe detached fixture value.
   * @template T @param {T} value @returns {T}
   */
  function clone(value) { return JSON.parse(JSON.stringify(value)); }

  /** Use native local timestamp formatting only for anonymous display records.
   * @param {number} [time] @returns {string}
   */
  function stamp(time = Date.now()) {
    const date = new Date(time), pad = (/** @type {number} */ value) => String(value).padStart(2,'0');
    return date.getFullYear()+'-'+pad(date.getMonth()+1)+'-'+pad(date.getDate())+' '+pad(date.getHours())+':'+pad(date.getMinutes())+':'+pad(date.getSeconds());
  }

  /** Choose the authored block nearest a fractional selection center.
   * @param {number[]} frac @returns {NativeDemoReading['blocks'][number]}
   */
  function blockAt(frac) {
    const x=frac[0]+frac[2]/2, y=frac[1]+frac[3]/2;
    return DATA.blocks.reduce((best,item)=>{
      const distance = (/** @type {NativeDemoReading['blocks'][number]} */ entry) => Math.hypot(x-entry.rect.x-entry.rect.w/2,y-entry.rect.y-entry.rect.h/2);
      return distance(item)<distance(best)?item:best;
    });
  }

  /** Return the source range authored for a block, never a SyncTeX claim.
   * @param {NativeDemoReading['blocks'][number]} block @returns {[number,number]}
   */
  function linesFor(block) { const index=DATA.blocks.indexOf(block); return [42+index*12,48+index*12]; }

  /** Format authored prose as native numbered source lines for the excerpt cache.
   * @param {number} lo @param {number} hi @param {string} value @returns {string}
   */
  function numberedSnippet(lo,hi,value) {
    const chars=Array.from(value),count=Math.min(100,Math.max(1,hi-lo+1)),width=Math.ceil(chars.length/count);
    return Array.from({length:count},(_,index)=>String(lo+index).padStart(5,' ')+'  '+chars.slice(index*width,(index+1)*width).join('')).join('\n');
  }

  /** Produce the real pick schema for an authored sample rectangle.
   * @param {number} page @param {number[]} frac @returns {NativeDemoSelection}
   */
  function pickFor(page,frac) {
    const block=blockAt(frac),[lo,hi]=linesFor(block),snippet=numberedSnippet(lo,hi,block.text);
    return {doc:activeDoc(),file:activeDoc()==='main'?'main.tex':'supplement.tex',name:activeDoc()==='main'?'main.tex':'supplement.tex',
      page,lo,hi,raw_lo:lo,raw_hi:hi,kind:'paragraph',via:'synctex',score:1,warn:'',n_lines:160,snippet,quote:block.text,
      frac:frac.slice(),pdf_build:buildName(),overlaps:[],default_level:'paragraph',
      levels:[{level:'paragraph',lo,hi,n:7,label:'문단',snippet},{level:'section',lo:Math.max(1,lo-5),hi:hi+7,n:19,label:'절',snippet}]};
  }

  /** Choose only one of the two anonymous demo documents from native URL state.
   * @returns {'main'|'supplement'}
   */
  function activeDoc() { return /(?:^#|&)doc=supplement(?:&|$)/.test(location.hash)?'supplement':'main'; }

  /** Keep the only two allowlisted sample build names stable across rebuilds. */
  function buildName() { return buildSeq===1?'demo-build-1':'demo-build-2'; }

  /** Build the original prototype scenarios in native wire shapes.
   * @returns {Pin[]}
   */
  function seedPins() {
    const notes=[
      '주입과 추출 조건을 같은 표에서 비교할 수 있도록 정리해 주세요.',
      '비교 기준 온도의 정의를 한 문장으로 보충하겠습니다.',
      '이 경계 조건은 겨울과 여름에 모두 적용되나요?',
      '그림 범례와 본문의 표기 순서를 맞춰 주세요.',
      '이웃 보어홀의 영향과 전체 온도 부담을 구분해 주세요.',
      '운전기간을 늘리면 같은 결론이 유지되나요?',
      '온도 기호와 단위를 통일해 주세요.',
      '결과 해석에서 주입·추출 배정의 차이를 조금 더 설명해 주세요.',
      '보충자료의 시간 간격은 본문과 같은가요?',
      '보충 표의 소수 자릿수를 맞춰 주세요.',
    ];
    const ranges=[[42,48],[54,58],[67,72],[83,88],[94,101],[112,118],[24,31],[124,130],[18,22],[61,66]];
    const locations=['method-1','intro-2','method-2','figure-1','result-1','limit-1','intro-1','result-2','intro-1','figure-1'];
    /** @type {Record<number,string>} */
    const results={15:'전체 평균과 개별 보어홀 응답을 나누고 비교 조건을 추가했습니다.',16:'운전기간이 길면 누적 효과가 커집니다. 본문의 적용 범위를 1년으로 명시했습니다.',17:'본문과 표의 단위를 모두 °C로 통일했습니다.',20:'모든 열을 소수 둘째 자리까지 표시했습니다.'};
    return notes.map((note,index)=>{
      const id=11+index,block=DATA.blocks.find(item=>item.id===locations[index])||DATA.blocks[0],r=block.rect,
        doc=id>=19?'supplement':'main',file=doc==='main'?'main.tex':'supplement.tex';
      /** @type {Pin} */
      const pin={id,doc,file,name:file,rel_path:file,page:1,lo:ranges[index][0],hi:ranges[index][1],raw_lo:ranges[index][0],raw_hi:ranges[index][1],
        frac:[r.x,r.y,r.w,r.h],mark:[r.x,r.y,r.w,r.h],mark_page:1,quote:block.text,
        pdf_build:'demo-build-1',kind:'paragraph',scope:'paragraph',via:'synctex',score:1,stale:false,sync:'ok',
        note,kind_req:[13,16,19].includes(id)?'question':'fix',assignee:[12,17,19].includes(id)?ME.login:[13,16,18].includes(id)?COLLEAGUE.login:'agent',
        mentions:[],at:stamp(Date.now()-2*3600000),author:clone(ME),rev:0,state:'open',done:false,review:false,thread:[]};
      if(id===14){pin.claimed_by=clone(AGENT);pin.claimed_at=stamp(Date.now()-8*60000);pin.claim_ts=Date.now()/1000-480;pin.claim_until=Date.now()/1000+3600;pin.eta_ts=Date.now()/1000+420;}
      if([15,16,17,20].includes(id)){
        pin.state=id===17?'done':'review';pin.done=true;pin.review=id!==17;pin.closed_by=clone(id===17?ME:AGENT);pin.done_at=stamp(Date.now()-30*60000);
        pin.close_ref=SHORT_COMMIT;pin.close_reply=results[id];pin.changes=[{file,lo:pin.lo||1,hi:pin.hi||1}];
        pin.thread=[{id:1,by:clone(pin.closed_by),at:pin.done_at,ev:'close',text:pin.close_reply,ref:SHORT_COMMIT}];
      }
      return pin;
    });
  }

  /** Announce an in-memory effect to proposal controls without calling native globals.
   * @param {'pins'|'meta'|'reset'} kind
   */
  function changed(kind) { window.dispatchEvent(new CustomEvent('limn-demo-change',{detail:{kind}})); }

  /** Derive complete native metadata for a closed anonymous document key.
   * @param {string} [doc] @returns {Meta}
   */
  function currentMeta(doc=activeDoc()) {
    const key=doc==='supplement'?'supplement':'main',now=Date.now()/1000,rows=pins.filter(pin=>pin.doc===key),building=!!runningBuild;
    return {pages:[1,2,3].map(page=>({name:'page-'+page+'.png',pt_w:595.276,pt_h:841.89})),built_at:stamp(),head:SHORT_COMMIT,main:key==='main'?'main.tex':'supplement.tex',
      pins_md:'pins.md',state_dir:'demo',me:clone(ME),label:'샘플 원고',accent:'#718096',repo:null,building,sync:{state:'disabled'},
      doc:key,doc_name:key==='main'?'열응답 분석':'보충자료',kind:'tex',view_only:false,multi:true,stale_build:stale,src_age_s:120,
      src_mtime:now+(stale?120:0),build_src_mtime:now,pages_build:buildName(),pins_rev:String(revision),build_seq:buildSeq,
      last_build:{state:'ok',errors:[],finished_at:stamp(),seq:buildSeq,head:SHORT_COMMIT},build:{state:building?'running':'idle',phase:building?'latex':null},
      ev_seq:0,n_open:rows.filter(p=>p.state==='open').length,n_review:rows.filter(p=>p.state==='review').length,n_done:rows.filter(p=>p.state==='done').length,
      docs:documentEntries(),src_sig:String(stale)+':'+buildSeq};
  }

  /** Return two native document entries with identical anonymous PDF geometry.
   * @returns {DocEntry[]}
   */
  function documentEntries() {
    return ['main','supplement'].map(key=>({key,name:key==='main'?'열응답 분석':'보충자료',kind:'tex',view_only:false,path:key+'.tex',main:key+'.tex',
      stale_build:stale,src_mtime:0,building:!!runningBuild,build:{state:runningBuild?'running':'idle',phase:runningBuild?'latex':null},
      build_seq:buildSeq,last_state:'ok',pages_build:buildName(),n_pages:3,n_open:pins.filter(p=>p.doc===key&&p.state==='open').length}));
  }

  /** Keep native preferences and drafts in memory; no browser storage is read or modified.
   * @param {Record<string,string>} initial @returns {Storage}
   */
  function memoryStorage(initial) {
    const values=new Map(Object.entries(initial));
    return {get length(){return values.size;},clear(){values.clear();},getItem(key){return values.get(String(key))??null;},
      key(index){return [...values.keys()][index]??null;},removeItem(key){values.delete(String(key));},setItem(key,value){values.set(String(key),String(value));}};
  }
  Object.defineProperty(window,'localStorage',{value:memoryStorage({pinPrefs:JSON.stringify({theme:'light',coach:{mouse:1,touch:1,side:1},sec:{open:true,review:true,done:false}}),limnLang:'ko'}),configurable:true});
  Object.defineProperty(window,'sessionStorage',{value:memoryStorage({}),configurable:true});

  /** Encode a fixture response; every mocked HTTP failure stays local.
   * @param {unknown} value @param {number} [status] @returns {Response}
   */
  function answer(value,status=200) { return new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}}); }

  /** Refuse an API operation unsupported by this bounded demo.
   * @param {number} [status] @param {string} [reason] @returns {Response}
   */
  function refused(status=405,reason='demo_operation_unavailable') { return answer({error:'이 시연에서는 지원하지 않는 동작입니다',reason},status); }

  /** Parse a bounded native JSON object without accepting arbitrary nested payloads.
   * @param {string} raw @returns {Record<string,unknown>|null}
   */
  function parseBody(raw) {
    if(new TextEncoder().encode(raw).length>16384)return null;
    let value;try{value=JSON.parse(raw||'{}');}catch(error){return null;}
    if(!value||typeof value!=='object'||Array.isArray(value))return null;
    const strings=new Set(['file','name','doc','kind','kind_req','scope','env','via','note','note_append','text','quote','pdf_build','done_at','assignee','commit','base']);
    const numbers=new Set(['page','x0','y0','x1','y1','lo','hi','raw_lo','raw_hi','score','base_rev','eta_min','ttl_min','pin']);
    for(const [key,entry] of Object.entries(value)){
      if(strings.has(key)){if(entry!==null&&typeof entry!=='string')return null;}
      else if(numbers.has(key)){if(typeof entry!=='number'||!Number.isFinite(entry))return null;}
      else if(['frac','mark'].includes(key)){if(!Array.isArray(entry)||entry.length!==4||!entry.every(n=>typeof n==='number'&&Number.isFinite(n)))return null;}
      else if(key==='mentions'){if(!Array.isArray(entry)||entry.length>20||!entry.every(s=>typeof s==='string'))return null;}
      else if(key==='reopen'){if(typeof entry!=='boolean')return null;}
      else if(key==='loc'){
        if(!entry||typeof entry!=='object'||Array.isArray(entry))return null;
        const fields=Object.entries(entry);if(fields.length>20)return null;
        for(const [field,item] of fields){
          if(strings.has(field)){if(item!==null&&typeof item!=='string')return null;}
          else if(numbers.has(field)){if(typeof item!=='number'||!Number.isFinite(item))return null;}
          else if(field==='frac'){if(!rectangle(item))return null;}
          else return null;
        }
      }
      else return null;
    }
    return value;
  }

  /** Read a parsed string field with an explicit fallback.
   * @param {Record<string,unknown>} body @param {string} key @param {string} [fallback]
   */
  function text(body,key,fallback='') { return typeof body[key]==='string'?body[key]:fallback; }

  /** Read a parsed numeric field with an explicit fallback.
   * @param {Record<string,unknown>} body @param {string} key @param {number} fallback
   */
  function number(body,key,fallback) { return typeof body[key]==='number'?body[key]:fallback; }

  /** Accept only a valid in-page native x/y/width/height rectangle.
   * @param {unknown} value @returns {number[]|null}
   */
  function rectangle(value) { return Array.isArray(value)&&value.length===4&&value.every(n=>typeof n==='number'&&n>=0&&n<=1)&&value[2]>0&&value[3]>0&&value[0]+value[2]<=1&&value[1]+value[3]<=1?value:null; }

  /** Append one native state/reply record using only anonymous fixture identity.
   * @param {Pin} pin @param {string} [event] @param {string} [value]
   */
  function addThread(pin,event,value) {
    const thread=pin.thread||(pin.thread=[]),entry={id:thread.length+1,by:clone(ME),at:stamp()};
    thread.push({...entry,...(event?{ev:event}:{}),...(value?{text:value}:{})});
  }

  /** Reopen the demo pin without silently changing its kind or assignee.
   * @param {Pin} pin
   */
  function reopen(pin) { pin.state='open';pin.done=false;pin.review=false;pin.reopened_at=stamp();pin.reopened_by=clone(ME);addThread(pin,'reopen'); }

  /** Build a small source diff authored for the displayed native pin range.
   * @param {URL} url
   */
  function revisionDiff(url) {
    const pin=pins.find(p=>p.id===Number(url.searchParams.get('pin')))||pins.find(p=>p.id===15),lo=pin?.lo||94,file=pin?.file||'main.tex';
    const patch='diff --git a/'+file+' b/'+file+'\n--- a/'+file+'\n+++ b/'+file+'\n@@ -'+lo+',3 +'+lo+',4 @@\n-전체 평균만으로 개선을 판단한다.\n+전체 평균과 개별 보어홀의 온도 응답을 나누어 비교한다.\n+같은 운전기간과 초기 조건을 비교 기준으로 명시한다.\n 이웃 보어홀의 영향은 배치에 따라 달라질 수 있다.\n';
    return {id:COMMIT,parent:PARENT,base:url.searchParams.get('base')||PARENT,diff:patch,truncated:false,files:[file],commits:1,commit_ids:[COMMIT],
      scope:url.searchParams.has('pin')?{mode:'pin',source:'changes',hunks:1,other:0,diff:patch,other_diff:'',truncated:false}:null};
  }

  /** Simulate the existing async build protocol without TeX or any server effect.
   * @param {string} doc
   */
  function startBuild(doc) {
    if(runningBuild)return false;
    runningBuild={started:Date.now(),doc};changed('meta');
    window.setTimeout(()=>{runningBuild=null;stale=false;buildSeq+=1;changed('meta');},900);
    return true;
  }

  /** Read or mutate only the anonymous API fixture; unknown routes fail closed.
   * @param {URL} url @param {string} method @param {Record<string,unknown>} body @returns {Promise<Response>}
   */
  async function fixture(url,method,body) {
    const path=url.pathname,doc=url.searchParams.get('doc')||activeDoc();
    if(method==='GET'){
      if(path==='/api/docs')return answer({docs:documentEntries(),default:'main',multi:true,other_open:1});
      if(path==='/api/meta')return answer(currentMeta(doc));
      if(path==='/api/pins')return answer(clone(pins));
      if(path==='/api/pins/dropped')return answer({dropped:clone(dropped)});
      if(path==='/api/people')return answer({people:[ME,COLLEAGUE,...ROBINS,AGENT],me:ME});
      if(path==='/api/outline-labels')return answer({build:buildName(),labels:[...DATA.sections.map((section,index)=>({title:section.label.replace(/^\d+\s+/,''),number:String(index+1),level:'section'})),
        {title:'추가 비교',number:'5',level:'section'},{title:'텍스트 없는 그림',number:'6',level:'section'}]});
      if(path==='/api/snippet'){
        const lo=Number(url.searchParams.get('lo'))||1,hi=Number(url.searchParams.get('hi'))||lo,block=DATA.blocks[Math.max(0,Math.min(DATA.blocks.length-1,Math.floor((lo-42)/12)))];
        const snippet=numberedSnippet(lo,hi,block.text);
        return answer({file:url.searchParams.get('file')||'main.tex',lo,hi,n_lines:160,snippet,
          levels:[{level:'paragraph',lo,hi,n:hi-lo+1,label:'문단',snippet}]});
      }
      if(path==='/api/build')return answer({state:runningBuild?'running':'ok',phase:runningBuild?'latex':null,started_at:runningBuild?stamp(runningBuild.started):null,
        last_s:1,pages:3,errors:[],built_at:stamp(),seq:buildSeq,finished_at:runningBuild?null:stamp(),last:currentMeta(doc).last_build,head:SHORT_COMMIT,pull:null,
        elapsed_s:runningBuild?(Date.now()-runningBuild.started)/1000:0,log_tail:'',progress:null});
      if(path==='/api/revisions')return answer({available:true,revisions:[{id:COMMIT,date:stamp().slice(0,10),subject:'Clarify comparison conditions',author:'Demo agent',time:new Date().toISOString(),parents:[PARENT]},
        {id:PARENT,date:stamp().slice(0,10),subject:'Add anonymous manuscript example',author:'Alice',time:new Date(Date.now()-3600000).toISOString(),parents:[]}],more:false,overlay:null});
      if(path==='/api/revision-diff')return answer(revisionDiff(url));
      if(path==='/api/revision-build')return answer({state:'ready',head:COMMIT,warnings:[],scope:url.searchParams.has('pin')?'pin':'commit'});
      if(path==='/api/revision-pdf')return realFetch('/sample.pdf');
      const match=/^\/api\/pins\/(\d+)$/.exec(path);
      if(match){const pin=pins.find(p=>p.id===Number(match[1]));return pin?answer(clone(pin)):refused(404,'not_found');}
      return refused(404);
    }
    if(method!=='POST')return refused();
    if(path==='/api/pick'){
      const frac=rectangle(body.frac),page=number(body,'page',1);if(!frac||!Number.isInteger(page)||page<1||page>3)return refused(400,'invalid_demo_selection');
      const result=pickFor(page,frac);result.doc=text(body,'doc',doc);result.file=result.doc==='supplement'?'supplement.tex':'main.tex';result.name=result.file;
      return answer(result);
    }
    if(path==='/api/rebuild')return startBuild(doc)?answer({ok:true,state:'running'},202):refused(409,'building');
    if(path==='/api/revision-build')return answer({state:'ready',head:text(body,'commit',COMMIT),warnings:[],scope:body.pin?'pin':'commit'});
    if(path==='/api/pin'){
      const frac=rectangle(body.frac),page=number(body,'page',1);if(!frac||!Number.isInteger(page)||page<1||page>3)return refused(400,'invalid_demo_selection');
      const id=Math.max(20,...pins.map(p=>p.id))+1,pick=pickFor(page,frac);
      const pin={...pick,id,doc:text(body,'doc',doc),file:text(body,'file',pick.file),name:text(body,'name',pick.name),lo:number(body,'lo',pick.lo||1),hi:number(body,'hi',pick.hi||1),
        kind_req:text(body,'kind_req','fix'),kind:text(body,'kind',pick.kind),scope:text(body,'scope','paragraph'),note:text(body,'note'),quote:text(body,'quote',pick.quote),assignee:text(body,'assignee','agent'),
        mentions:mentionScan(text(body,'note'),new Set(Array.isArray(body.mentions)?body.mentions:[])).hit.filter(login=>login!==ME.login),
        author:clone(ME),at:stamp(),rev:0,state:'open',done:false,review:false,thread:[]};
      pins.push(pin);revision+=1;changed('pins');return answer({ok:true,id,pin:clone(pin)});
    }
    const match=/^\/api\/pins\/(\d+)\/(reply|claim|unclaim|confirm|close|reopen|edit|drop|restore|purge)$/.exec(path);
    if(!match)return refused();
    const id=Number(match[1]),action=match[2],pin=(action==='restore'||action==='purge'?dropped:pins).find(p=>p.id===id);
    if(!pin)return answer({ok:false},404);
    if(action==='confirm'){
      if(pin.state!=='review')return answer({error:'open',reason:'conflict',pin:clone(pin)},409);
      if(body.done_at&&body.done_at!==pin.done_at)return answer({error:'conflict',reason:'conflict',pin:clone(pin)},409);
      pin.state='done';pin.review=false;pin.confirmed_at=stamp();pin.confirmed_by=clone(ME);addThread(pin,'confirm');
    }else if(action==='close'){
      pin.state='done';pin.done=true;pin.review=false;pin.done_at=stamp();pin.closed_by=clone(ME);addThread(pin,'close');
    }else if(action==='reopen')reopen(pin);
    else if(action==='reply'){
      const value=text(body,'text').trim();if(!value)return refused(400,'invalid_demo_reply');
      const doReopen=pin.state!=='open'&&(typeof body.reopen==='boolean'?body.reopen:pin.kind_req!=='question'&&!(Array.isArray(body.mentions)&&body.mentions.length));
      addThread(pin,undefined,value);if(doReopen)reopen(pin);
      pin.rev=(pin.rev||0)+1;revision+=1;changed('pins');return answer({ok:true,reopened:doReopen,state:pin.state,pin:clone(pin)});
    }else if(action==='claim'){
      const eta=number(body,'eta_min',15),ttl=number(body,'ttl_min',30);
      if(eta<1||eta>240||ttl<1||ttl>120||!Number.isInteger(eta)||!Number.isInteger(ttl))return refused(400,'invalid_demo_eta');
      if(pin.state!=='open')return answer({ok:false,error:'done',reason:'done'},409);
      if((pin.claim_until||0)>Date.now()/1000&&pin.claimed_by?.login!==ME.login)return answer({ok:false,error:'claimed',reason:'claimed'},409);
      pin.claimed_by=clone(ME);pin.claimed_at=stamp();pin.claim_ts=Date.now()/1000;pin.claim_until=pin.claim_ts+ttl*60;pin.eta_ts=pin.claim_ts+eta*60;
    }else if(action==='unclaim'){delete pin.claimed_by;delete pin.claimed_at;delete pin.claim_ts;delete pin.claim_until;delete pin.eta_ts;}
    else if(action==='edit'){
      if(body.base_rev!==undefined&&body.base_rev!==(pin.rev||0))return answer({error:'conflict',reason:'conflict',pin:clone(pin)},409);
      if(typeof body.note==='string')pin.note=body.note;
      if(typeof body.note_append==='string')pin.note=(pin.note||'')+'\n\n'+body.note_append;
      if(typeof body.kind_req==='string')pin.kind_req=body.kind_req;
      if(typeof body.assignee==='string')pin.assignee=body.assignee;
      if(typeof body.lo==='number')pin.lo=body.lo;if(typeof body.hi==='number')pin.hi=body.hi;
      if(body.loc&&typeof body.loc==='object'){
        const loc=body.loc;
        if('file' in loc&&typeof loc.file==='string')pin.file=loc.file;
        if('name' in loc&&typeof loc.name==='string')pin.name=loc.name;
        if('page' in loc&&typeof loc.page==='number')pin.page=loc.page;
        if('lo' in loc&&typeof loc.lo==='number')pin.lo=loc.lo;
        if('hi' in loc&&typeof loc.hi==='number')pin.hi=loc.hi;
        if('quote' in loc&&typeof loc.quote==='string')pin.quote=loc.quote;
        if('pdf_build' in loc&&typeof loc.pdf_build==='string')pin.pdf_build=loc.pdf_build;
        if('frac' in loc){const frac=rectangle(loc.frac);if(frac){pin.frac=frac;pin.mark=frac.slice();}}
      }
      pin.edited_at=stamp();pin.edited_by=clone(ME);
    }else if(action==='drop'){pins=pins.filter(p=>p.id!==id);pin.dropped_at=stamp();pin.dropped_by=clone(ME);dropped.push(pin);}
    else if(action==='restore'){dropped=dropped.filter(p=>p.id!==id);delete pin.dropped_at;delete pin.dropped_by;pins.push(pin);}
    else if(action==='purge')dropped=dropped.filter(p=>p.id!==id);
    pin.rev=(pin.rev||0)+1;revision+=1;changed('pins');return answer({ok:true,state:pin.state,pin:clone(pin)});
  }

  /** Intercept every demo API call; refuse external URLs, unsupported methods and unknown mutations.
   * @param {RequestInfo|URL} input @param {RequestInit} [init] @returns {Promise<Response>}
   */
  window.fetch=async function(input,init={}) {
    const url=new URL(input instanceof Request?input.url:String(input),location.href),method=(init.method||(input instanceof Request?input.method:'GET')).toUpperCase();
    if(url.origin!==location.origin)return refused(403,'demo_external_request_refused');
    if(!url.pathname.startsWith('/api/')){
      if(method!=='GET'&&method!=='HEAD')return refused();
      return realFetch(input,init);
    }
    const raw=typeof init.body==='string'?init.body:input instanceof Request?await input.clone().text():'';
    const body=parseBody(raw);if(!body)return refused(400,'invalid_demo_body');
    return fixture(url,method,body);
  };

  window.LimnDemo={snapshotPins:()=>clone(pins),setPins(value){pins=clone(value);revision+=1;changed('pins');},
    reset(){pins=seedPins();dropped=[];revision+=1;stale=false;buildSeq=1;runningBuild=null;changed('reset');},
    setStale(value){stale=!!value;changed('meta');},currentMeta,pickFor,reading:()=>clone(DATA)};
})();
