import { Claims, access } from './claims.mjs';

export function runTests(tsv) {
  const lines = tsv.trim().split(/\r?\n/);
  const header = lines.shift().split('\t');
  const claims = new Claims();
  const results = [];
  function check(name, condition) { if (!condition) throw new Error(name); results.push(name); }
  for (const line of lines) {
    const row = Object.fromEntries(line.split('\t').map((value, i) => [header[i], value]));
    let attempt = claims.attempt(row.session, row.site);
    if (row.action === 'mark') attempt = claims.mark(row.session, row.pet, row.site);
    else if (row.action === 'submit') claims.submit(attempt, row.capture);
    else if (row.action === 'resume') claims.resume(attempt);
    else if (row.action === 'resolve') claims.resolve(attempt, row.capture, row.outcome);
    else throw new Error(`unknown fixture action ${row.action}`);
    const site = claims.sites.get(row.site);
    check(row.step, site.occupancy?.pet === row.owner && site.occupancy?.certification === row.certification &&
      attempt.disposition === row.disposition && attempt.photo === row.photo);
  }
  check('accuracy radius boundary', access({recording: true, trusted: true, distance: 15, accuracy: 5}) === 'READY');
  check('accuracy outside', access({recording: true, trusted: true, distance: 15, accuracy: 6}) === 'APPROACHING');
  check('stale fix', access({recording: true, trusted: true, distance: 0, accuracy: 1, age: 11}) === 'UNAVAILABLE');
  check('paused', access({recording: false, trusted: true, distance: 0, accuracy: 1}) === 'UNAVAILABLE');
  check('mock location', access({recording: true, trusted: false, distance: 0, accuracy: 1}) === 'UNAVAILABLE');
  const concurrent = new Claims();
  const first = concurrent.mark('s1', 'p1', 'A');
  concurrent.submit(first, 'c1');
  const second = concurrent.mark('s2', 'p2', 'A');
  concurrent.submit(second, 'c2');
  concurrent.resolve(second, 'c2', 'ACCEPTED');
  let blocked = false;
  try { concurrent.resolve(first, 'c1', 'ACCEPTED'); } catch (e) { blocked = e.message === 'site_changed'; }
  check('concurrent result never overwrites silently', blocked && concurrent.sites.get('A').occupancy.pet === 'p2');
  return results;
}
