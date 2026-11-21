import assert from 'node:assert/strict';
import test from 'node:test';

import {
  assessExtraction,
  detectChallenge,
  titleCorroboration,
  titleTokens,
} from '../src/verify.mjs';

test('detectChallenge recognises an English interstitial title', () => {
  assert.deepEqual(detectChallenge({ title: 'Just a moment...' }), {
    sign: 'just a moment',
    where: 'title',
  });
  assert.equal(detectChallenge({ title: 'Attention Required! | Cloudflare' }).where, 'title');
});

test('detectChallenge recognises a Chinese verification page', () => {
  assert.equal(detectChallenge({ title: '安全验证' }).sign, '安全验证');
  assert.equal(detectChallenge({ title: '请稍候…', text: '正在验证您的浏览器' }).where, 'title');
});

test('detectChallenge reports body signatures separately from titles', () => {
  const found = detectChallenge({
    title: 'Some article',
    text: 'Please enable JavaScript and cookies to continue.',
  });
  assert.equal(found.where, 'body');
});

test('detectChallenge ignores a genuine article that quotes the phrase deep in the body', () => {
  const filler = 'ordinary paragraph text. '.repeat(120); // > 2000 chars of head
  assert.equal(
    detectChallenge({ title: 'Bypassing bot gates', text: `${filler}verify you are human appears here` }),
    null,
  );
});

test('titleTokens splits CJK titles into 2-grams and drops Latin stopwords', () => {
  const cjk = titleTokens('分布式系统的可靠性');
  assert.ok(cjk.includes('分布'));
  assert.ok(cjk.includes('可靠'));
  assert.equal(cjk.some(token => token.length > 2), false);
  const latin = titleTokens('The Secure Clipping of Articles');
  assert.ok(latin.includes('secure'));
  assert.ok(latin.includes('clipping'));
  assert.equal(latin.includes('the'), false);
});

test('titleTokens splits a mixed-script word per script', () => {
  const tokens = titleTokens('AI分布式系统的可靠性');
  assert.ok(tokens.includes('分布'));
  assert.ok(tokens.includes('可靠'));
  // The whole word must not survive as one latin token, or nothing would match.
  assert.equal(tokens.some(token => token.includes('ai')), false);
});

test('titleCorroboration rates a matching Latin body as strong', () => {
  const result = titleCorroboration({
    title: 'Secure Web Clipping Without Surprises',
    markdown: 'Secure web clipping starts with defaults. Clipping without surprises is possible.',
  });
  assert.equal(result.verdict, 'strong');
  assert.ok(result.ratio >= 0.6);
});

test('titleCorroboration matches Latin tokens on word boundaries only', () => {
  const result = titleCorroboration({
    title: 'Rapid Response',
    markdown: 'They were rapidly responding to the incident.',
  });
  assert.equal(result.verdict, 'none');
});

test('titleCorroboration rates a matching CJK body as strong', () => {
  const result = titleCorroboration({
    title: '分布式系统的可靠性设计',
    markdown: '本文讨论分布式系统在可靠性设计上的取舍，以及共识算法的代价。',
  });
  assert.equal(result.verdict, 'strong');
});

test('detectChallenge normalises hyphenated body signatures', () => {
  const found = detectChallenge({
    title: 'Some article',
    text: 'cf-browser-verification is running, please wait',
  });
  assert.equal(found.where, 'body');
  assert.equal(found.sign, 'cf browser verification');
});

test('a body signature outranks a corroborated challenge title', () => {
  const body =
    'Verify you are human. Please enable JavaScript and cookies to continue. '.repeat(5);
  const assessment = assessExtraction({
    result: { title: 'Verify you are human', markdown: body },
    method: 'static',
  });
  assert.equal(assessment.verdict, 'challenge');
});

test('assessExtraction rejects a challenge page', () => {
  const assessment = assessExtraction({
    result: { title: 'Just a moment...', markdown: 'Checking your browser before accessing the site. '.repeat(20) },
    method: 'static',
  });
  assert.equal(assessment.verdict, 'challenge');
});

test('assessExtraction keeps a real article whose title only looks like a challenge', () => {
  const body =
    'Access denied is a common outcome in content moderation. ' +
    'This year inside the filter taught us how appeals work. '.repeat(20);
  const assessment = assessExtraction({
    result: { title: 'Access Denied: A Year Inside the Filter', markdown: body },
    method: 'static',
  });
  assert.notEqual(assessment.verdict, 'challenge');
});

test('assessExtraction still rejects a challenge body under a benign title', () => {
  const assessment = assessExtraction({
    result: {
      title: 'Access Denied: A Year Inside the Filter',
      markdown: 'Please enable JavaScript and cookies to continue. '.repeat(5),
    },
    method: 'static',
  });
  assert.equal(assessment.verdict, 'challenge');
});

test('assessExtraction rejects a navigation shell that does not echo the title', () => {
  const assessment = assessExtraction({
    result: {
      title: 'How Consensus Algorithms Work',
      markdown: 'Home Products Pricing Docs Blog Careers Contact Login Sign up '.repeat(8),
    },
    method: 'playwright',
  });
  assert.equal(assessment.verdict, 'fake');
  assert.equal(assessment.reason, 'title-not-in-body');
});

test('assessExtraction keeps a long body with a rewritten title, marked weak', () => {
  const body = '这是一个关于可靠性设计的段落。'.repeat(120);
  const assessment = assessExtraction({
    result: { title: 'How Consensus Algorithms Work', markdown: body },
    method: 'static',
  });
  assert.equal(assessment.verdict, 'weak');
});

test('assessExtraction keeps a short prose post that never repeats its title', () => {
  const body =
    '今天在研究一个新问题。关键在于边界条件。我先做了三组实验。第一组失败了。' +
    '第二组有了一点进展。第三组结果稳定。';
  const assessment = assessExtraction({
    result: { title: 'Reliability Notes', markdown: body },
    method: 'static',
  });
  assert.equal(assessment.verdict, 'weak');
});

test('assessExtraction rejects a short login wall with no prose', () => {
  const assessment = assessExtraction({
    result: {
      title: 'How Consensus Algorithms Work',
      markdown: 'Sign in to continue · Reading is for members · Subscribe',
    },
    method: 'static',
  });
  assert.equal(assessment.verdict, 'fake');
  assert.equal(assessment.reason, 'title-not-in-body');
});

test('assessExtraction accepts a caption-only video page', () => {
  const assessment = assessExtraction({
    result: { title: 'Some talk', markdown: 'A caption.', videos: [{ src: 'https://example.com/v.mp4' }] },
    method: 'static',
    allowVideoStub: true,
  });
  assert.equal(assessment.verdict, 'strong');
  assert.equal(assessment.reason, 'video');
});

test('assessExtraction still rejects a challenge page that carries a video tag', () => {
  const assessment = assessExtraction({
    result: {
      title: 'Just a moment...',
      markdown: 'Checking your browser before accessing the site.',
      videos: [{ src: 'https://example.com/v.mp4' }],
    },
    method: 'static',
    allowVideoStub: true,
  });
  assert.equal(assessment.verdict, 'challenge');
});

test('assessExtraction downgrades a browser render that gained nothing, never discards it', () => {
  const body = '导航 首页 产品 价格 文档 '.repeat(80); // >= 800 chars, still no article
  const assessment = assessExtraction({
    result: { title: 'How Consensus Algorithms Work', markdown: body },
    method: 'playwright',
    staticBody: body,
  });
  assert.equal(assessment.verdict, 'weak');
  assert.equal(assessment.reason, 'no-render-gain');
});
