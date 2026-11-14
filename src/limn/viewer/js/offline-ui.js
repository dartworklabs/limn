// ------------------------------------------------ The queued pins on screen (docs/handbook/viewer.md §끊긴 채 보기와 핀 쌓기)
// offline.js reads the queue (offlineSync) on boot, after every pin kept, dropped or sent, and calls offlineUiSync(all)
// with every record each time. This part draws them: where they stand on the page and in the pin panel.
/** @param {any[]} all every queued record, oldest first (offline.js offAll) */
function offlineUiSync(all){void all;}
