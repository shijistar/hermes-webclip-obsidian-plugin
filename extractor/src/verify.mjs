/**
 * Post-extraction verification.
 *
 * The quality gate only looks at shape (a title, enough characters). A bot
 * challenge page, a navigation shell and a paywall teaser all pass it, so the
 * extractor confirms "success" and the note is written from the wall itself.
 * This module answers the question the gate cannot: does the rendered body
 * actually contain the article the title promises?
 *
 * Everything here is local string work — no extra network, no new config.
 */

export const MIN_LENGTH_FOR_WEAK_PASS = 800;
export const STRONG_RATIO = 0.6;
export const WEAK_RATIO = 0.25;
export const RENDER_GAIN_RATIO = 1.2;

/** Titles a challenge page puts in `<title>`; matched after normalization. */
export const CHALLENGE_TITLE_SIGNS = [
  'just a moment',
  'attention required',
  'checking your browser',
  'verify you are human',
  'are you a robot',
  'access denied',
  'security check',
  'one more step',
  '请稍候',
  '正在验证',
  '安全验证',
  '访问受限',
];

/** Phrases that only appear on an interstitial body, not on an article. */
export const CHALLENGE_BODY_SIGNS = [
  'enable javascript and cookies to continue',
  'cf-browser-verification',
  'checking your browser before accessing',
  'verify you are human',
  'slide to verify',
  '请完成安全验证',
  '滑动验证',
];

const LATIN_STOPWORDS = new Set([
  'the', 'and', 'for', 'with', 'from', 'that', 'this', 'your', 'you', 'are',
  'was', 'were', 'has', 'have', 'had', 'not', 'but', 'its', 'it', 'of', 'to',
  'in', 'on', 'at', 'by', 'as', 'an', 'a', 'is', 'or', 'be', 'how', 'why',
]);

const CJK_RUN = /^[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}]+$/u;

/** NFKC, lowercase, punctuation folded to single spaces. */
export function normalizeForMatch(text) {
  return String(text ?? '')
    .normalize('NFKC')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim();
}

/**
 * Return the matched challenge signature, or '' when the page looks genuine.
 * Title hits are decisive; body hits only look at the head of the document so
 * a real article quoting "verify you are human" is not rejected.
 */
export function detectChallenge({ title = '', text = '' } = {}) {
  const normalizedTitle = normalizeForMatch(title);
  for (const sign of CHALLENGE_TITLE_SIGNS) {
    if (normalizedTitle.includes(sign)) return sign;
  }
  const head = normalizeForMatch(text).slice(0, 2000);
  for (const sign of CHALLENGE_BODY_SIGNS) {
    if (head.includes(sign)) return sign;
  }
  return '';
}

/**
 * Title tokens used for corroboration. Latin titles contribute words; CJK has
 * no spaces, so a Han run contributes its 2-grams instead (标题 "分布式系统" →
 * 分布/布式/式系/系统).
 */
export function titleTokens(title) {
  const seen = new Set();
  for (const word of normalizeForMatch(title).split(/\s+/)) {
    if (!word) continue;
    if (CJK_RUN.test(word)) {
      if (word.length === 1) seen.add(word);
      for (let index = 0; index + 1 < word.length; index += 1) {
        seen.add(word.slice(index, index + 2));
      }
      continue;
    }
    if (word.length >= 3 && !LATIN_STOPWORDS.has(word)) seen.add(word);
  }
  return [...seen];
}

/** Share of the title's tokens that reappear in the body. */
export function titleCorroboration({ title = '', markdown = '' } = {}) {
  const tokens = titleTokens(title);
  if (tokens.length === 0) return { ratio: 0, tokens: 0, verdict: 'unknown' };
  const body = normalizeForMatch(markdown);
  const hits = tokens.filter(token => body.includes(token)).length;
  const ratio = hits / tokens.length;
  const verdict = ratio >= STRONG_RATIO ? 'strong' : ratio >= WEAK_RATIO ? 'weak' : 'none';
  return { ratio, tokens: tokens.length, verdict };
}

/** Prose has sentence terminators; navigation chrome and walls do not. */
function looksLikeProse(text) {
  const terminators = text.match(/[。！？!?]|\.\s/g);
  return (terminators ? terminators.length : 0) >= 5;
}

/**
 * Classify an extraction as strong / weak / challenge / fake.
 *
 * Fail-open by design: only two combinations are fatal — a challenge page, and
 * a body that neither echoes the title, nor reads as prose, nor carries enough
 * text to be an article. A long body whose heading was rewritten still passes,
 * marked weak.
 */
export function assessExtraction({
  result,
  method = 'static',
  staticBody = '',
  allowVideoStub = false,
} = {}) {
  const markdown = String(result?.markdown ?? '');
  const length = markdown.trim().length;

  // A video page legitimately has a caption-only body.
  if (allowVideoStub && Array.isArray(result?.videos) && result.videos.length > 0) {
    return { verdict: 'strong', reason: 'video' };
  }

  const challenge = detectChallenge({ title: result?.title ?? '', text: markdown });
  if (challenge) return { verdict: 'challenge', reason: challenge };

  const corroboration = titleCorroboration({ title: result?.title ?? '', markdown });

  // A short body that never names the article and does not read as prose is a
  // shell or a wall. Real short posts still save — they just save as weak.
  if (
    corroboration.verdict === 'none' &&
    length < MIN_LENGTH_FOR_WEAK_PASS &&
    !looksLikeProse(markdown)
  ) {
    return { verdict: 'fake', reason: 'title-not-in-body', corroboration };
  }

  if (
    method === 'playwright' &&
    staticBody &&
    length < staticBody.trim().length * RENDER_GAIN_RATIO &&
    corroboration.verdict !== 'strong'
  ) {
    return { verdict: 'fake', reason: 'no-render-gain', corroboration };
  }

  return {
    verdict: corroboration.verdict === 'strong' ? 'strong' : 'weak',
    reason: '',
    corroboration,
  };
}
