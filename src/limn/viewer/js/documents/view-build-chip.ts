import { translateTemplate, translate } from '../platform/i18n.ts';
import { tableEntry } from '../platform/tables.ts';
import { PULL_STATE } from '../app/rules-tables.ts';

function buildChipText(build: BuildStatus) {
  const label =
    tableEntry(
      { pull: '원격 main 당겨오는 중', copy: '원고 복사 중', latex: 'LaTeX 컴파일 중', render: '쪽 그리는 중' },
      build.phase,
    ) || '재빌드 중';
  const elapsed = Math.round(build.elapsed_s || 0),
    last = build.last_s ? ' ' + translateTemplate('(지난번 {s}초)', { s: Math.round(build.last_s) }) : '';
  return translate(label) + ' · ' + translateTemplate('{s}초', { s: elapsed }) + last;
}
// --git-pull (docs/handbook/build-sync.md §재빌드 전 원격 main 당겨오기): appends one line about the pull result to the
// build's completion (the status line's message, or the error panel's title). ok gets the applied commit range,
// skipped/error just the reason - up_to_date has nothing worth reporting, so nothing is appended.
function pullSuffix(build: BuildStatus) {
  const pull = build && build.pull;
  if (!pull || !pull.state) return '';
  if (pull.state === PULL_STATE.OK)
    return (
      ' · ' +
      translateTemplate('원격 반영 {range}', {
        range: String(pull.head_before || '?').slice(0, 7) + '..' + String(pull.head_after || '?').slice(0, 7),
      })
    );
  if (pull.state === PULL_STATE.SKIPPED || pull.state === PULL_STATE.ERROR)
    return (
      ' · ' +
      translateTemplate(pull.state === PULL_STATE.ERROR ? 'git pull 실패({reason})' : 'git pull 건너뜀({reason})', {
        reason: pull.reason || '?',
      })
    );
  return '';
}
export { buildChipText, pullSuffix };
