const API='/api/transcripts-test-tencent/jobs';
const PROFILE_API='/api/video/profile';
const STORAGE_KEY='siyumenghai_tencent_transcript_test_v1';
const form=document.querySelector('#query-form');
const input=document.querySelector('#share-url');
const submitButton=document.querySelector('#submit-button');
const card=document.querySelector('#current-card');
const currentTitle=document.querySelector('#current-title');
const statusPill=document.querySelector('#status-pill');
const message=document.querySelector('#task-message');
const metrics=document.querySelector('#metrics');
const resultWrap=document.querySelector('#result-wrap');
const transcript=document.querySelector('#transcript-text');
const playerWrap=document.querySelector('#player-wrap');
const player=document.querySelector('#video-player');
const historyList=document.querySelector('#history-list');
const historyEmpty=document.querySelector('#history-empty');
let currentJobId='';
let pollTimer=0;

function readHistory(){try{const value=JSON.parse(localStorage.getItem(STORAGE_KEY)||'[]');return Array.isArray(value)?value:[]}catch{return[]}}
function writeHistory(items){localStorage.setItem(STORAGE_KEY,JSON.stringify(items.slice(0,30)))}
function upsertHistory(item){const items=readHistory().filter(entry=>entry.jobId!==item.jobId&&entry.shareUrl!==item.shareUrl);items.unshift({...item,updatedAt:Date.now()});writeHistory(items);renderHistory()}
function validShareUrl(value){try{const url=new URL(value.trim());return url.protocol==='https:'&&url.hostname==='weixin.qq.com'&&url.pathname.startsWith('/sph/')?url.toString():''}catch{return''}}
function formatDuration(seconds){const value=Math.max(0,Number(seconds)||0);const minutes=Math.floor(value/60);return `${minutes}:${String(Math.round(value%60)).padStart(2,'0')}`}
function textWithoutLineBreaks(value){return String(value||'').replace(/[\r\n]/g,'')}
function formatTranscript(raw){
  const source=String(raw||'');
  if(!source)return{formatted:'',verified:true};
  const terminal='。！？!?；;';
  const soft='，、：:';
  const paragraphs=[];
  let paragraph='';
  let visibleChars=0;
  let sentences=0;
  for(const character of source){
    paragraph+=character;
    if(!/\s/.test(character))visibleChars+=1;
    if(terminal.includes(character))sentences+=1;
    const terminalBreak=terminal.includes(character)&&(sentences>=3||visibleChars>=120);
    const softBreak=soft.includes(character)&&visibleChars>=180;
    const hardBreak=visibleChars>=240;
    if(terminalBreak||softBreak||hardBreak){paragraphs.push(paragraph);paragraph='';visibleChars=0;sentences=0}
  }
  if(paragraph)paragraphs.push(paragraph);
  const formatted=paragraphs.join('\n\n');
  const verified=textWithoutLineBreaks(formatted)===textWithoutLineBreaks(source);
  return{formatted:verified?formatted:source,verified};
}
function statusLabel(status){return({queued:'等待处理',processing:'处理中',completed:'已完成',failed:'失败'})[status]||status||'未知'}
function setStatus(status,stage){statusPill.className=`status-pill ${status||''}`;statusPill.textContent=statusLabel(status);currentTitle.textContent=stage||statusLabel(status)}
function showMetrics(job){metrics.innerHTML=`<div class="metric"><strong>${formatDuration(job.video_duration_seconds)}</strong><span>视频时长</span></div><div class="metric"><strong>${Number(job.elapsed_seconds||0).toFixed(3)}秒</strong><span>生成耗时</span></div><div class="metric"><strong>${job.char_count||0}</strong><span>逐字稿字数</span></div><div class="metric"><strong>${formatDuration(job.coverage_end_seconds)}</strong><span>识别覆盖至</span></div>`;metrics.classList.remove('hidden')}
async function loadPlayer(shareUrl){try{const response=await fetch(`${PROFILE_API}?url=${encodeURIComponent(shareUrl)}`,{cache:'no-store'});if(!response.ok)throw new Error();const payload=await response.json();const feed=payload?.data?.data?.feedInfo||{};const url=feed?.h264VideoInfo?.videoUrl||feed.videoUrl||feed.originVideoUrl;if(!url)throw new Error();if(player.src!==url)player.src=url;playerWrap.classList.remove('hidden')}catch{playerWrap.classList.add('hidden')}}
function renderJob(job){card.classList.remove('hidden');currentJobId=job.id;setStatus(job.status,job.stage);message.textContent=job.error||(['queued','processing'].includes(job.status)?'任务正在后台继续处理，可以刷新页面或查看其他视频。':'');if(job.video_duration_seconds)showMetrics(job);else metrics.classList.add('hidden');if(job.status==='completed'&&job.text){const formatted=formatTranscript(job.text);transcript.value=formatted.formatted;resultWrap.classList.remove('hidden')}else{transcript.value='';resultWrap.classList.add('hidden')}upsertHistory({jobId:job.id,shareUrl:job.share_url,status:job.status,stage:job.stage,elapsed:job.elapsed_seconds,chars:job.char_count});loadPlayer(job.share_url)}
async function fetchJob(jobId,{makeCurrent=false}={}){const response=await fetch(`${API}/${encodeURIComponent(jobId)}`,{cache:'no-store'});if(!response.ok)throw new Error(response.status===404?'任务已过期':'状态查询失败');const job=await response.json();if(makeCurrent||jobId===currentJobId)renderJob(job);else upsertHistory({jobId:job.id,shareUrl:job.share_url,status:job.status,stage:job.stage,elapsed:job.elapsed_seconds,chars:job.char_count});return job}
function schedulePoll(){clearTimeout(pollTimer);if(!currentJobId)return;pollTimer=setTimeout(async()=>{try{const job=await fetchJob(currentJobId,{makeCurrent:true});if(['queued','processing'].includes(job.status))schedulePoll()}catch(error){message.textContent=error.message;schedulePoll()}},1800)}
async function submit(shareUrl){submitButton.disabled=true;submitButton.textContent='正在提交';try{const response=await fetch(API,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({share_url:shareUrl})});const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body.error||'任务提交失败');renderJob(body);schedulePoll()}finally{submitButton.disabled=false;submitButton.textContent='生成逐字稿'}}
function renderHistory(){const items=readHistory();historyEmpty.classList.toggle('hidden',items.length>0);historyList.innerHTML='';for(const item of items){const status=['queued','processing','completed','failed'].includes(item.status)?item.status:'';const node=document.createElement('article');node.className='history-item';node.innerHTML=`<div class="history-top"><div class="history-url"></div><span class="status-pill ${status}"></span></div><div class="history-meta"></div><div class="history-actions"><button type="button" data-view>查看任务</button><button type="button" class="secondary" data-copy>复制链接</button></div>`;node.querySelector('.history-url').textContent=item.shareUrl;node.querySelector('.status-pill').textContent=statusLabel(status);node.querySelector('.history-meta').textContent=item.chars?`${item.chars}字 · ${Number(item.elapsed||0).toFixed(3)}秒`:(item.stage||'等待查询');node.querySelector('[data-view]').onclick=async()=>{try{const job=await fetchJob(item.jobId,{makeCurrent:true});if(['queued','processing'].includes(job.status))schedulePoll();card.scrollIntoView({behavior:'smooth'})}catch(error){alert(error.message)}};node.querySelector('[data-copy]').onclick=()=>navigator.clipboard.writeText(item.shareUrl);historyList.appendChild(node)}}
form.addEventListener('submit',async event=>{event.preventDefault();const shareUrl=validShareUrl(input.value);if(!shareUrl){alert('请输入 https://weixin.qq.com/sph/ 开头的视频号分享链接。');return}try{await submit(shareUrl)}catch(error){alert(error.message)}});
document.querySelector('#copy-button').onclick=async()=>{await navigator.clipboard.writeText(transcript.value);message.textContent='逐字稿已复制。'};
document.querySelector('#refresh-all').onclick=async()=>{for(const item of readHistory()){try{await fetchJob(item.jobId,{makeCurrent:item.jobId===currentJobId})}catch{}}renderHistory()};
renderHistory();
const pending=readHistory().find(item=>['queued','processing'].includes(item.status));
const latest=pending||readHistory()[0];
if(latest){fetchJob(latest.jobId,{makeCurrent:true}).then(job=>{if(['queued','processing'].includes(job.status))schedulePoll()}).catch(()=>{})}
