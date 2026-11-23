/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/**
 * detectKind(text): what the Home box is being asked to make, read live while
 * the person types. Returns { kind, word } or null (plain chat).
 *
 * Rules, in order:
 * 1. Questions about the app ("how does the film feature work?") stay chat,
 *    unless they ask for something ("can you make a video of...").
 * 2. Each media word scores for its type. A word right after a making verb
 *    ("make a song", "generate a photo") counts double, and the first media
 *    word in the text wins a tie ("a video of a photo shoot" is a video).
 * 3. "no music", "without voice", "not a video" don't count.
 * 4. A bare description with no media word ("a red bicycle in the rain")
 *    stays chat: the chat picks for itself.
 *
 * English and Arabic. Pure function, no DOM: test/js/detect_kind.test.mjs.
 */

const WORDS = {
  image: [
    'image', 'images', 'photo', 'photos', 'picture', 'pictures', 'pic', 'poster', 'posters', 'logo', 'logos',
    'illustration', 'drawing', 'painting', 'portrait', 'render', 'thumbnail', 'banner', 'wallpaper', 'headshot',
    'product shot', 'still', 'photograph', 'artwork', 'icon', 'sticker', 'mockup', 'flyer',
    'صورة', 'صور', 'رسمة', 'شعار', 'ملصق', 'لوحة',
  ],
  video: [
    'video', 'videos', 'clip', 'clips', 'footage', 'animation', 'animate', 'animated', 'b-roll', 'reel', 'reels',
    'drone shot', 'dolly', 'timelapse', 'time-lapse', 'slow motion', 'slow-mo', 'cinemagraph',
    'فيديو', 'مقطع', 'تحريك', 'لقطة',
  ],
  music: [
    'music', 'song', 'songs', 'beat', 'beats', 'track', 'tracks', 'jingle', 'soundtrack', 'melody', 'tune',
    'instrumental', 'lo-fi', 'lofi', 'score', 'theme music', 'background music', 'bpm', 'loop',
    'موسيقى', 'أغنية', 'لحن', 'نغمة',
  ],
  voice: [
    'voice', 'voiceover', 'voice-over', 'voice over', 'narrate', 'narration', 'narrator', 'read aloud', 'read this',
    'say', 'speak', 'speech', 'tts', 'text to speech', 'announcement', 'podcast intro', 'audio message',
    'صوت', 'تعليق صوتي', 'اقرأ', 'قل',
  ],
  film: [
    'film', 'short film', 'movie', 'ad', 'advert', 'commercial', 'trailer', 'story', 'storyboard', 'scenario',
    'short story', 'teaser', 'promo film', 'brand film', 'mini series',
    'فيلم', 'إعلان', 'قصة', 'دعاية',
  ],
};

const VERBS = [
  'make', 'create', 'generate', 'produce', 'draw', 'paint', 'design', 'render', 'shoot', 'film', 'animate',
  'compose', 'write', 'record', 'give me', 'build', 'turn', 'convert', 'i want', 'i need', "let's make", 'show me',
  'اصنع', 'أنشئ', 'انشئ', 'ارسم', 'صمم', 'أريد', 'اريد', 'حول', 'اعمل', 'سو',
];

const NEGATIONS = ['no', 'not', 'without', "don't", 'dont', 'never', 'بدون', 'لا', 'ليس', 'غير'];

// Starts of questions about the app rather than requests.
const QUESTION = /^(how|what|why|when|where|who|which|is|are|does|do|did|explain|tell me about)\b|^(كيف|ماذا|ما|لماذا|متى|هل|اشرح)(\s|$)/i;
const ASKS_FOR = /\b(can|could|would|will) you (please )?(make|create|generate|draw|design|animate|compose|write|turn|give)\b/i;

function escape(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// One regex per word: whole words in Latin script; Arabic may carry a prefix
// (ال, و, ب) so it only needs a boundary on the right.
function pattern(word) {
  const arabic = /[؀-ۿ]/.test(word);
  const body = escape(word).replace(/ /g, '[\\s-]+');
  return arabic ? new RegExp(`${body}(?![\\u0600-\\u06ff])`, 'g') : new RegExp(`(?<![\\w-])${body}(?![\\w-])`, 'gi');
}

const MATCHERS = Object.fromEntries(Object.entries(WORDS).map(([k, list]) => [k, list.map((w) => [w, pattern(w)])]));
const VERB_RE = new RegExp(`(?<![\\w])(${VERBS.map(escape).join('|')})(?![\\w])`, 'gi');

function negated(text, index) {
  const before = text.slice(Math.max(0, index - 14), index).toLowerCase().trim().split(/\s+/);
  const last = before.slice(-2);
  return last.some((w) => NEGATIONS.includes(w.replace(/[^\w؀-ۿ']/g, '')));
}

/** { kind, word } for the type the text asks for, or null. */
export function detectKind(raw) {
  const text = String(raw || '').trim();
  if (text.length < 3) return null;
  const lower = text.toLowerCase();
  const question = (QUESTION.test(lower) || /\?\s*$/.test(lower)) && !ASKS_FOR.test(lower);
  if (question) return null;

  const verbs = [];
  for (const m of lower.matchAll(VERB_RE)) verbs.push(m.index + m[0].length);

  const scores = {};
  const first = {};
  const found = {};
  for (const [kind, list] of Object.entries(MATCHERS)) {
    for (const [word, re] of list) {
      re.lastIndex = 0;
      for (const m of text.matchAll(re)) {
        if (negated(text, m.index)) continue;
        // "say" and "story" are common words: they only count after a verb.
        const weak = ['say', 'speak', 'story', 'ad', 'still', 'score', 'loop', 'icon', 'قل', 'قصة'].includes(word);
        const afterVerb = verbs.some((end) => m.index >= end && m.index - end <= 12);
        const sized = word === 'ad' && /(second|sec|minute|min|tv|video|radio|an|our)[\s-]+$/i.test(text.slice(0, m.index));
        if (weak && !afterVerb && !sized && m.index > 0) continue;
        const points = (afterVerb ? 2 : 1) + (word.includes(' ') ? 0.5 : 0);
        scores[kind] = (scores[kind] || 0) + points;
        if (first[kind] === undefined || m.index < first[kind]) { first[kind] = m.index; found[kind] = m[0]; }
      }
    }
  }
  // Animating something is always a video, whatever it animates.
  if (/(?<![w])animat(e|ed|ing)(?![w])|تحريك|حرك/i.test(text)) scores.video = (scores.video || 0) + 3;
  // "film" is also a verb ("film a dog surfing" is a video).
  if (scores.film && /^\s*film\s+(a|an|the|my|our|some)\b/i.test(text)) {
    scores.video = (scores.video || 0) + scores.film;
    first.video = Math.min(first.video ?? Infinity, 0);
    found.video = found.video || 'film';
    delete scores.film;
  }
  const kinds = Object.keys(scores);
  if (!kinds.length) return null;
  kinds.sort((a, b) => (scores[b] - scores[a]) || (first[a] - first[b]));
  return { kind: kinds[0], word: found[kinds[0]] };
}

export default detectKind;
