import assert from 'node:assert/strict';
import test from 'node:test';

import { waitForChallengeClear } from '../src/extractor.mjs';

const page = (title, text) => ({
  title: async () => title,
  evaluate: async () => text,
});

const ARTICLE = 'Access denied is a common outcome in content moderation. '.repeat(40);

test('a challenge-like title over an article body is not fatal', async () => {
  const blocked = await waitForChallengeClear(
    page('Access Denied: A Year Inside the Filter', ARTICLE),
    0,
  );
  assert.equal(blocked, null);
});

test('a body signature is fatal even when the title looks harmless', async () => {
  const blocked = await waitForChallengeClear(
    page('Some article', 'Please enable JavaScript and cookies to continue.'),
    0,
  );
  assert.equal(blocked.where, 'body');
  // The sign travels to the error so the caller can name the marker.
  assert.equal(blocked.sign, 'enable javascript and cookies to continue');
});

test('an interstitial that clears inside the window continues', async () => {
  let reads = 0;
  const clearing = {
    title: async () => (reads === 0 ? 'Just a moment...' : 'The article'),
    evaluate: async () => {
      const first = reads === 0;
      reads += 1;
      return first ? 'Checking your browser before accessing the site.' : ARTICLE;
    },
  };
  const blocked = await waitForChallengeClear(clearing, 1_500);
  assert.equal(blocked, null);
});

test('a page with no challenge costs no settle time', async () => {
  const started = Date.now();
  const blocked = await waitForChallengeClear(page('An article', ARTICLE), 12_000);
  assert.equal(blocked, null);
  assert.ok(Date.now() - started < 500);
});
