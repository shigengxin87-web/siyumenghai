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

test('shape forwards cache hit flag and duration', () => {
  const result = shape({platform:'xiaohongshu',id:'67abcdef0123456789abcdef',title:'缓存命中',cached:true,duration:'52',cover:'',images:[],web_url:'https://www.xiaohongshu.com/explore/67abcdef0123456789abcdef'});
  assert.equal(result.cached, true);
  assert.equal(result.duration, '52');
});

test('shape routes author payload into note list with ticketed covers', () => {
  const result = shape({
    platform:'xiaohongshu', kind:'author', cached:true,
    author:{id:'user1', nickname:'海边日记', web_url:'https://www.xiaohongshu.com/user/profile/user1'},
    notes:[
      {id:'67abcdef0123456789abcdef', type:'video', title:'日落', cover:'https://sns-img-bd.xhscdn.com/cover.jpg', time:1, web_url:'https://www.xiaohongshu.com/explore/67abcdef0123456789abcdef'},
      {id:'', type:'image', title:'应过滤', cover:'', time:null, web_url:''},
    ],
  });
  assert.equal(result.kind, 'author');
  assert.equal(result.author.nickname, '海边日记');
  assert.equal(result.notes.length, 1);
  assert.equal(result.notes[0].type, 'video');
  assert.match(result.notes[0].cover, /^\/api\/xhs\/media\/[a-f0-9]{48}$/);
});
