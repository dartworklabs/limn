import { translateTemplate } from '../platform/i18n.ts';
import { api } from '../platform/api.ts';
import { quietNote } from '../platform/notices.ts';
import { NOTICE_HOST } from '../platform/tables.ts';
import { markMine } from './state.ts';

// [되살리기] (the Trash, a deleted pin's row, a background message): the pin is back as it was. Silent - its card is
// there. Resolves with whether it was restored: a message whose action this is stays until then (noticeAct); a failure
// says itself where it can be seen (bannerNote: the status line while the panel is closed). settled runs once the
// request is answered, before the list reload (trashRestore's bound is the request's).
async function restoreDroppedPin(
  id: number | null,
  reload: () => Promise<boolean>,
  settled?: () => void,
): Promise<boolean> {
  let ok = false;
  try {
    await api('POST /api/pins/{id}/restore', {
      id,
      what: '되살리기',
      where: NOTICE_HOST.LIST,
      retry: () => {
        restoreDroppedPin(id, reload);
      },
    });
    ok = true;
    markMine(id);
    quietNote(translateTemplate('핀 #{id} 되살림', { id }));
  } catch (error) {}
  if (settled) settled();
  await reload();
  return ok;
}

export { restoreDroppedPin };
