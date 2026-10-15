const fs = require('fs'), path = require('path'), vm = require('vm');
const root = path.resolve(__dirname, '..');
const archive = fs.readFileSync(path.join(root,'member-view/archive-days.js'),'utf8');
const source = fs.readFileSync(path.join(root,'member-view/app.js'),'utf8');
const boundary = source.indexOf('\nlet members =');
if (boundary < 0) throw new Error('日报结构改变，请检查生成器');
const context = vm.createContext({});
vm.runInContext(archive+'\n'+source.slice(0,boundary)+'\nglobalThis.result=days;',context,{timeout:3000});
const reports=JSON.parse(JSON.stringify(context.result));
const days=Object.entries(reports).map(([key,r])=>({key,dateLabel:r.dateLabel,weekday:r.weekday,messages:r.messages,title:r.title})).sort((a,b)=>b.key.localeCompare(a.key));
const categories={content:'内容制作',product:'产品经营',private:'私域运营'};
const tips=Object.entries(reports).sort(([a],[b])=>b.localeCompare(a)).flatMap(([date,r])=>(r.insights||[]).map((insight,i)=>({id:date+'-'+i,cat:categories[(insight.roles||[])[0]]||'社群实战',title:insight.title,summary:insight.text,body:[insight.text],source:insight.source,date,note:'来自 '+date+' 石董会日报',links:[{title:'查看当天日报',url:'https://siyumenghai.cn/member-view/?date='+date}]})));
if(!days.length||!tips.length)throw new Error('未生成真实内容');
fs.writeFileSync(path.join(root,'member-view/miniprogram-content.json'),JSON.stringify({version:1,days,tips})+'\n');
console.log(JSON.stringify({days:days.length,tips:tips.length,latest:days[0].key}));

fs.writeFileSync(path.join(root,'miniprogram/data/tips.js'),'module.exports = '+JSON.stringify(tips,null,2)+';\n');
fs.writeFileSync(path.join(root,'miniprogram/data/reports.js'),'const reports = '+JSON.stringify(reports,null,2)+';\nconst reportKeys = Object.keys(reports).sort();\nmodule.exports = { reports, reportKeys };\n');
