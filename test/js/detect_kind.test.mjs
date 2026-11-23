// Run: node --test test/js/detect_kind.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { detectKind } from '../../src/components/home_chat/detect_kind.js';

const CASES = [
  ['A perfume bottle on wet black stone, studio photo', 'image'],
  ['make an image of a cat astronaut', 'image'],
  ['poster for a summer sale', 'image'],
  ['logo for a coffee shop called Dune', 'image'],
  ['Slow dolly in on a barista pouring latte art', 'video'],
  ['a video of a photo shoot backstage', 'video'],
  ['animate image 1', 'video'],
  ['Drone shot over a desert road at sunrise', 'video'],
  ['film a dog surfing at sunset', 'video'],
  ['8 second clip of waves, 9:16', 'video'],
  ['Warm lo-fi beat with soft piano, 80 bpm', 'music'],
  ['compose a jingle for our bakery', 'music'],
  ['uplifting cinematic soundtrack for a launch', 'music'],
  ['write a song about the sea', 'music'],
  ['voice-over: Welcome to our store', 'voice'],
  ['narrate this: the city never sleeps', 'voice'],
  ['say welcome to the demo in a warm voice', 'voice'],
  ['read this aloud please', 'voice'],
  ['A 30-second ad for an electric bike in the city', 'film'],
  ['make a short film about a lighthouse keeper', 'film'],
  ['a commercial for our new sneakers', 'film'],
  ['trailer for a sci-fi movie', 'film'],
  ['a product photo, no music', 'image'],
  ['a video without voice', 'video'],
  ['how does the film feature work', null],
  ['what can you make?', null],
  ['why did the video fail?', null],
  ['can you make a video of a fox in the snow?', 'video'],
  ['hello', null],
  ['a red bicycle in the rain', null],
  ['thanks!', null],
  ['tell me a story', null],
  ['make me a story about a robot', 'film'],
  ['صورة لزجاجة عطر على حجر أسود', 'image'],
  ['فيديو لطائرة فوق الصحراء', 'video'],
  ['أغنية هادئة مع بيانو', 'music'],
  ['تعليق صوتي: أهلا بكم', 'voice'],
  ['فيلم قصير عن حارس منارة', 'film'],
  ['كيف تعمل ميزة الفيلم', null],
];

for (const [text, want] of CASES) {
  test(`${JSON.stringify(text)} -> ${want}`, () => {
    const got = detectKind(text);
    assert.equal(got ? got.kind : null, want);
  });
}
