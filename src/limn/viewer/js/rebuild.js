// ------------------------------------------------ PDF rebuild
// The reading spot: the page at the PDF scroller's top edge (or off px below it) and how far down that page the edge is
// (frac, 0-1), with whether the scroller is at its very top on a touch screen (atTop); null with no pages.
function topAnchor(off){const L=$('#left'),top=L.getBoundingClientRect().top+(off||0),atTop=MQ_COARSE.matches&&L.scrollTop<=0;
  for(const pg of $$('.pg')){const r=pg.getBoundingClientRect(); if(r.bottom>top+1)return {page:+pg.dataset.page,frac:Math.max(0,(top-r.top)/r.height),atTop};}
  return null;}
// Scrolls the PDF back to a reading spot from topAnchor() after a re-fit. On a touch screen - where the select mode lives - a
// spot taken at the very top stays at the top, so the space above page 1 (its margin, or the select mode's reserve that keeps
// the mode bar off its first line) is kept rather than scrolled away; a mouse window re-fits as it always did.
function restoreAnchor(a){if(!a)return; if(a.atTop){$('#left').scrollTop=0; return;} const pg=document.getElementById('p'+a.page); if(!pg)return; const L=$('#left');
  L.scrollTop+=pg.getBoundingClientRect().top-L.getBoundingClientRect().top+a.frac*pg.getBoundingClientRect().height;}
// Apply a supplied meta snapshot, or fetch one for the current document. A switch away and back invalidates an
// in-flight refresh even when the document key matches again; its old pages must not replace the new visit. A failed read
// is said on the status line (api, NOTICE_HOST.LINE) and throws. A refresh means a new build of the document is here (a
// completed build, one met on returning to the document or on a pick): a failed request to rebuild it is over (rebuildSources).
async function refreshDoc(meta){const a=topAnchor(),k=DOC,seq=SWITCHSEQ;
  const m=meta===undefined?(await api(dq('/api/meta'),{what:'화면 정보 읽기',where:NOTICE_HOST.LINE})).data:meta;
  if(k!==DOC||seq!==SWITCHSEQ)return;
  rebuildSources(k).forEach(sourceOk); META_BY.set(k,m);
  const same=META&&m.pages.length===META.pages.length; META=m; drawMeta();
  // The canvas was drawn from the old PDF - it's torn down to show the new PNG first, then redrawn once the new build's PDF is opened.
  if(same){vecReleaseAll(); $$('.pg').forEach((pg,i)=>{const p=META.pages[i]; pg.style.aspectRatio=p.pt_w+' / '+p.pt_h; pg.querySelector('img').src=pageSrc(p);});}
  else buildDoc();
  restoreAnchor(a); vecOpen(); if(document.body.classList.contains('revision-open'))loadRevisions(); await loadPins();}
// On ok_errors|fail, the panel itself is opened right away: it is where a failed build is said (with the pull's line,
// pullSuffix), and the status line's failure item (compact) and #build-err-chip (the desktop's chips, while the panel is not on
// screen: syncBuildErrChip) keep a way to open it again as long as BUILD.error exists. say = a build this visit watched has
// just failed: its title is read out as an alert too (rule 1) - the desktop's panel and chip are no live region.
/** @param {any} r @param {boolean} [say] */
function showBuildErr(r,say){BUILD.error=r; if(DOC)BUILD_ERR_BY.set(DOC,r); const b=$('#build-err');
  const title=buildErrTitle(r); if(say)announce(title,true);
  const log=String(r.log_tail||r.log||'').split('\n').slice(-20).join('\n');
  const close=html`<button class="btn-sm" data-act="err-close" data-tip="이 알림을 닫습니다(다시 보기는 위 배지로)">닫기</button>`;
  const errors=(r.errors||[]).map(e=>html`<div class="dim">${e.line?'L'+e.line+' · ':''}${e.msg}</div>`);
  setHtml(b,html`<div class="row"><b>${title}</b><span class="sp"></span>${close}</div>${errors}<pre class="nowrap" style="max-height:30vh">${log}</pre>`);
  b.hidden=false; syncBuildErrChip();}
// The error sources of document k's rebuild (notices.js sourceEntry): the requests rebuild() sends, plain and forced
// (api's source is the method and URL). A failed [PDF 재빌드] says itself under its own; an answered one clears it, and so
// does a later build of that document, which refreshDoc shows.
/** @param {string|null} k @returns {string[]} */
function rebuildSources(k){return ['/api/rebuild?async=1','/api/rebuild?async=1&force=1'].map(u=>'POST '+dq(u,k||undefined));}
// The title of build r's failure (fail) or its LaTeX errors (ok_errors), with the pull's line: the error panel's, and what
// showBuildErr reads out.
/** @param {any} r @returns {string} */
function buildErrTitle(r){return tr(r.state===BUILD_STATE.FAIL?'빌드 실패 — 화면은 이전 PDF입니다':'PDF를 재빌드했지만 LaTeX 오류가 있습니다')+pullSuffix(r);}
// Closes the build error panel; its chip stays while the error does (syncBuildErrChip).
function hideBuildErr(){$('#build-err').hidden=true; syncBuildErrChip();}
// #build-err-chip ('빌드 오류 · 다시 보기') shows while there is a build error whose panel is not on screen: closed, or inside a
// collapsed panel - where only the status chips float, so it is the one sign of a failed build on a collapsed desktop.
function syncBuildErrChip(){$('#build-err-chip').hidden=!BUILD.error||(SIDE_OPEN&&!$('#build-err').hidden);}
// docs/handbook/build-sync.md §비동기 재빌드: rebuild is async - the POST returns immediately, and the #build-chip poller (startBuildPolling) shows
// progress, then does the in-place swap and says so once it finishes. A build started by someone else is caught by the same poller.
// Its completion may update controls or start polling only while the initiating document visit remains active. BUILD.asked
// marks that this tab asked, so an unchanged rebuild (no new seq) still gets its answer; it is set only after any older
// in-flight poll settled, since that one may carry the previous rebuild's unchanged mark. force (only the status line's
// [그래도 빌드] of an unchanged rebuild passes it) asks for ?force=1: a cold build that never ends unchanged. A rebuild already
// running elsewhere (409) is a warning on the status line; a failed request an error there, with [다시 시도].
async function rebuild(force){
  const k=DOC,visit=SWITCHSEQ;
  try{const {status}=await api(dq('/api/rebuild?async=1'+(force===true?'&force=1':'')),{method:'POST',what:'PDF 재빌드',where:NOTICE_HOST.LINE,
      retry:()=>rebuild(force),expect:[409]});
    if(k!==DOC||visit!==SWITCHSEQ)return;
    if(status===409){lineNote('이미 다른 곳에서 PDF를 재빌드하는 중입니다 — 끝난 뒤 다시 누르세요',NOTICE_KIND.WARN);return;}
    $('#build-err').hidden=true;
    // If a request already went out before this POST, its completion is awaited before asking again - that request
    // carries a stale state (ok) and would never turn on 1-second polling. Completion is distinguished by build_seq, so this tab has nothing separate to remember.
    if(BUILD.inflight){try{await BUILD.inflight;}catch(e){}}
    if(k!==DOC||visit!==SWITCHSEQ)return;
    BUILD.asked=true; await pollBuild();
  }catch(e){}}

// [더보기]'s [PDF 내려받기]: saves the PDF of the build on screen (META.pages_build) of this document as a file. The server names it
// after the document (GET /pdf?download=1 adds Content-Disposition: attachment, docs/handbook/api.md); a click on a link that carries
// the download attribute is the browser's own save, so the page stays where it is. Nothing is sent when no build is on screen.
function downloadPdf(){
  if(!META||!META.pages_build)return;
  const a=document.createElement('a');
  a.href=dq('/pdf?build='+encodeURIComponent(META.pages_build)+'&download=1'); a.download=''; a.hidden=true;
  document.body.appendChild(a); a.click(); a.remove();}
