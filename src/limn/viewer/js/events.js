// ------------------------------------------------ Help
let HELP_BACK=null;
function openHelp(){const d=$('#help'); if(d.open)return; HELP_BACK=document.activeElement; hideTip(); d.showModal(); toastHost();}
$('#help').addEventListener('close',()=>{if(HELP_BACK&&HELP_BACK.focus)HELP_BACK.focus(); HELP_BACK=null;});

// ------------------------------------------------ Event delegation (no inline handlers)
document.addEventListener('click',e=>{
  const cp=e.target.closest('[data-copy]'); if(cp){copyText(cp.dataset.copy);return;}
  const a=e.target.closest('[data-act]'); if(!a)return;
  const host=a.closest('[data-id]'),id=host?+host.dataset.id:null,inEdit=!!a.closest('.edit');
  const fromMore=!!a.closest('#more');
  if(fromMore&&(a.dataset.close||a.dataset.act==='help'))$('#more').close();
  switch(a.dataset.act){
    case 'side':toggleSide();break;
    case 'selmode':setSelMode(!SELMODE);if(SELMODE&&LAYOUT==='narrow'&&!CUR&&!EDIT)setSide(false);break;
    case 'more':openMore();break; case 'more-close':$('#more').close();break;
    case 'size-preset':sizePreset(+a.dataset.i);break;
    case 'm-jump':$('#more').close();goPage($('#m-jump').value);break;
    case 'coach-close':$('#coach').hidden=true;break;
    case 'toasts-expand':$('#toasts').classList.add('expanded'); syncToastStack(); break;
    case 'card-toggle':if(id==null)break; if(OPEN_CARDS.has(id))OPEN_CARDS.delete(id); else OPEN_CARDS.add(id); drawPins();break;
    case 'rebuild':rebuild();break; case 'reload':loadPins();break;
    case 'zoom-in':zoom(1);break; case 'zoom-out':zoom(-1);break; case 'fit':fitW();break;
    case 'theme':cycleTheme();break; case 'lang':switchLang();break; case 'notify-toggle':notifyToggle();break; case 'help':openHelp();break; case 'help-close':$('#help').close();break;
    case 'save':if(!viewerBlocked())savePin();break; case 'cancel':discardSelection();break;
    case 'overlap-append':{const text=$('#note').value.trim();
      if(!text){toast('메모를 먼저 써야 덧붙일 수 있습니다','warn');break;}
      appendToPin(+a.dataset.oid,text);break;}
    case 'overlap-separate':OVERLAP_DISMISSED=a.dataset.key||null;renderOverlapBanner();break;
    case 'wrap':WRAP=!WRAP;savePrefs({wrap:WRAP});renderComposer();renderEdit();break;
    case 'copy-cur':if(CUR)copyText(CUR.name+' L'+CUR.lo+'-L'+CUR.hi);break;
    case 'expand':SNIP_OPEN=!SNIP_OPEN;renderComposer();break;
    case 'level':{const o=inEdit?EDIT:CUR; if(!o)break; useLevel(o,a.dataset.level); if(!inEdit)recomputeOverlap(); inEdit?renderEdit():renderComposer(); break;}
    case 'nudge':{const o=inEdit?EDIT:CUR; if(!o||!nudge(o,a.dataset.dir))break; if(!inEdit)recomputeOverlap(); const r=inEdit?renderEdit:renderComposer; r(); refetchSnip(o,r); break;}
    case 'view':jumpPin(id);break; case 'edit':openEdit(id);break;
    case 'doc':{const inMenu=!!a.closest('#docs-menu'); switchDoc(a.dataset.doc); if(inMenu)$('#docs-menu').close(); break;}
    // ^ inMenu is determined before calling switchDoc() - for a cached document, switchDoc finishes synchronously
    //   through drawDocTabs, and inside that it redraws the open #docs-menu (drawDocsMenu), detaching a from the DOM.
    //   Calling a.closest() after switchDoc would return null, leaving the menu open and blocking the next tab
    //   interaction (a touch regression).
    case 'doc-menu':openDocsMenu();break; case 'docs-menu-close':$('#docs-menu').close();break;
    case 'view-mode':setViewMode(a.dataset.mode);break;
    case 'rev-back':revBack();break;
    case 'outline':toggleOutline();break;
    case 'outline-page':if(LAYOUT==='mid'&&OUTLINE_MID_OPEN)toggleOutline();OUTLINE_SELECTED=Number(a.dataset.index);OUTLINE_ACTIVE_PAGE=Number(a.dataset.page);OUTLINE_PINNED={index:OUTLINE_SELECTED,page:OUTLINE_ACTIVE_PAGE};renderOutline();updateSectionStrip();setViewMode('manuscript');goPage(a.dataset.page);break;
    case 'revision':showRevision(a.dataset.commit);break;
    case 'revision-format':setRevisionFormat(a.dataset.format);break;
    case 'all-docs':SHOW_ALL=!SHOW_ALL;drawPins();break;
    case 'mention-filter':MENTION_ONLY=!MENTION_ONLY;drawPins();break;
    case 'mention-pick':mentionApply(+a.dataset.i);break;
    case 'pin-ref':gotoPinRef(+a.dataset.ref);break;
    case 'assign-new':ASSIGN_NEW.v=a.dataset.v||'agent'; ASSIGN_NEW.touched=true; renderAssignNew(); saveDraftSoon(); break;
    case 'assign-edit':if(EDIT){EDIT.assignee=a.dataset.v||'agent'; renderAssignEdit();} break;
    case 'msg-more':{const k=a.dataset.key; if(!k)break; if(MSG_OPEN.has(k))MSG_OPEN.delete(k); else MSG_OPEN.add(k); drawPins(); break;}
    case 'diff-wrap':setDiffWrap(!DIFF_WRAP);break;
    case 'revision-other':toggleRevisionOther();break;
    case 'revision-whole':setRevisionWhole(!REV_SCOPE.whole);break;
    case 'mark-jump':revealCard(id);jumpToCard(id);break;
    case 'close':closePin(id);break; case 'drop':dropPin(id,false);break;
    case 'restore':restorePin(id);break; case 'purge':if(id!=null)purgePin(id);break; case 'unclaim':unclaimPin(id);break;
    case 'kind':{const fromHint=!!a.closest('#c-qhint'); setKind(a.dataset.kind);
      // [질문으로 보내기] hides itself (qHint), which would drop focus to <body> and make Ctrl+Enter do nothing - back to the memo.
      if(fromHint){const n=$('#note'); n.focus({preventScroll:true}); n.setSelectionRange(n.value.length,n.value.length);}
      break;}
    case 'e-kind':if(EDIT){EDIT.kind_req=a.dataset.kind==='question'?'question':'fix'; renderEdit();}break;
    case 'reply-open':if(id!=null)openReply(id);break;
    case 'reply-flip':if(REPLY){REPLY.flip=!REPLY.flip; renderReplyOutcome();}break;
    case 'confirm':if(id!=null)confirmPin(id);break;
    case 'change':if(id!=null)showChange(id);break;
    case 'goto-review':gotoReview();break;
    case 'reply-cancel':closeReply();break; case 'reply-send':sendReply();break;
    case 'thread-more':if(id==null)break; if(THREAD_OPEN.has(id))THREAD_OPEN.delete(id); else THREAD_OPEN.add(id); drawPins();break;
    case 'arc-toggle':{const k=a.dataset.key; if(!k)break; if(ARC_OPEN.has(k))ARC_OPEN.delete(k); else ARC_OPEN.add(k); drawPins(); break;}
    case 'esave':saveEdit();break; case 'ecancel':cancelEdit();break;
    case 'repick':startRepick();break; case 'rp-cancel':cancelRepick();break; case 'rp-apply':applyRepick();break;
    case 'sec-toggle':toggleSec(a.dataset.sec);break;
    case 'done-toggle':toggleSec('done');if(fromMore)revealList('#done-toggle',SEC.done);break;
    case 'trash-open':openTrash();break; case 'trash-close':$('#trash').close();break;
    case 'err-close':hideBuildErr();break;
    case 'build-err-reopen':if(LAST_BUILD_ERR){setSide(true); showBuildErr(LAST_BUILD_ERR);} break;   // the chip floats on a collapsed panel; the log is inside it
  }
});
$('#doc-select').addEventListener('change',e=>switchDoc(e.target.value));
$('#revision-list').addEventListener('change',e=>{if(e.target.id==='revision-select')showRevision(e.target.value);});
$('#revision-file').addEventListener('change',renderRevisionFile);
document.addEventListener('keydown',e=>{
  if(e.isComposing||e.keyCode===229)return;
  const t=e.target,inField=t&&(t.tagName==='TEXTAREA'||t.tagName==='INPUT'||t.tagName==='SELECT'||t.isContentEditable);
  // Ctrl(Cmd) + = / - / 0 zooms/fits just the PDF page instead of the browser zoom. Left to the browser inside an input field.
  if((e.ctrlKey||e.metaKey)&&!e.altKey&&!inField){const z=zoomKey(e);
    if(z){e.preventDefault(); if(z==='fit')fitW(); else zoom(z==='in'?1:-1); return;}}
  // Document switching (multiple documents): Ctrl+PgUp/PgDn is previous/next, Alt+1...9 is that index (e.code - Option+digit on Mac produces a different character).
  // The selector uses default keyboard handling. Global shortcuts are never used inside an input field.
  if(multiDoc()&&!inField){
    if(e.ctrlKey&&!e.altKey&&!e.metaKey&&(e.key==='PageUp'||e.key==='PageDown')){e.preventDefault(); cycleDoc(e.key==='PageDown'?1:-1); return;}
    if(e.altKey&&!e.ctrlKey&&!e.metaKey&&/^Digit[1-9]$/.test(e.code||'')){const d=DOCS[+e.code.slice(5)-1]; if(d){e.preventDefault(); switchDoc(d.key);} return;}
  }
  // Ctrl(Cmd)+\ opens and collapses the pin panel at every width (docs/handbook/viewer.md §패널 폭과 시트 높이) - not inside a text field.
  if((e.ctrlKey||e.metaKey)&&!e.altKey&&!inField&&(e.code==='Backslash'||e.key==='\\')){e.preventDefault(); toggleSide(); return;}
  if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)){
    if(t&&(t.id==='note'||(t.closest&&t.closest('#composer')&&!$('#composer').hidden&&!inField))){e.preventDefault(); if(!viewerBlocked())savePin();}
    else if(t&&t.classList&&t.classList.contains('e-note')){e.preventDefault();saveEdit();}
    else if(t&&t.classList&&t.classList.contains('r-text')){e.preventDefault();sendReply();}
    return;}
  if(e.key==='Enter'&&t&&t.dataset&&t.dataset.copy!==undefined&&!inField){copyText(t.dataset.copy);return;}
  // A span with role=button (a card's #number) is also activated by Enter/Space - sent through the same data-act path as a click.
  if((e.key==='Enter'||e.key===' ')&&t&&t.getAttribute&&/^(button|link)$/.test(t.getAttribute('role')||'')&&t.dataset&&t.dataset.act&&!inField){e.preventDefault();t.click();return;}
  if(e.key==='Escape'){
    if($('#help').open||$('#more').open||$('#docs-menu').open||$('#trash').open)return;
    if(!TIP.hidden){hideTip(); if(!inField){e.preventDefault(); return;}}
    // Each Esc closes the top thing only; a handled Esc is not also a close request (the back-gesture layer's CloseWatcher).
    if(LAYOUT==='mid'&&OUTLINE_MID_OPEN){e.preventDefault();toggleOutline();return;}
    if(REPICK){e.preventDefault();cancelRepick();return;}
    if(REPLY){e.preventDefault();closeReply();return;}
    if(EDIT){e.preventDefault();cancelEdit();return;}
    if(CUR||!$('#composer').hidden){e.preventDefault();discardSelection();return;}
    // The 701-900px overlay panel covers the document: Esc collapses it (a selection above was cancelled first).
    if(LAYOUT==='mid'&&MID_OVERLAY&&SIDE_OPEN){e.preventDefault();setSide(false,true,true);focusSideToggle();return;}
    if(document.body.classList.contains('revision-open')){e.preventDefault();revBack();return;}   // Esc in [변경 보기] = [원고로]
    return;}
  if(e.key==='?'&&!inField&&!e.metaKey&&!e.ctrlKey&&!e.altKey){e.preventDefault();openHelp();}
});
boot();
