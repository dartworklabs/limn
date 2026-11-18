// Source paths for build coverage and static checks. Only imports from js/main.ts determine execution order.
import { readdirSync } from 'node:fs';
import { join, relative, sep } from 'node:path';

/** Every source file under js/, as a viewer-relative POSIX path. */
export function viewerModules(viewer) {
  return readdirSync(join(viewer, 'js'), { recursive: true, withFileTypes: true })
    .filter((entry) => !entry.isDirectory())
    .map((entry) => relative(viewer, join(entry.parentPath, entry.name)).split(sep).join('/'))
    .sort();
}
