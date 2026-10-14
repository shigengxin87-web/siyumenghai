import test from 'node:test';
import assert from 'node:assert/strict';
import { extractUrl, mediaHost, publicIPv4, shape } from './gateway.mjs';

test('extractUrl accepts xhs share text and removes punctuation', () => {
  assert.equal(extractUrl('复制 https://xhslink.com/aBc123。'), 'https://xhslink.com/aBc123');
});

test('extractUrl rejects unrelated hosts', () => {
  assert.throws(() => extractUrl('https://example.com/explore/abc'), /仅支持小红书/);
});

test('media host allowlist is boundary safe', () => {
  assert.equal(mediaHost('sns-video-bd.xhscdn.com'), true);
  assert.equal(mediaHost('xhscdn.com.example.org'), false);
});

test('private IP ranges are rejected', () => {
  assert.equal(publicIPv4('127.0.0.1'), false);
  assert.equal(publicIPv4('192.168.1.2'), false);
  assert.equal(publicIPv4('8.8.8.8'), true);
});

test('shape issues only same-origin tickets and keeps metadata', () => {
  const result = shape({platform:'xiaohongshu',id:'67abcdef0123456789abcdef',title:'测试',video:'https://sns-video-bd.xhscdn.com/a.mp4',cover:'https://sns-img-bd.xhscdn.com/a.jpg',images:[],web_url:'https://www.xiaohongshu.com/explore/67abcdef0123456789abcdef'});
  assert.match(result.video, /^\/api\/xhs\/media\/[a-f0-9]{48}$/);
  assert.equal(result.title, '测试');
});
