const { test, after } = require('node:test');
const assert = require('node:assert/strict');
const http = require('http'), fs = require('fs'), os = require('os'), path = require('path');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'sdh-agent-test-'));
process.env.AGENT_CONFIG_PATH = path.join(temp,'config.json');
fs.writeFileSync(process.env.AGENT_CONFIG_PATH,JSON.stringify({appkey:'test-only',upstream:'https://test.invalid'}));
const { handler } = require('./server');
const realFetch = global.fetch;
after(() => { global.fetch = realFetch; fs.rmSync(temp,{recursive:true,force:true}); });
function evt(Type, extra={}) { return 'data: '+JSON.stringify({Type,...extra})+'\n\n'; }
const added = (id,type) => evt('message.added',{Message:{MessageId:id,Type:type}});
const done = (id,text) => evt('message.done',{Message:{MessageId:id,Type:'reply',Status:'success',Contents:[{Type:'text',Text:text}]}});
async function request(raw, options={}) {
 let upstreamBody;
 global.fetch=async (_url,o)=>{ upstreamBody=JSON.parse(o.body); return new Response(raw,{status:options.status||200}); };
 const server=http.createServer(handler);await new Promise(r=>server.listen(0,'127.0.0.1',r));
 try {
  const body=JSON.stringify({user_id:'test-user',stream:options.stream!==false,stream_format:options.format===false?undefined:'events',conversation_id:options.conversation,messages:[{role:'user',content:[{type:'text',text:'hello'}]}]});
  const response=await new Promise((resolve,reject)=>{const req=http.request({hostname:'127.0.0.1',port:server.address().port,method:'POST',path:'/api/agent/chat',headers:{'Content-Type':'application/json'}},r=>{let text='';r.setEncoding('utf8');r.on('data',c=>text+=c);r.on('end',()=>resolve({status:r.statusCode,text}));});req.on('error',reject);req.end(body);});
  return {...response,upstreamBody};
 } finally { await new Promise(r=>server.close(r)); }
}
test('streams only reply IDs and applies authoritative replacements',async()=>{
 const raw=added('t','thought')+added('r','reply')+evt('text.delta',{MessageId:'t',Text:'secret reasoning'})+evt('text.delta',{MessageId:'r',Text:'旧'})+evt('text.replace',{MessageId:'r',Text:'新'})+done('r','最终答案');
 const r=await request(raw);const events=r.text.trim().split('\n').map(JSON.parse);
 assert.equal(events.at(-1).type,'done');assert.equal(events.at(-1).text,'最终答案');assert.ok(!r.text.includes('secret reasoning'));assert.ok(events.some(e=>e.type==='replace'&&e.text==='新'));
});
test('done-only and final line without newline are parsed',async()=>{const r=await request(done('r','你好😀').trim());assert.equal(JSON.parse(r.text.trim().split('\n').at(-1)).text,'你好😀');});
test('empty or interrupted replies never emit done',async()=>{for(const raw of ['',added('r','reply')+evt('text.delta',{MessageId:'r',Text:'partial'})]){const r=await request(raw);const events=r.text.trim().split('\n').map(JSON.parse);assert.equal(events.at(-1).type,'error');assert.ok(!events.some(e=>e.type==='done'));}});
test('provider errors are not exposed to visitors',async()=>{const r=await request(evt('error',{Error:{Message:'sensitive internal detail'}}));assert.ok(!r.text.includes('sensitive'));assert.equal(JSON.parse(r.text.trim()).type,'error');});
test('legacy plain text and non-stream JSON remain compatible',async()=>{const raw=added('r','reply')+evt('text.delta',{MessageId:'r',Text:'你好'})+done('r','你好');assert.equal((await request(raw,{format:false})).text,'你好');assert.equal(JSON.parse((await request(raw,{stream:false})).text).choices[0].message.content,'你好');});
test('new session resets cloud conversation, old clients retain stable ID',async()=>{const raw=done('r','ok');const a=await request(raw),b=await request(raw),c=await request(raw,{conversation:'new-session'});assert.equal(a.upstreamBody.ConversationId,b.upstreamBody.ConversationId);assert.notEqual(a.upstreamBody.ConversationId,c.upstreamBody.ConversationId);});
test('upstream HTTP errors return generic classified failures',async()=>{const r=await request('secret provider error',{status:429});assert.equal(r.status,429);assert.ok(!r.text.includes('secret'));});
