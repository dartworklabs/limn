// ------------------------------------------------ PDF rebuild
function topAnchor(off){const L=$('#left'),top=L.getBoundingClientRect().top+(off||0);
  for(const pg of $$('.pg')){const r=pg.getBoundingClientRect(); if(r.bottom>top+1)return {page:+pg.dataset.page,frac:Math.max(0,(top-r.top)/r.height)};}
  return null;}
function restoreAnchor(a){if(!a)return; const pg=document.getElementById('p'+a.page); if(!pg)return; const L=$('#left');
  L.scrollTop+=pg.getBoundingClientRect().top-L.getBoundingClientRect().top+a.frac*pg.getBoundingClientRect().height;}
// Apply a supplied meta snapshot, or fetch one for the current document. A switch away and back invalidates an
// in-flight refresh even when the document key matches again; its old pages must not replace the new visit.
async function refreshDoc(meta){const a=topAnchor(),k=DOC,seq=SWITCHSEQ;
  const m=meta===undefined?(await api(dq('/api/meta'),{what:'화면 정보 읽기'})).data:meta;
  if(k!==DOC||seq!==SWITCHSEQ)return;
  META_BY.set(k,m);
  const same=META&&m.pages.length===META.pages.length; META=m; drawMeta();
  // The canvas was drawn from the old PDF - it's torn down to show the new PNG first, then redrawn once the new build's PDF is opened.
  if(same){vecReleaseAll(); $$('.pg').forEach((pg,i)=>{const p=META.pages[i]; pg.style.aspectRatio=p.pt_w+' / '+p.pt_h; pg.querySelector('img').src=pageSrc(p);});}
  else buildDoc();
  restoreAnchor(a); vecOpen(); if(document.body.classList.contains('revision-open'))loadRevisions(); await loadPins();}
// On ok_errors|fail, the panel itself is opened right away, not just a toast - once the toast disappeared after 6
// seconds there used to be no way to see it again. Even after closing it, #build-err-chip remains to reopen it (as long as BUILD.error exists).
function showBuildErr(r){BUILD.error=r; if(DOC)BUILD_ERR_BY.set(DOC,r); const b=$('#build-err');
  const title=tr(r.state===BUILD_STATE.FAIL?'빌드 실패 — 화면은 이전 PDF입니다':'PDF를 재빌드했지만 LaTeX 오류가 있습니다');
  b.innerHTML='<div class="row"><b>'+esc(title)+'</b><span class="sp"></span>'+
    '<button class="btn-sm" data-act="err-close" data-tip="이 알림을 닫습니다(다시 보기는 위 배지로)">닫기</button></div>'+
    (r.errors||[]).map(e=>'<div class="dim">'+(e.line?'L'+e.line+' · ':'')+esc(e.msg)+'</div>').join('')+
    '<pre class="nowrap" style="max-height:30vh">'+esc(String(r.log_tail||r.log||'').split('\n').slice(-20).join('\n'))+'</pre>';
  b.hidden=false; $('#build-err-chip').hidden=true;}
function hideBuildErr(){$('#build-err').hidden=true; $('#build-err-chip').hidden=!BUILD.error;}
// docs/handbook/build-sync.md §비동기 재빌드: rebuild is async - the POST returns immediately, and the #build-chip poller (startBuildPolling) shows
// progress, then does the in-place swap and notification once it finishes. A build started by someone else is caught by the same poller.
// Its completion may update controls or start polling only while the initiating document visit remains active. BUILD.asked
// marks that this tab asked, so an unchanged rebuild (no new seq) still gets its toast; it is set only after any older
// in-flight poll settled, since that one may carry the previous rebuild's unchanged mark. force (only the [그래도 빌드]
// of an unchanged rebuild's toast passes it) asks for ?force=1: a cold build that never ends unchanged.
async function rebuild(force){
  const k=DOC,visit=SWITCHSEQ;
  try{const {status}=await api(dq('/api/rebuild?async=1'+(force===true?'&force=1':'')),{method:'POST',what:'PDF 재빌드',expect:[409]});
    if(k!==DOC||visit!==SWITCHSEQ)return;
    if(status===409){toast('이미 다른 곳에서 PDF를 재빌드하는 중입니다 — 끝난 뒤 다시 누르세요','warn');return;}
    $('#build-err').hidden=true;
    // If a request already went out before this POST, its completion is awaited before asking again - that request
    // carries a stale state (ok) and would never turn on 1-second polling. Completion is distinguished by build_seq, so this tab has nothing separate to remember.
    if(BUILD.inflight){try{await BUILD.inflight;}catch(e){}}
    if(k!==DOC||visit!==SWITCHSEQ)return;
    BUILD.asked=true; await pollBuild();
  }catch(e){}}
