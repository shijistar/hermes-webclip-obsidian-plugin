import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import { errorPayload } from '../src/error-payload.mjs';
import { ExtractorError } from '../src/extractor.mjs';

const cliPath = fileURLToPath(new URL('../src/cli.mjs', import.meta.url));

test('CLI emits exactly one safe JSON error for a malformed URL', () => {
  const result = spawnSync(process.execPath, [cliPath, 'not a URL'], { encoding: 'utf8' });

  assert.notEqual(result.status, 0);
  assert.equal(result.stderr, '');
  assert.equal(result.stdout.trim().split('\n').length, 1);
  const output = JSON.parse(result.stdout);
  assert.deepEqual(Object.keys(output).sort(), ['code', 'error', 'ok']);
  assert.equal(output.ok, false);
  assert.equal(output.code, 'INVALID_URL');
  assert.doesNotMatch(output.error, /not a URL|stack|at file:/i);
});

test('a challenge error names its marker both ways', () => {
  const payload = errorPayload(
    new ExtractorError('CHALLENGE_PAGE', 'challenge', { marker: 'verify you are human' }),
  );

  assert.equal(payload.code, 'CHALLENGE_PAGE');
  assert.equal(payload.marker, 'verify you are human');
  assert.match(payload.error, /Marker: "verify you are human"/);
});

test('details outside the allowlist never reach the payload', () => {
  const payload = errorPayload(
    new ExtractorError('CHALLENGE_PAGE', 'challenge', {
      marker: 'ok',
      secret: 'should not escape',
      status: '403',
    }),
  );

  assert.deepEqual(Object.keys(payload).sort(), ['code', 'error', 'marker', 'ok']);
  assert.equal(payload.status, undefined);
});

test('a marker longer than 64 characters is truncated', () => {
  const payload = errorPayload(
    new ExtractorError('CHALLENGE_PAGE', 'challenge', { marker: 'x'.repeat(100) }),
  );

  assert.equal(payload.marker.length, 64);
});

test('an unknown code degrades to EXTRACTION_FAILED', () => {
  const payload = errorPayload(new ExtractorError('NOT_A_CODE', 'boom'));

  assert.equal(payload.code, 'EXTRACTION_FAILED');
  assert.equal(payload.error, 'Article extraction failed.');
});
