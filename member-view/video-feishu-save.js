(function () {
  'use strict';
  const saveButton=document.querySelector('[data-feishu-save]');
  const dialog=document.querySelector('[data-feishu-dialog]');
  if (!saveButton || !dialog) return;
  const form=dialog.querySelector('form');
  const status=document.querySelector('[data-feishu-status]');
  const openLink=document.querySelector('[data-feishu-open]');
  const retryButton=document.querySelector('[data-feishu-retry]');
  const ownerKey='siyumenghai-feishu-owner-v1';
  const jobsKey='siyumenghai-feishu-deliveries-v1';
  const endpoint='/api/feishu-sync';
  let config=null;
  let timer=0;
  let currentJob='';
  let busy=false;
  let checkedShare='';
  let polls=0;
  let epoch=0;

  function read(key,fallback) { try { return JSON.parse(localStorage.getItem(key)||'null')||fallback; } catch { return fallback; } }
  function share() { return document.querySelector('[data-video-result]')?.dataset.videoShareUrl||''; }
  function message(text,error=false) { status.textContent=text;status.classList.toggle('is-error',error); }
  function owner(create=false) {
    let value=localStorage.getItem(ownerKey)||'';
    if (!value && create) {
      value=Array.from(crypto.getRandomValues(new Uint8Array(32)),n=>n.toString(16).padStart(2,'0')).join('');
      localStorage.setItem(ownerKey,value);
    }
    return value;
  }
  async function api(path,body) {
    const controller=new AbortController();
    const timeout=setTimeout(()=>controller.abort(),18000);
    try {
      const response=await fetch(endpoint+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','Authorization':'Bearer '+owner(!!body)},body:body?JSON.stringify(body):undefined,signal:controller.signal,cache:'no-store'});
      const result=await response.json().catch(()=>{throw new Error('保存服务暂时没有响应，请稍后再试。');});
      if (!response.ok) throw new Error(result.error||'飞书保存服务暂时不可用');
      return result;
    } finally { clearTimeout(timeout); }
  }
  async function loadConfig() {
    if (!owner()) return config={configured:false};
    return config=await api('/connection');
  }
  function setLink(url,label) {
    openLink.hidden=!url;
    if (url) { openLink.href=url;openLink.textContent=label; }
  }
  function remember(source,id) {
    const jobs=read(jobsKey,{});delete jobs[source];jobs[source]=id;
    try { localStorage.setItem(jobsKey,JSON.stringify(Object.fromEntries(Object.entries(jobs).slice(-20)))); } catch { /* Server status remains available during this visit. */ }
  }
  function showDelivery(job,source) {
    if (source!==share()) return;
    currentJob=job.request_id;
    retryButton.hidden=true;
    if (job.status==='confirmed') {
      message('已保存到飞书。再次保存会更新同一条记录。');
      setLink(job.record_url,'查看记录');
    } else if (job.status==='error') {
      message(job.error||'飞书未接收，请检查配置后重试。',true);
      setLink(config?.table_url,'打开素材库');
    } else {
      message(job.error||'已发送，待飞书确认写入。');
      setLink(config?.table_url,'打开素材库');
      retryButton.hidden=job.retry_after>0;
      clearTimeout(timer);
      if (polls++<30) timer=setTimeout(()=>checkDelivery(job.request_id,source),3000);
      else message('仍待飞书确认，请到素材库检查；修复流程后可重试发送。');
    }
  }
  async function checkDelivery(id,source) {
    const version=epoch;
    try { const result=await api('/deliveries/'+encodeURIComponent(id));if(version===epoch)showDelivery(result,source); }
    catch {
      if (source===share() && version===epoch) message('暂时无法查询保存结果，稍后可点击保存重新检查。',true);
    }
  }
  async function settings() {
    dialog.showModal();
    const feedback=dialog.querySelector('[data-feishu-config-status]');
    feedback.textContent='';
    try {
      const value=await loadConfig();
      form.elements.name.value=value.name||'我的视频素材库';
      form.elements.table_url.value=value.table_url||'';
      form.elements.webhook_url.required=!value.configured;
      form.elements.webhook_token.required=!value.configured;
      feedback.textContent=value.configured?'已配置。接收地址和凭证留空时保留原配置。':'';
    } catch { feedback.textContent='暂时无法读取配置，请稍后再试。'; }
  }
  async function save(retry=false) {
    if (busy) return;
    const source=share();
    const version=epoch;
    const textNode=document.querySelector('[data-transcript-corrected-text]');
    if (!source || !textNode?.value.trim()) return message('请先生成逐字稿。',true);
    if (!textNode.readOnly) return message('文案尚未保存，请先点击“保存”再保存到飞书。',true);
    busy=true;saveButton.disabled=true;retryButton.disabled=true;
    try {
      if (!config?.configured) await loadConfig();
      if (!config?.configured) { await settings();return; }
      message('正在发送到飞书…');
      setLink(config.table_url,'打开素材库');retryButton.hidden=true;
      const payload={source_url:source,title:document.querySelector('[data-video-description]')?.textContent||'视频号视频',author:document.querySelector('[data-author-name]')?.textContent||'',transcript:window.videoTranscriptEditor?.savedText(source)??textNode.value,retry};
      const result=await api('/save',payload);
      if (version===epoch) { remember(source,result.request_id);polls=0;showDelivery(result,source); }
    } catch (error) {
      if(version===epoch)message(error.name==='AbortError'?'连接超时，尚未确认保存结果；请稍后检查飞书。':error.message,true);
    } finally { busy=false;saveButton.disabled=false;retryButton.disabled=false; }
  }
  saveButton.addEventListener('click',()=>save());
  retryButton.addEventListener('click',()=>save(true));
  document.querySelector('[data-feishu-settings]').addEventListener('click',settings);
  dialog.querySelector('[data-feishu-close]').addEventListener('click',()=>dialog.close());
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    const button=form.querySelector('[type=submit]');
    const feedback=dialog.querySelector('[data-feishu-config-status]');
    button.disabled=true;
    try {
      config=await api('/connection',Object.fromEntries(new FormData(form)));
      form.elements.webhook_url.value='';form.elements.webhook_token.value='';
      epoch++;localStorage.removeItem(jobsKey);currentJob='';clearTimeout(timer);
      dialog.close();setLink(config.table_url,'打开素材库');
      message('飞书配置已保存。点击“保存到飞书”即可发送当前文案。');
    } catch (error) { feedback.textContent=error.message||'配置保存失败。'; }
    finally { button.disabled=false; }
  });
  window.addEventListener('video-transcript-saved',()=>{
    epoch++;
    clearTimeout(timer);currentJob='';retryButton.hidden=true;setLink('','');
    message('文案已更新，可保存最新版本到飞书。');
  });
  document.addEventListener('input',event=>{
    if(!event.target.matches('[data-transcript-corrected-text]'))return;
    epoch++;clearTimeout(timer);currentJob='';retryButton.hidden=true;setLink('','');
    message('文案编辑中，请保存后再入库。');
  });
  const observer=new MutationObserver(()=>{
    const source=share();
    if (document.querySelector('[data-video-result]')?.hidden || source===checkedShare) return;
    epoch++;checkedShare=source;currentJob='';clearTimeout(timer);retryButton.hidden=true;setLink('','');
    message('首次使用请先配置飞书接收流程。');
    const id=read(jobsKey,{})[source];
    if (id) { polls=0;loadConfig().then(()=>checkDelivery(id,source)).catch(()=>{}); }
  });
  observer.observe(document.documentElement,{subtree:true,attributes:true,attributeFilter:['hidden','data-video-share-url']});
})();
