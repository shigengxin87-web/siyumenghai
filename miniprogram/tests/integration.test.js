const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('fs'),path=require('path'),vm=require('vm');
const root=path.resolve(__dirname,'..');const {Utf8Decoder,EventReader}=require('../utils/chat-stream');
function page(file,api={}) {
 let definition;const context={getApp:()=>({globalData:{agent:{apiUrl:'https://siyumenghai.cn/api/agent/chat'}}}),Page:p=>definition=p,wx:api,require:p=>require(path.resolve(root,path.dirname(file),p)),console,Uint8Array,Array,Date,Math};
 vm.runInNewContext(fs.readFileSync(path.join(root,file),'utf8'),context);
 const p={...definition,data:JSON.parse(JSON.stringify(definition.data))};p.setData=patch=>Object.assign(p.data,patch);return p;
}
test('registered navigation paths and tab actions match one app',()=>{
 const a=JSON.parse(fs.readFileSync(path.join(root,'app.json')));const pages=new Set(a.pages);const tabs=new Set(a.tabBar.list.map(t=>t.pagePath));
 assert.deepEqual(a.tabBar.list.map(t=>t.text),['首页','技巧','AI问答','讨论','我的']);
 function walk(dir){for(const entry of fs.readdirSync(dir,{withFileTypes:true})){const f=path.join(dir,entry.name);if(entry.isDirectory())walk(f);else if(entry.name.endsWith('.js')){const text=fs.readFileSync(f,'utf8');for(const m of text.matchAll(/\/pages\/([\w/-]+)(?:[?'"`])/g))assert.ok(pages.has('pages/'+m[1]),f+' references '+m[1]);for(const m of text.matchAll(/switchTab\(\{\s*url:\s*['"]\/([^?'"`]+)/g))assert.ok(tabs.has(m[1]),f+' switchTab mismatch');}}}
 walk(path.join(root,'pages'));for(const p of pages)for(const ext of ['js','json','wxml','wxss'])assert.ok(fs.existsSync(path.join(root,p+'.'+ext)),p+'.'+ext);
});
test('member avatars all exist in upload package',()=>{const {members}=require('../data/members');for(const m of members)assert.ok(fs.existsSync(path.join(root,m.avatar)),m.avatar);});
test('UTF8 handles every split including chinese and emoji',()=>{const text='回答：你好😀\n';const bytes=Buffer.from(text);for(let i=0;i<=bytes.length;i++){const d=new Utf8Decoder();const ab=b=>b.buffer.slice(b.byteOffset,b.byteOffset+b.length);assert.equal(d.push(ab(bytes.subarray(0,i)))+d.push(ab(bytes.subarray(i))),text);}});
test('event frames work across chunks and with unterminated final line',()=>{const events=[];const r=new EventReader(e=>events.push(e));r.push('{"type":"delta","text":"你',false);r.push('好"}\n{"type":"done","text":"你好"}',true);assert.equal(events.length,2);assert.equal(events[1].text,'你好');});
test('HTTP failure is retryable, normal answers mentioning timeout are not',()=>{
 let o,chunk,headers;const store={};const api={getStorageSync:k=>store[k],setStorageSync:(k,v)=>store[k]=v,request:v=>{o=v;return{abort(){},onChunkReceived(fn){chunk=fn},onHeadersReceived(fn){headers=fn}}}};
 const p=page('pages/chat/chat.js',api);p.onLoad();p.data.input='question';p.send();headers({statusCode:500});chunk({data:Buffer.from('provider secret').buffer});o.success({statusCode:500,data:'secret'});o.complete();assert.equal(p.data.messages.at(-1).canRetry,true);assert.ok(!p.data.messages.at(-1).text.includes('secret'));
 p.data.input='next';p.send();const data='{"type":"done","text":"解释网络超时的原因"}\n';o.success({statusCode:200,data});o.complete();assert.equal(p.data.messages.at(-1).canRetry,false);assert.equal(p.data.sending,false);
});
test('late callbacks cannot mutate cleared/unloaded page and clear creates session',()=>{
 let o;const store={};const api={getStorageSync:k=>store[k],setStorageSync:(k,v)=>store[k]=v,showModal:v=>v.success({confirm:true}),request:v=>{o=v;return{abort(){}}}};
 const p=page('pages/chat/chat.js',api);p.onLoad();const id=p.conversation;p.clearChat();assert.notEqual(p.conversation,id);p.data.input='question';p.send();const before=JSON.stringify(p.data);p.onUnload();o.success({statusCode:200,data:'{"type":"done","text":"late"}\n'});o.complete();assert.equal(JSON.stringify(p.data),before);
});
