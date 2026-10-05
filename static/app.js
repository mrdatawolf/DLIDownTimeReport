const $ = id => document.getElementById(id);
const number = (n, digits=2) => n == null ? '—' : n.toLocaleString(undefined, {maximumFractionDigits:digits});
function element(tag, text, cls) { const e=document.createElement(tag); e.textContent=text; if(cls)e.className=cls; return e; }
let reportShifts = [];
let reportRequest = 0;
async function load() {
  const request = ++reportRequest;
  const filters = reportFilters();
  if(!filters) return;
  const query = new URLSearchParams({date:$('date').value, shift:$('shift').value});
  for(const [key,value] of Object.entries(filters)) if(value !== '') query.set(key,value);
  const response = await fetch('/api/reports?'+query);
  if(!response.ok) throw new Error('Could not load reports.');
  const data=await response.json();
  if(request !== reportRequest) return;
  if(!Number.isInteger(data.match_total)) {
    $('filter-status').textContent='The server is running an older version. Restart Downtime Tracker and refresh this page to apply the page filters.';
    return;
  }
  const selectedDate=$('date').value;
  $('date').replaceChildren(new Option('All dates',''));
  for(const date of data.dates) { const option=element('option',date); option.value=date; $('date').append(option); }
  $('date').value=selectedDate;
  $('export').href='/api/export.csv?'+query;
  $('totals').replaceChildren();
  for(const [label,value] of [['Shifts',data.shifts.length],['Downtime',number(data.totals.downtime_minutes)+' min'],['Availability',data.totals.availability_percent == null ? '—' : number(data.totals.availability_percent)+'%']]) {
    const card=element('div','','card'); card.append(element('span',label),element('strong',String(value))); $('totals').append(card);
  }
  $('shifts').replaceChildren();
  for(const s of data.shifts) {
    const d=s.downtime, p=s.production?.numeric;
    const row=document.createElement('tr');
    for(const value of [`${s.date} · ${s.shift}`,d?number(d.downtime_minutes)+' min':'—',d?number(100*d.uptime_minutes/d.shift_minutes)+'%':'—',number(p?.['Total Logs'],0),p?number(p['Total Brd Footage'],0)+' BF':'—',p?'$'+number(p['Total Board Value']):'—']) row.append(element('td',value));
    $('shifts').append(row);
  }
  if(!data.shifts.length) {
    const row=document.createElement('tr'), cell=element('td','No shifts match the page filters. Adjust or reset the filters to see data.');
    cell.colSpan=6; row.append(cell); $('shifts').append(row);
  }
  reportShifts = data.shifts;
  $('filter-status').textContent='';
  renderTrends();
  renderDowntimePie(data.causes);
  $('causes').replaceChildren();
  const max=data.causes[0]?.minutes || 1;
  for(const c of data.causes) {
    const row=element('div','','cause'); const labels=element('div'); labels.append(element('strong',c.cause),element('small',`${c.area} · ${c.category} · ${c.occurrences} occurrences`));
    const track=element('div','','track'), bar=element('div','','bar'); bar.style.width=(c.minutes/max*100)+'%'; track.append(bar);
    row.append(labels,track,element('span',number(c.minutes)+' min')); $('causes').append(row);
  }
  if(!data.shifts.length) $('causes').append(element('p','No reports match these filters. Import PDFs to begin.'));
  $('sources').replaceChildren();
  for(const s of data.shifts) for(const source of s.sources) {
    const a=element('a',`${source.filename} · printed ${source.report_date}`); a.href='/api/source/'+source.id; a.target='_blank'; a.rel='noopener'; $('sources').append(a);
  }
}
for(const id of ['date','shift']) $(id).addEventListener('change',()=>load().catch(e=>$('status').textContent=e.message));
$('files').addEventListener('change',async event=>{
  const files=[...event.target.files]; $('files').disabled=true;
  const messages=[];
  for(const file of files) {
    $('status').textContent='Importing '+file.name+'…';
    try { const response=await fetch('/api/import?'+new URLSearchParams({filename:file.name}),{method:'POST',headers:{'Content-Type':'application/pdf'},body:file}); const result=await response.json(); messages.push(file.name+': '+(result.error || result.status)); }
    catch(e) {messages.push(file.name+': '+e.message);}
  }
  $('status').textContent=messages.join(' · '); $('files').disabled=false; $('files').value='';
  const current=$('date').value; $('date').replaceChildren(new Option('All dates','')); await load(); $('date').value=current; await load();
});
load().catch(e=>$('status').textContent=e.message);

async function loadIngestion() {
  const response=await fetch('/api/ingestion');
  if(!response.ok) throw new Error('Could not load ingestion status.');
  const data=await response.json();
  $('folder').textContent='Watching: '+data.folder;
  const counts={}; for(const file of data.files) counts[file.status]=(counts[file.status]||0)+1;
  $('ingestion-summary').textContent=Object.entries(counts).map(([status,count])=>`${count} ${status}`).join(' · ') || 'Waiting for stable PDF files.';
  $('ingestion').replaceChildren();
  for(const file of data.files) {
    const row=document.createElement('tr');
    for(const value of [file.path,file.status,file.checked_at+' UTC',file.error || '—']) row.append(element('td',value));
    $('ingestion').append(row);
  }
}
loadIngestion().catch(e=>$('ingestion-summary').textContent=e.message);
setInterval(()=>{
  load().catch(e=>$('status').textContent=e.message);
  loadIngestion().catch(e=>$('ingestion-summary').textContent=e.message);
},30000);

const trendMetrics = [
  {key:'downtime', label:'Downtime', unit:'min', color:'#b14d37'},
  {key:'availability', label:'Availability', unit:'%', color:'#22634c'},
  {key:'logs', label:'Logs', unit:'logs', color:'#386baf'},
  {key:'boardFeet', label:'Board footage', unit:'BF', color:'#8455a1'}
];
function shiftMetrics(s) {
  return {downtime:s.downtime?.downtime_minutes ?? null,
    availability:s.downtime?.shift_minutes > 0 ? 100*s.downtime.uptime_minutes/s.downtime.shift_minutes : null,
    logs:s.production?.numeric?.['Total Logs'] ?? null,
    boardFeet:s.production?.numeric?.['Total Brd Footage'] ?? null};
}
function svgElement(tag, attributes={}, text='') {
  const node=document.createElementNS('http://www.w3.org/2000/svg',tag);
  for(const [key,value] of Object.entries(attributes)) node.setAttribute(key,value);
  node.textContent=text; return node;
}
function renderDowntimePie(causes) {
  const container=$('downtime-pie');
  container.replaceChildren(element('h3','Share of downtime by cause'));
  const positive=causes.filter(c=>c.minutes>0);
  const total=positive.reduce((sum,c)=>sum+c.minutes,0);
  if(!total) { container.append(element('p','No downtime to chart for the selected filters.','muted')); return; }
  const slices=positive.slice(0,8).map(c=>({label:`${c.cause} · ${c.area} · ${c.category}`,minutes:c.minutes}));
  if(positive.length>8) slices.push({label:'Other causes',minutes:positive.slice(8).reduce((sum,c)=>sum+c.minutes,0)});
  const colors=['#22634c','#386baf','#b14d37','#8455a1','#b17b20','#237f87','#a33f70','#657346','#687485'];
  const layout=element('div','','pie-layout');
  const svg=svgElement('svg',{viewBox:'0 0 300 300',role:'img','aria-label':`Downtime by cause: ${number(total)} total minutes. Slice values are listed in the legend.`});
  const legend=element('ul','','pie-legend');
  let angle=-Math.PI/2;
  slices.forEach((slice,index)=>{
    const share=slice.minutes/total, end=angle+share*2*Math.PI;
    const description=`${slice.label}: ${number(slice.minutes)} min (${number(share*100,1)}%)`;
    const attrs={fill:colors[index],stroke:'white','stroke-width':2};
    const shape=slices.length===1 ? svgElement('circle',{...attrs,cx:150,cy:150,r:130}) : svgElement('path',{...attrs,d:`M 150 150 L ${150+130*Math.cos(angle)} ${150+130*Math.sin(angle)} A 130 130 0 ${share>0.5?1:0} 1 ${150+130*Math.cos(end)} ${150+130*Math.sin(end)} Z`});
    shape.append(svgElement('title',{},description)); svg.append(shape);
    const item=element('li'), swatch=element('span','','pie-swatch'); swatch.style.backgroundColor=colors[index];
    item.append(swatch,element('span',description)); legend.append(item); angle=end;
  });
  layout.append(svg,legend); container.append(element('p',`${number(total)} total downtime minutes`,'muted'),layout);
}
function showShift(s) {
  const detail=$('trend-detail'); detail.replaceChildren(element('h3',`${s.date} · Shift ${s.shift} · ${s.site}`));
  const metrics=shiftMetrics(s);
  detail.append(element('p',trendMetrics.map(m=>`${m.label}: ${metrics[m.key] == null ? '—' : number(metrics[m.key])+' '+m.unit}`).join(' · ')));
  for(const source of s.sources) {
    const a=element('a',source.filename); a.href='/api/source/'+source.id; a.target='_blank'; a.rel='noopener'; detail.append(a);
  }
}
function reportFilters() {
  const form=$('page-filters');
  let error=form.checkValidity() ? '' : 'Enter valid, nonnegative filter values. Availability must be between 0 and 100.';
  const from=$('trend-from').value, to=$('trend-to').value;
  if(from && to && from>to) error='From date must be on or before Through date.';
  const bounds=[['downtime','min-downtime','max-downtime'],['availability','min-availability','max-availability'],['logs','min-logs',null],['boardFeet','min-board-feet',null]].map(([key,min,max])=>({key,min:$(min).value === '' ? null : Number($(min).value),max:max && $(max).value !== '' ? Number($(max).value) : null}));
  if(bounds.some(b=>b.min != null && b.max != null && b.min>b.max)) error='Each minimum must be less than or equal to its maximum.';
  if(error) { $('filter-status').textContent=error; return null; }
  return Object.fromEntries([['from','trend-from'],['to','trend-to'],['min_downtime','min-downtime'],['max_downtime','max-downtime'],['min_availability','min-availability'],['max_availability','max-availability'],['min_logs','min-logs'],['min_board_feet','min-board-feet']].map(([key,id])=>[key,$(id).value]));
}
function metricAverage(items, metric) {
  const valid=items.filter(s=>shiftMetrics(s)[metric.key]!=null);
  if(!valid.length) return null;
  if(metric.key==='availability') return 100*valid.reduce((sum,s)=>sum+s.downtime.uptime_minutes,0)/valid.reduce((sum,s)=>sum+s.downtime.shift_minutes,0);
  return valid.reduce((sum,s)=>sum+shiftMetrics(s)[metric.key],0)/valid.length;
}
function periodDate(date, monthly) {
  if(monthly) return date.slice(0,7)+'-01';
  const day=new Date(date+'T00:00:00Z');
  day.setUTCDate(day.getUTCDate()-(day.getUTCDay()+6)%7);
  return day.toISOString().slice(0,10);
}
function showPeriod(label, items, metric) {
  const detail=$('trend-detail');
  detail.replaceChildren(element('h3',label),element('p',`${metric.label}: ${number(metricAverage(items,metric))} ${metric.unit} · ${items.length} shifts. Select a shift to inspect its reports.`));
  for(const s of items) {
    const button=element('button',`${s.date} · ${s.site} · Shift ${s.shift}`);
    button.addEventListener('click',()=>showShift(s)); detail.append(button);
  }
}
function chartAction(node, description, action) {
  node.setAttribute('tabindex',0); node.setAttribute('role','button'); node.setAttribute('aria-label',description);
  node.append(svgElement('title',{},description)); node.addEventListener('click',action);
  node.addEventListener('keydown',event=>{if(event.key==='Enter' || event.key===' ') {event.preventDefault();action();}});
}
function renderPeriodChart(card, shifts, metric, style) {
  const monthly=style==='monthly', heatmap=style==='heatmap';
  const groups=new Map(), periods=new Map();
  for(const s of shifts) {
    const label=`${s.site} · Shift ${s.shift} · ${s.start_time}`, date=periodDate(s.date,monthly);
    if(!groups.has(label)) groups.set(label,new Map());
    if(!groups.get(label).has(date)) groups.get(label).set(date,[]);
    groups.get(label).get(date).push(s); periods.set(date,true);
  }
  const observed=[...periods.keys()].sort(), dates=[], labels=[...groups.keys()];
  const cursor=new Date(observed[0]+'T00:00:00Z'), end=observed[observed.length-1];
  while(cursor.toISOString().slice(0,10)<=end) {
    dates.push(cursor.toISOString().slice(0,10));
    if(monthly) cursor.setUTCMonth(cursor.getUTCMonth()+1); else cursor.setUTCDate(cursor.getUTCDate()+7);
  }
  const width=Math.max(640,dates.length*(heatmap?26:Math.max(32,labels.length*16))+160);
  const height=heatmap?Math.max(170,labels.length*36+95):285;
  const svg=svgElement('svg',{viewBox:`0 0 ${width} ${height}`,role:'group','aria-label':`${metric.label} ${style}`});
  const values=[...groups.values()].flatMap(group=>[...group.values()].map(items=>metricAverage(items,metric))).filter(v=>v!=null);
  if(!values.length) {card.append(element('p','No reports contain this metric for the matching shifts.','muted'));return;}
  const max=metric.key==='availability'?100:Math.max(...values,1)*(heatmap?1:1.1), left=heatmap?160:72, cellWidth=(width-left-20)/dates.length;
  const palette=['#22634c','#386baf','#b14d37','#8455a1','#b17b20','#237f87'];
  card.append(element('p',heatmap?'Each cell is a weekly average per shift. Darker cells mean higher values; gray cells have no metric data.':`${monthly?'Monthly':'Weekly (Monday start)'} averages per shift. Availability is weighted by shift duration; other metrics average reported values. Select a cell or bar for its shifts.`,'muted'));
  if(!heatmap) for(let tick=0;tick<=4;tick++) {
    const value=max*tick/4, y=222-value/max*180;
    svg.append(svgElement('line',{x1:left,x2:width-20,y1:y,y2:y,stroke:'#e1e8df'}),svgElement('text',{x:left-8,y:y+4,'text-anchor':'end',class:'axis-label'},number(value,1)));
  }
  labels.forEach((label,row)=>{
    if(heatmap) svg.append(svgElement('text',{x:left-8,y:42+row*36+18,'text-anchor':'end',class:'axis-label'},label));
    dates.forEach((date,column)=>{
      const items=groups.get(label).get(date)||[], value=metricAverage(items,metric);
      const x=left+column*cellWidth;
      const node=heatmap?svgElement('rect',{x:x+1,y:42+row*36,width:cellWidth-2,height:30,fill:value==null?'#e1e8df':metric.color,'fill-opacity':value==null?1:0.12+0.88*value/max}):value==null?null:svgElement('rect',{x:x+row*cellWidth/labels.length+1,y:222-value/max*180,width:Math.max(1,cellWidth/labels.length-2),height:Math.max(2,value/max*180),fill:palette[row%palette.length]});
      if(!node) return;
      const description=`${date} · ${label}: ${value==null?'No metric data':number(value)+' '+metric.unit} · ${items.length} shifts`;
      if(items.length) chartAction(node,description,()=>showPeriod(`${monthly?'Month':'Week'} of ${date} · ${label}`,items,metric));
      else node.append(svgElement('title',{},description));
      svg.append(node);
    });
  });
  const stride=Math.max(1,Math.ceil(dates.length/8));
  dates.forEach((date,i)=>{if(i%stride===0 || i===dates.length-1) svg.append(svgElement('text',{x:left+(i+0.5)*cellWidth,y:heatmap?height-20:248,'text-anchor':'middle',class:'axis-label'},date.slice(5).replace('-','/')));});
  const scroll=element('div','','chart-scroll'); svg.style.minWidth=width+'px';scroll.append(svg);card.append(scroll);
  if(!heatmap) {
    const legend=element('div','','chart-legend'); labels.forEach((label,i)=>{const item=element('span',label),swatch=element('span','','pie-swatch');swatch.style.backgroundColor=palette[i%palette.length];item.prepend(swatch);legend.append(item);});card.append(legend);
  } else card.append(element('p',`Color scale: 0–${number(max)} ${metric.unit}. Availability averages are weighted by shift duration.`,'muted'));
}
function renderTrends() {
  const charts=$('trend-charts');
  charts.replaceChildren(); $('trend-detail').replaceChildren();
  const shifts=[...reportShifts].sort((a,b)=>a.date.localeCompare(b.date) || a.shift.localeCompare(b.shift));
  if(!shifts.length) { charts.append(element('p','No shifts match these filters. Adjust or reset the filters to see data.')); return; }
  const timestamp=s=>Date.parse(s.date+'T00:00:00Z');
  const first=timestamp(shifts[0]), last=timestamp(shifts[shifts.length-1]);
  const x=s=>first===last ? 320 : 72+(timestamp(s)-first)/(last-first)*496;
  const groups=new Map();
  for(const s of shifts) { const key=`${s.site} · Shift ${s.shift} · ${s.start_time}`; if(!groups.has(key)) groups.set(key,[]); groups.get(key).push(s); }
  const startYear=shifts[0].date.slice(0,4), endYear=shifts[shifts.length-1].date.slice(0,4);
  const years=startYear===endYear ? startYear : `${startYear}–${endYear}`;
  for(const metric of trendMetrics.filter(metric=>metric.key===$('trend-metric').value)) {
    const card=element('section','','chart-card'); card.append(element('h3',`${metric.label} (${metric.unit}) · ${years}`));
    if($('trend-style').value !== 'points') { renderPeriodChart(card,shifts,metric,$('trend-style').value); charts.append(card); continue; }
    const values=shifts.map(s=>shiftMetrics(s)[metric.key]).filter(v=>v!=null);
    if(!values.length) { card.append(element('p','No reports contain this metric for the matching shifts.','muted')); charts.append(card); continue; }
    const ceiling=metric.key==='availability' ? 100 : Math.max(...values,1)*1.1;
    const y=v=>222-v/ceiling*180;
    const svg=svgElement('svg',{viewBox:'0 0 640 260',role:'group','aria-label':metric.label+' by shift date'});
    for(let tick=0;tick<=4;tick++) {
      const value=ceiling*tick/4;
      svg.append(svgElement('line',{x1:72,x2:568,y1:y(value),y2:y(value),stroke:'#e1e8df'}),svgElement('text',{x:64,y:y(value)+4,'text-anchor':'end',class:'axis-label'},number(value,metric.key==='availability'?0:1)));
    }
    const dates=[...new Set(shifts.map(s=>s.date))];
    const ticks=dates.filter((_,i)=>i===0 || i===dates.length-1 || i%Math.ceil(dates.length/4)===0);
    for(const date of ticks) svg.append(svgElement('text',{x:x({date}),y:247,'text-anchor':'middle',class:'axis-label'},date.slice(5).replace('-','/')));
    let groupIndex=0;
    const legend=element('div','','chart-legend');
    for(const [label,items] of groups) {
      const dash=['','7 4','2 4','10 3 2 3'][groupIndex++%4];
      let segment=[];
      const draw=()=>{if(segment.length>1) svg.append(svgElement('polyline',{points:segment.join(' '),fill:'none',stroke:metric.color,'stroke-width':2,'stroke-dasharray':dash})); segment=[];};
      for(const s of items) { const value=shiftMetrics(s)[metric.key]; if(value==null) {draw();continue;} segment.push(`${x(s)},${y(value)}`); } draw();
      const labelNode=element('span',label); const swatch=svgElement('svg',{viewBox:'0 0 30 10','aria-hidden':'true'}); swatch.append(svgElement('line',{x1:0,x2:30,y1:5,y2:5,stroke:metric.color,'stroke-width':2,'stroke-dasharray':dash})); labelNode.prepend(swatch); legend.append(labelNode);
    }
    // Points follow all lines so every point remains clickable.
    for(const s of shifts) {
      const value=shiftMetrics(s)[metric.key]; if(value==null) continue;
      const description=`${s.date}, shift ${s.shift}, ${s.site}: ${number(value)} ${metric.unit}`;
      const point=svgElement('circle',{cx:x(s),cy:y(value),r:6,fill:metric.color,stroke:'white','stroke-width':2,tabindex:0,role:'button','aria-label':description,class:'chart-point'});
      point.append(svgElement('title',{},description));
      point.addEventListener('click',()=>showShift(s));
      point.addEventListener('keydown',event=>{if(event.key==='Enter' || event.key===' ') {event.preventDefault();showShift(s);}});
      svg.append(point);
    }
    card.append(svg,legend); charts.append(card);
  }
}
$('trend-metric').addEventListener('change',renderTrends);
$('trend-style').addEventListener('change',renderTrends);
$('page-filters').addEventListener('submit',event=>event.preventDefault());
for(const button of document.querySelectorAll('[data-date-range]')) {
  button.addEventListener('click',()=>{
    const today=new Date();
    const from=new Date(today.getFullYear(),today.getMonth(),today.getDate());
    if(button.dataset.dateRange === 'ytd') from.setMonth(0,1);
    else from.setDate(from.getDate()-(Number(button.dataset.dateRange)-1));
    const dateValue=date=>`${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
    $('trend-from').value=dateValue(from);
    $('trend-to').value=dateValue(today);
    $('date').value='';
    load().catch(e=>$('status').textContent=e.message);
  });
}
$('page-filters').addEventListener('input',event=>{
  if(event.target.tagName !== 'SELECT') load().catch(e=>$('status').textContent=e.message);
});
$('page-filters').addEventListener('reset',()=>setTimeout(()=>load().catch(e=>$('status').textContent=e.message),0));
const tabs=[$('raw-tab'),$('trends-tab')];
function selectTab(tab) {
  for(const item of tabs) {const active=item===tab; item.setAttribute('aria-selected',String(active)); item.tabIndex=active ? 0 : -1; $(item.getAttribute('aria-controls')).hidden=!active;}
}
for(const tab of tabs) {
  tab.addEventListener('click',()=>selectTab(tab));
  tab.addEventListener('keydown',event=>{
    if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) {event.preventDefault(); const next=event.key==='Home' ? tabs[0] : event.key==='End' ? tabs[1] : tabs.find(item=>item!==tab); selectTab(next); next.focus();}
  });
}
