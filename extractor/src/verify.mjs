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
 * Fatal outcomes are deliberately narrow (see `assessExtraction`): a challenge,
 * and a short body that neither names the article nor reads as prose.
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
const CJK_SPLIT = /([\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}]+)/u;

/** NFKC, lowercase, punctuation folded to single spaces. */
export function normalizeForMatch(text) {
  return String(text ?? '')
    .normalize('NFKC')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim();
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Return `{ sign, where }` for a challenge page, or null.
 *
 * Body signatures are decisive. A title hit is only a suspicion — "Access
 * Denied: A Year Inside the Filter" is a legitimate article title — so the
 * caller weighs it against the body before failing the extraction.
 */
export function detectChallenge({ title = '', text = '' } = {}) {
  const normalizedTitle = normalizeForMatch(title);
  for (const sign of CHALLENGE_TITLE_SIGNS) {
    if (normalizedTitle.includes(sign)) return { sign, where: 'title' };
  }
  const head = normalizeForMatch(text).slice(0, 2000);
  for (const sign of CHALLENGE_BODY_SIGNS) {
    if (head.includes(sign)) return { sign, where: 'body' };
  }
  return null;
}

function pushSegments(word, seen) {
  // Splitting on a capture group keeps both sides: even indices are the
  // non-CJK chunks, odd indices the Han/kana runs they were split from.
  word.split(CJK_SPLIT).forEach((segment, index) => {
    if (!segment) return;
    if (index % 2 === 1) {
      if (segment.length === 1) seen.add(segment);
      for (let position = 0; position + 1 < segment.length; position += 1) {
        seen.add(segment.slice(position, position + 2));
      }
      return;
    }
    if (segment.length >= 3 && !LATIN_STOPWORDS.has(segment)) seen.add(segment);
  });
}

/**
 * Title tokens used for corroboration. Latin titles contribute words; CJK has
 * no spaces, so a Han run contributes its 2-grams instead (标题 "分布式系统" →
 * 分布/布式/式系/系统). Mixed-script words ("AI分布式") split per script.
 */
export function titleTokens(title) {
  const seen = new Set();
  for (const word of normalizeForMatch(title).split(/\s+/)) {
    if (word) pushSegments(word, seen);
  }
  return [...seen];
}

/** Latin tokens match on word boundaries, so "rapid" no longer matches "rapidly". */
function containsToken(body, token) {
  if (CJK_RUN.test(token)) return body.includes(token);
  const pattern = new RegExp(
    `(^|[^\\p{L}\\p{N}])${escapeRegExp(token)}(?![\\p{L}\\p{N}])`,
    'u',
  );
  return pattern.test(body);
}

/** Share of the title's tokens that reappear in the body. */
export function titleCorroboration({ title = '', markdown = '' } = {}) {
  const tokens = titleTokens(title);
  if (tokens.length === 0) return { ratio: 0, tokens: 0, verdict: 'unknown' };
  const body = normalizeForMatch(markdown);
  const hits = tokens.filter(token => containsToken(body, token)).length;
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
 * Fatal only when:
 *   - a challenge is present: a body signature always; a title signature while
 *     the body does not corroborate that title;
 *   - the body is short, never names the article, and does not read as prose.
 * A long body, a prose post, a render that merely grew slowly, or a title that
 * only resembles a challenge signature all save — marked weak.
 */
export function assessExtraction({
  result,
  method = 'static',
  staticBody = '',
  allowVideoStub = false,
} = {}) {
  const markdown = String(result?.markdown ?? '');
  const length = markdown.trim().length;

  const challenge = detectChallenge({ title: result?.title ?? '', text: markdown });
  const corroboration = titleCorroboration({ title: result?.title ?? '', markdown });

  // A challenge is a challenge even when the page also carries a video tag.
  if (challenge && (challenge.where === 'body' || corroboration.verdict !== 'strong')) {
    return { verdict: 'challenge', reason: challenge.sign };
  }

  // A video page legitimately has a caption-only body. A title that merely
  // resembles a challenge signature also lands here.
  if (allowVideoStub && Array.isArray(result?.videos) && result.videos.length > 0) {
    return { verdict: 'strong', reason: 'video' };
  }

  if (challenge) return { verdict: 'weak', reason: '' };

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
    // The gain heuristic is a hint, not a verdict: fail-open wins, so this only
    // downgrades to weak instead of discarding a possible real article.
    return { verdict: 'weak', reason: 'no-render-gain', corroboration };
  }

  return {
    verdict: corroboration.verdict === 'strong' ? 'strong' : 'weak',
    reason: '',
    corroboration,
  };
}
