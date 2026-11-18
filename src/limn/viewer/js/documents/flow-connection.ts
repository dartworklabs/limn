import { api } from '../platform/api.ts';

// ---------------- Limn itself was updated
// The page's version (the [더보기] foot's 'v0.4.51', filled in when the server made the page) and the server's (GET
// /api/version, asked by documents/flow-polling.ts after a lost connection comes back, on return and every
// VERSION_EVERY_MS): when they differ, this tab runs the old viewer against a new server, and the status line says so
// with [새로 고침] until it reloads. A call while one is out (busy) is left to it, and asked again once it is answered
// (again): the one out may fail, or have been answered by the process a restart has just replaced - the return after a
// lost connection must not go unasked.
const VERSION = { page: '', server: '', at: 0, busy: false, again: false };
const VERSION_EVERY_MS = 60000;
function versionDue() {
  return Date.now() - VERSION.at >= VERSION_EVERY_MS;
}
function versionOutdated() {
  if (!VERSION.page) {
    const versionElement = document.querySelector('#more-foot .m-ver');
    VERSION.page = versionElement
      ? String(versionElement.textContent || '')
          .trim()
          .replace(/^v/, '')
      : '';
  }
  return VERSION.server && VERSION.page && VERSION.server !== VERSION.page ? VERSION.server : '';
}

async function checkVersion(drawStatus: () => void) {
  if (VERSION.busy) {
    VERSION.again = true;
    return;
  }
  VERSION.busy = true;
  VERSION.again = false;
  VERSION.at = Date.now();
  try {
    const answer = (await api('GET /api/version', { what: '버전 확인', silent: true })).data,
      version = String((answer && answer.version) || '');
    if (version && version !== VERSION.server) {
      const was = versionOutdated();
      VERSION.server = version;
      if (versionOutdated() !== was) drawStatus();
    }
  } catch (error) {
  } finally {
    VERSION.busy = false;
  }
  if (VERSION.again) checkVersion(drawStatus);
}
// Consecutive light-poll failures used by the status line and the offline pin queue.
let POLL_FAILS = 0;
function setPollFails(value: number) {
  POLL_FAILS = value;
  return value;
}
export { versionDue, versionOutdated, checkVersion, POLL_FAILS, setPollFails };
