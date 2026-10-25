// Clyp video editor: library, captions, background sound, colour grading and export.
// Caption and grade previews mirror build_ass()/grade_filters() in video_service.py;
// "Check exact frame" asks FFmpeg for the real thing.
const $=id=>document.getElementById(id);
const qs=new URLSearchParams(location.search);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clamp=(v,lo,hi)=>Math.max(lo,Math.min(hi,v));
let OPTIONS=null,project=null,sounds=[],saveTimer=null,savePromise=null,activeCaption=-1,raf=0,pollTimer=null;

async function api(url,options={}){const res=await fetch(url,options);const data=await res.json().catch(()=>({ok:false,message:'Invalid server response'}));if(!res.ok||!data.ok)throw Object.assign(new Error(data.message||'Request failed'),{data,status:res.status});return data}
function showToast(message,ms=2600){const t=$('toast');t.textContent=message;t.classList.add('show');clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>t.classList.remove('show'),ms)}
function fmtTime(s){s=Math.max(0,Number(s)||0);const m=Math.floor(s/60);return `${m}:${(s-m*60).toFixed(1).padStart(4,'0')}`}
function fmtDuration(s){s=Math.round(Number(s)||0);return `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`}
function formatDate(s){const d=new Date(s);return Number.isNaN(d.getTime())?'':new Intl.DateTimeFormat(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}).format(d)}

// ---------------------------------------------------------------------------
// Library
// ---------------------------------------------------------------------------
async function showLibrary(){
  $('libraryView').hidden=false;
  const grid=$('videoGrid');
  try{
    const {projects}=await api('/api/video/projects');
    $('videoCount').textContent=projects.length?`${projects.length} video${projects.length>1?'s':''}`:'';
    grid.innerHTML=projects.length?projects.map(p=>`<div class="video-card"><a href="video.html?id=${encodeURIComponent(p.id)}"><div class="video-thumb" style="background-image:url('/api/video/projects/${encodeURIComponent(p.id)}/thumb')"></div><div class="project-info"><strong>${esc(p.name)}</strong><small>${fmtDuration(p.duration)} · ${p.width}×${p.height} · ${esc(formatDate(p.updated_at))}</small></div></a><button class="card-delete" data-delete="${esc(p.id)}" title="Delete video" aria-label="Delete ${esc(p.name)}">×</button></div>`).join(''):'<div class="empty-projects"><strong>No videos yet.</strong><span>Upload a clip to start captioning, scoring and grading it.</span></div>';
  }catch(err){grid.innerHTML=`<div class="empty-projects"><strong>Couldn't load your videos.</strong><span>${esc(err.message)}</span></div>`}
}
$('videoGrid').addEventListener('click',async e=>{
  const id=e.target.closest('[data-delete]')?.dataset.delete;if(!id)return;
  e.preventDefault();
  if(!confirm('Delete this video project and its exports? This cannot be undone.'))return;
  try{await api(`/api/video/projects/${id}`,{method:'DELETE'});showLibrary()}catch(err){showToast(err.message,5000)}
});
function uploadVideo(file){
  if(!file)return;
  const box=$('uploadProgress'),bar=$('uploadBar'),text=$('uploadText');
  box.hidden=false;bar.style.width='0';text.textContent='Uploading…';
  const form=new FormData();form.append('video',file);
  const xhr=new XMLHttpRequest();
  xhr.open('POST','/api/video/projects');
  xhr.upload.onprogress=e=>{if(e.lengthComputable){const p=e.loaded/e.total;bar.style.width=`${p*100}%`;text.textContent=p<1?`Uploading… ${Math.round(p*100)}%`:'Analysing colour…'}};
  xhr.onload=()=>{let data={};try{data=JSON.parse(xhr.responseText)}catch{}if(xhr.status<300&&data.ok){location.href=`video.html?id=${encodeURIComponent(data.project.id)}`}else{box.hidden=true;showToast(data.message||'Upload failed',6000)}};
  xhr.onerror=()=>{box.hidden=true;showToast('Upload failed — is Clyp still running?',6000)};
  xhr.send(form);
}
$('dropZone').onclick=()=>$('videoInput').click();
$('videoInput').onchange=()=>uploadVideo($('videoInput').files[0]);
['dragenter','dragover'].forEach(t=>$('dropZone').addEventListener(t,e=>{e.preventDefault();$('dropZone').classList.add('dragging')}));
['dragleave','drop'].forEach(t=>$('dropZone').addEventListener(t,e=>{e.preventDefault();$('dropZone').classList.remove('dragging')}));
$('dropZone').addEventListener('drop',e=>uploadVideo(e.dataTransfer.files[0]));

// ---------------------------------------------------------------------------
// Saving
// ---------------------------------------------------------------------------
function setStatus(text){$('saveStatus').textContent=text}
function scheduleSave(){setStatus('Saving…');clearTimeout(saveTimer);saveTimer=setTimeout(flushSave,500)}
async function flushSave(){
  clearTimeout(saveTimer);saveTimer=null;
  if(savePromise)await savePromise;
  const body={name:$('projectName').value,captions:project.captions,caption_style:project.caption_style,sound:project.sound,grade:project.grade};
  savePromise=api(`/api/video/projects/${project.id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(()=>setStatus('Saved')).catch(err=>{setStatus('Not saved');showToast(err.message,5000)}).finally(()=>{savePromise=null});
  return savePromise;
}
window.addEventListener('beforeunload',e=>{if(saveTimer){flushSave();e.preventDefault()}});

// ---------------------------------------------------------------------------
// Editor shell
// ---------------------------------------------------------------------------
const player=$('player');
async function showEditor(id){
  try{({project}=await api(`/api/video/projects/${encodeURIComponent(id)}`))}catch(err){showToast(err.message,5000);$('libraryView').hidden=false;showLibrary();return}
  document.body.classList.add('editing');
  $('editorView').hidden=false;$('titleWrap').hidden=false;$('libraryLink').hidden=false;$('exportBtn').hidden=false;$('crumb').hidden=true;
  document.title=`${project.name} · Clyp Video`;
  $('projectName').value=project.name;
  player.src=`/api/video/projects/${project.id}/source`;
  player.volume=clamp(project.sound.original_volume,0,1);
  new ResizeObserver(fitPlayer).observe($('stage'));fitPlayer();
  buildCaptionControls();renderCaptionList();buildGradeControls();applyGrade();
  loadSounds();
  if(project.render?.status==='running')pollRender(false);
}
document.querySelectorAll('.video-tabs .tool-tab').forEach(btn=>btn.onclick=()=>{
  document.querySelectorAll('.video-tabs .tool-tab').forEach(b=>b.classList.toggle('active',b===btn));
  document.querySelectorAll('.video-panel section').forEach(s=>s.hidden=s.dataset.section!==btn.dataset.tab);
});
$('projectName').addEventListener('input',scheduleSave);

function fitPlayer(){
  if(!project)return;
  const stage=$('stage'),cs=getComputedStyle(stage);
  const availW=stage.clientWidth-parseFloat(cs.paddingLeft)-parseFloat(cs.paddingRight);
  const availH=stage.clientHeight-parseFloat(cs.paddingTop)-parseFloat(cs.paddingBottom)-$('stage').querySelector('.stage-bar').offsetHeight;
  const ratio=project.width/project.height;
  let w=availW,h=w/ratio;if(h>availH){h=availH;w=h*ratio}
  $('playerWrap').style.width=`${Math.max(80,w)}px`;$('playerWrap').style.height=`${Math.max(80,h)}px`;
  renderOverlay();
}

// Transport
$('playBtn').onclick=()=>player.paused?player.play():player.pause();
player.addEventListener('click',()=>player.paused?player.play():player.pause());
player.addEventListener('play',()=>{$('playBtn').textContent='❚❚';hideExact();syncMusic(true);loop()});
player.addEventListener('pause',()=>{$('playBtn').textContent='▶';$('musicPreview').pause();cancelAnimationFrame(raf);tick()});
player.addEventListener('seeked',()=>{syncMusic(!player.paused);tick()});
player.addEventListener('loadedmetadata',tick);
player.addEventListener('ended',()=>$('musicPreview').pause());
$('scrub').addEventListener('input',()=>{player.currentTime=$('scrub').value/1000*(project.duration||player.duration||0);hideExact()});
document.addEventListener('keydown',e=>{if(e.code==='Space'&&project&&!e.target.closest('input,textarea,select,button')){e.preventDefault();$('playBtn').click()}});
function loop(){tick();raf=requestAnimationFrame(loop)}
function tick(){
  const t=player.currentTime,d=project.duration||player.duration||0;
  $('timecode').textContent=`${fmtTime(t)} / ${fmtTime(d)}`;
  if(document.activeElement!==$('scrub'))$('scrub').value=d?Math.round(t/d*1000):0;
  renderOverlay();
}

// ---------------------------------------------------------------------------
// Captions
// ---------------------------------------------------------------------------
const STOPWORDS=new Set(`a an and are as at be been but by can could did do does for from had has have he her him his how i if in into is it its
just me my no not of on or our out she so than that the their them then there these they this to too up us was we were what when where which
who will with would you your about after again all also am any because before being both each few more most much only other over own same
some such very like really gonna wanna yeah okay oh`.split(/\s+/));
function emphasisWords(text,auto=true){
  const out=[];let active=false;
  for(const raw of text.split(/\s+/)){
    const word=raw.replace(/\*/g,'');if(!word)continue;
    const opens=raw.startsWith('*'),closes=(opens?raw.slice(1):raw).includes('*');
    out.push([word,active||opens]);
    if(opens&&!closes)active=true;else if(closes)active=false;
  }
  if(auto&&out.length&&!out.some(w=>w[1])){
    const letters=w=>w.replace(/[^\p{L}\p{N}']/gu,'').toLowerCase();
    let best=-1;out.forEach(([w],i)=>{const l=letters(w);if(l.length>=4&&!STOPWORDS.has(l)&&(best<0||l.length>letters(out[best][0]).length))best=i});
    if(best>=0)out[best][1]=true;
  }
  return out;
}
function wordOffsets(words,duration){const weights=words.map(w=>w.length+1),sum=weights.reduce((a,b)=>a+b,0);let acc=0;return weights.map(w=>{const at=acc/sum*duration;acc+=w;return at})}
function cssFont(name,bold){
  const map={'Segoe UI Semibold':["'Segoe UI',system-ui,sans-serif",600],'Segoe UI Black':["'Segoe UI',system-ui,sans-serif",900],'Arial Black':["'Arial Black',Arial,sans-serif",900],'Impact':["Impact,'Arial Narrow',sans-serif",400],'Arial':["Arial,sans-serif",bold?700:400]};
  return map[name]||[`'${name}',sans-serif`,bold?700:400];
}
function rgba(hex,a){const n=parseInt(hex.slice(1),16);return `rgba(${n>>16&255},${n>>8&255},${n&255},${a})`}

function buildCaptionControls(){
  const s=project.caption_style,styles=OPTIONS.caption_styles;
  $('capStyles').innerHTML=OPTIONS.caption_order.map(key=>[key,styles[key]]).map(([key,st])=>{const [family,weight]=cssFont(st.font,st.kind!=='build');const sample=st.kind==='build'?`<span style="font-weight:${weight}">so my </span><span style="font-weight:900;font-size:1.3em">prayer</span>`:(st.upper?'PRAYER':'Prayer');return `<button type="button" class="style-chip${key===s.preset?' selected':''}${st.kind==='build'?' featured':''}" data-style="${key}"><b style="font-family:${family};font-weight:${weight};color:${st.kind==='build'?st.base:st.highlight}">${sample}</b><small>${esc(st.label)}${st.kind==='build'?' · word by word':''}</small></button>`}).join('');
  $('capEnabled').checked=s.enabled;$('capWords').value=String(s.words);$('capPosition').value=s.position;
  $('capSize').value=s.size;$('capSizeOut').textContent=`${s.size}%`;$('capHighlight').checked=s.highlight;$('capColor').value=s.highlight_color.toLowerCase();
  const build=styles[s.preset].kind==='build';
  $('capHighlightLabel').textContent=build?'Emphasise key words (bigger and bolder)':'Highlight each word as it is spoken';
  $('capColorLabel').textContent=build?'Key word colour':'Highlight colour';
  $('capHint').innerHTML=build?'Words appear one at a time as they are spoken. Wrap a word in <b>*asterisks*</b> to make it the key word; Clyp picks one automatically when a line has none.':'The whole line shows at once and each word fills with the highlight colour as it is spoken.';
  $('resplitBtn').disabled=!project.has_transcript;
  $('effectBox').hidden=!build;
  document.querySelectorAll('#capEffect [data-effect]').forEach(b=>b.setAttribute('aria-checked',String(b.dataset.effect===s.effect)));
  $('glowFields').hidden=s.effect!=='glow';
  $('glowColor').value=s.glow_color.toLowerCase();$('glowStrength').value=s.glow_strength;$('glowStrengthOut').textContent=`${s.glow_strength}%`;
}
$('capStyles').addEventListener('click',e=>{const key=e.target.closest('[data-style]')?.dataset.style;if(!key)return;project.caption_style.preset=key;project.caption_style.highlight_color=OPTIONS.caption_styles[key].highlight;buildCaptionControls();renderOverlay(true);scheduleSave()});
$('capEnabled').onchange=()=>{project.caption_style.enabled=$('capEnabled').checked;renderOverlay(true);scheduleSave()};
$('capWords').onchange=()=>{project.caption_style.words=Number($('capWords').value);scheduleSave()};
$('capPosition').onchange=()=>{project.caption_style.position=$('capPosition').value;renderOverlay(true);scheduleSave()};
$('capSize').oninput=()=>{project.caption_style.size=Number($('capSize').value);$('capSizeOut').textContent=`${$('capSize').value}%`;renderOverlay(true);scheduleSave()};
$('capHighlight').onchange=()=>{project.caption_style.highlight=$('capHighlight').checked;renderOverlay(true);scheduleSave()};
$('capColor').oninput=()=>{project.caption_style.highlight_color=$('capColor').value.toUpperCase();renderOverlay(true);scheduleSave()};
$('capEffect').addEventListener('click',e=>{const effect=e.target.closest('[data-effect]')?.dataset.effect;if(!effect)return;project.caption_style.effect=effect;buildCaptionControls();renderOverlay(true);scheduleSave()});
$('glowColor').oninput=()=>{project.caption_style.glow_color=$('glowColor').value.toUpperCase();renderOverlay(true);scheduleSave()};
$('glowStrength').oninput=()=>{project.caption_style.glow_strength=Number($('glowStrength').value);$('glowStrengthOut').textContent=`${$('glowStrength').value}%`;renderOverlay(true);scheduleSave()};

$('transcribeBtn').onclick=async()=>{
  const btn=$('transcribeBtn');
  if(project.captions.some(c=>c.text.trim())&&!confirm('Replace the current caption lines with a new AI transcript?'))return;
  btn.disabled=true;btn.textContent='✦ Listening to your video…';
  try{
    await flushSave();
    ({project}=await api(`/api/video/projects/${project.id}/transcribe`,{method:'POST'}));
    renderCaptionList();buildCaptionControls();renderOverlay(true);
    showToast(`${project.captions.length} caption lines ready`);
  }catch(err){showToast(err.message,7000)}
  finally{btn.disabled=false;btn.textContent='✦ Generate captions with AI'}
};
$('resplitBtn').onclick=async()=>{try{await flushSave();({project}=await api(`/api/video/projects/${project.id}/resplit`,{method:'POST'}));renderCaptionList();renderOverlay(true)}catch(err){showToast(err.message,5000)}};

function renderCaptionList(){
  const list=$('captionList');activeCaption=-1;
  if(!project.captions.length){list.innerHTML='<div class="caption-empty">No caption lines yet. Generate them with AI, or add one at the playhead.</div>';return}
  list.innerHTML=project.captions.map((c,i)=>`<div class="caption-row" data-i="${i}"><label>Start<input type="number" step="0.1" min="0" data-field="start" value="${c.start}"></label><label>End<input type="number" step="0.1" min="0" data-field="end" value="${c.end}"></label><button class="row-del" type="button" data-del="${i}" title="Delete line" aria-label="Delete line">×</button><textarea rows="2" data-field="text" aria-label="Caption text">${esc(c.text)}</textarea><button class="row-jump" type="button" data-jump="${i}">▶ Jump to ${fmtTime(c.start)}</button></div>`).join('');
}
$('captionList').addEventListener('input',e=>{
  const row=e.target.closest('.caption-row'),field=e.target.dataset.field;if(!row||!field)return;
  const c=project.captions[Number(row.dataset.i)];
  c[field]=field==='text'?e.target.value:Math.max(0,Number(e.target.value)||0);
  renderOverlay(true);scheduleSave();
});
$('captionList').addEventListener('change',e=>{if(e.target.dataset.field==='start'){project.captions.sort((a,b)=>a.start-b.start);renderCaptionList()}});
$('captionList').addEventListener('click',e=>{
  const del=e.target.closest('[data-del]'),jump=e.target.closest('[data-jump]');
  if(del){project.captions.splice(Number(del.dataset.del),1);renderCaptionList();renderOverlay(true);scheduleSave()}
  if(jump){player.currentTime=project.captions[Number(jump.dataset.jump)].start+0.01;hideExact()}
});
$('addCaption').onclick=()=>{
  const t=Math.round(player.currentTime*10)/10;
  const next=project.captions.find(c=>c.start>t);
  const c={start:t,end:Math.round(Math.min(next?next.start:t+2,t+2,project.duration)*10)/10||t+0.5,text:''};
  project.captions.push(c);project.captions.sort((a,b)=>a.start-b.start);
  renderCaptionList();scheduleSave();
  $('captionList').querySelector(`.caption-row[data-i="${project.captions.indexOf(c)}"] textarea`)?.focus();
};

let overlayKey='';
function renderOverlay(force=false){
  if(!project)return;
  const el=$('captionOverlay'),s=project.caption_style,style=OPTIONS.caption_styles[s.preset];
  const t=player.currentTime;
  const index=s.enabled?project.captions.findIndex(c=>t>=c.start&&t<c.end&&c.text.replace(/\*/g,'').trim()):-1;
  if(index!==activeCaption){
    $('captionList').querySelector('.caption-row.active')?.classList.remove('active');
    if(index>=0)$('captionList').querySelector(`.caption-row[data-i="${index}"]`)?.classList.add('active');
    activeCaption=index;
  }
  if(index<0){if(overlayKey){el.innerHTML='';overlayKey=''}return}
  const c=project.captions[index];
  const W=project.width,H=project.height,k=$('playerWrap').clientHeight/H;
  const scale=Math.min(W,H)/1080*s.size/100,build=style.kind==='build';
  const words=emphasisWords(style.upper?c.text.toUpperCase():c.text,build&&s.highlight);
  const offsets=wordOffsets(words.map(w=>w[0]),c.end-c.start);
  const key=`${index}|${$('playerWrap').clientHeight}|${JSON.stringify(s)}|${c.text}|${c.start}|${c.end}`;
  if(force||key!==overlayKey){
    overlayKey=key;
    const [family,weight]=cssFont(style.font,!build),[efamily,eweight]=cssFont(style.emphasis_font||style.font,true);
    const marginX=(build?0.09:0.065)*W*k,marginY=(build?(s.position==='bottom'?0.15:0.1):0.085)*H*k;
    Object.assign(el.style,{inset:'0',padding:`${marginY}px ${marginX}px`,justifyContent:{bottom:'flex-end',middle:'center',top:'flex-start'}[s.position],alignItems:build?'flex-start':'center',textAlign:build?'left':'center'});
    const size=style.size*scale*k;
    let css=`font-family:${family};font-weight:${weight};font-size:${size}px;line-height:1.18;letter-spacing:${(style.spacing||0)*scale*k}px;color:${build?style.base:style.base};`;
    if(build&&s.effect==='shadow')css+=`text-shadow:0 0 ${Math.max(2,7*scale)*k*1.4}px rgba(0,0,0,.6);`;
    else if(build&&s.effect==='glow'){const g=s.glow_strength/100;css+=`text-shadow:0 0 ${(3+5*g)*scale*k*1.6}px ${rgba(s.glow_color,0.6+0.4*g)},0 0 ${(10+18*g)*scale*k*1.6}px ${rgba(s.glow_color,0.35+0.45*g)},0 0 ${(1+2*g)*scale*k*2}px ${rgba(s.glow_color,0.6+0.4*g)};`}
    else{
      if(style.box)css+=`background:${rgba(style.back,style.back_alpha)};padding:.08em .3em;box-decoration-break:clone;-webkit-box-decoration-break:clone;border-radius:.12em;`;
      else css+=`-webkit-text-stroke:${style.outline_size*scale*k*2}px ${style.outline};paint-order:stroke fill;text-shadow:${style.shadow*scale*k}px ${style.shadow*scale*k}px 0 ${rgba(style.back,style.back_alpha)};`;
    }
    const spans=words.map(([w,emph],i)=>{
      const e=build&&emph&&s.highlight?`font-family:${efamily};font-weight:${eweight};font-size:${style.emphasis_scale}em;letter-spacing:${(style.spacing||0)*scale*k/style.emphasis_scale}px;color:${s.highlight_color};`:'';
      return `<span class="w" data-at="${offsets[i]}" style="${e}">${esc(w)}</span>`;
    }).join(' ');
    el.innerHTML=`<div class="cap-line"><span class="cap" style="${css}">${spans}</span></div>`;
  }
  const elapsed=t-c.start;
  el.querySelectorAll('.w').forEach(span=>{
    const on=elapsed>=Number(span.dataset.at);
    if(build)span.classList.toggle('hidden',!on);
    else span.style.color=s.highlight&&on?s.highlight_color:style.base;
  });
}

// ---------------------------------------------------------------------------
// Sounds
// ---------------------------------------------------------------------------
async function loadSounds(){
  try{({sounds}=await api('/api/video/sounds'))}catch(err){sounds=[];showToast(err.message,5000)}
  renderSounds();
  const s=project.sound;
  $('musicVol').value=Math.round(s.volume*100);$('musicVolOut').textContent=`${$('musicVol').value}%`;
  $('origVol').value=Math.round(s.original_volume*100);$('origVolOut').textContent=`${$('origVol').value}%`;
  $('musicStart').value=s.start;$('musicDuck').checked=s.duck;
  setMusicSource();
}
function renderSounds(){
  const items=[{id:'',title:'No background sound',duration:0,kind:''},...sounds];
  $('soundList').innerHTML=items.map(s=>`<div class="sound-item${s.id===project.sound.id?' selected':''}" role="button" tabindex="0" data-sound="${esc(s.id)}">${s.id?`<button class="sample" type="button" data-sample="${esc(s.id)}" title="Listen" aria-label="Listen to ${esc(s.title)}">▶</button>`:'<span></span>'}<span><strong>${esc(s.title)}</strong>${s.id?`<br><small>${s.kind==='upload'?'Your upload':'Clyp library'}</small>`:''}</span><small>${s.duration?fmtDuration(s.duration):''}</small></div>`).join('');
}
$('soundList').addEventListener('click',e=>{
  const sample=e.target.closest('[data-sample]');
  if(sample){e.stopPropagation();const a=$('soundSample'),src=`/api/video/sounds/${encodeURIComponent(sample.dataset.sample)}`;if(!a.paused&&a.dataset.id===sample.dataset.sample){a.pause();sample.textContent='▶';return}document.querySelectorAll('[data-sample]').forEach(b=>b.textContent='▶');a.dataset.id=sample.dataset.sample;a.src=src;a.volume=.8;a.play();sample.textContent='❚❚';a.onended=()=>sample.textContent='▶';return}
  const item=e.target.closest('[data-sound]');if(!item)return;
  project.sound.id=item.dataset.sound;renderSounds();setMusicSource();scheduleSave();
});
$('soundList').addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&e.target.matches('[data-sound]')){e.preventDefault();e.target.click()}});
$('uploadSoundBtn').onclick=()=>$('soundInput').click();
$('soundInput').onchange=async()=>{
  const file=$('soundInput').files[0];if(!file)return;
  const form=new FormData();form.append('sound',file);
  try{const {sound}=await api('/api/video/sounds',{method:'POST',body:form});sounds.push(sound);project.sound.id=sound.id;renderSounds();setMusicSource();scheduleSave();showToast('Track added')}catch(err){showToast(err.message,5000)}
  $('soundInput').value='';
};
$('musicVol').oninput=()=>{project.sound.volume=$('musicVol').value/100;$('musicVolOut').textContent=`${$('musicVol').value}%`;$('musicPreview').volume=project.sound.volume;scheduleSave()};
$('origVol').oninput=()=>{project.sound.original_volume=$('origVol').value/100;$('origVolOut').textContent=`${$('origVol').value}%`;player.volume=clamp(project.sound.original_volume,0,1);scheduleSave()};
$('musicStart').onchange=()=>{project.sound.start=Math.max(0,Number($('musicStart').value)||0);syncMusic(!player.paused);scheduleSave()};
$('musicDuck').onchange=()=>{project.sound.duck=$('musicDuck').checked;scheduleSave()};
function setMusicSource(){
  const m=$('musicPreview');
  if(!project.sound.id){m.pause();m.removeAttribute('src');m.load();return}
  m.src=`/api/video/sounds/${encodeURIComponent(project.sound.id)}`;m.volume=project.sound.volume;
  syncMusic(!player.paused);
}
function syncMusic(play){
  const m=$('musicPreview');if(!project?.sound.id||!m.src)return;
  const go=()=>{const d=m.duration||0;const at=project.sound.start+player.currentTime;m.currentTime=d?at%d:at;if(play)m.play().catch(()=>{});else m.pause()};
  if(m.readyState>=1)go();else m.addEventListener('loadedmetadata',go,{once:true});
}

// ---------------------------------------------------------------------------
// Colour grading: automatic correction + look x strength + fine-tune sliders.
// The preview approximates grade_filters() in video_service.py with one colour matrix.
// ---------------------------------------------------------------------------
const SLIDERS={brightness:'Brightness',contrast:'Contrast',saturation:'Saturation',temperature:'Temperature',tint:'Tint',vignette:'Vignette',grain:'Film grain'};
const ZERO_FROM=new Set(['vignette','grain']);
function gradeValues(grade){
  const look=OPTIONS.grade_presets[grade.preset]?.values||{},strength=(grade.strength??100)/100;
  const auto=grade.auto?(project.analysis?.values||{}):{};
  const v={};
  for(const key of OPTIONS.grade_keys)v[key]=clamp(Math.round((auto[key]||0)+(look[key]||0)*strength+(Number(grade[key])||0)),ZERO_FROM.has(key)?0:-100,100);
  return v;
}
function gradeMatrix(grade){
  const v=gradeValues(grade),look=OPTIONS.grade_presets[grade.preset]||{},strength=(grade.strength??100)/100;
  const b=v.brightness/100*0.2,c=1+v.contrast/100*0.6,s=Math.max(0,1+v.saturation/100),t=v.temperature/100,n=v.tint/100;
  const bal=look.balance||{},fade=(look.fade||0)*strength;
  // colorbalance: shadows/midtones shift the channel, highlights scale it.
  const offset=['r','g','b'].map(ch=>((bal[ch+'s']||0)*0.5+(bal[ch+'m']||0)*0.5)*strength);
  const gain=['r','g','b'].map(ch=>1+(bal[ch+'h']||0)*0.6*strength);
  const temp=[0.09*t,-0.06*n,-0.09*t];
  const lw=[0.2126,0.7152,0.0722];
  const rows=[0,1,2].map(r=>{
    const g=gain[r]*(1-fade);
    const row=lw.map((w,col)=>((1-s)*w+(col===r?s:0))*c*g);
    return [...row,0,(0.5*(1-c)+b+temp[r]+offset[r])*(1-fade)+fade];
  });
  return [...rows.flat(),0,0,0,1,0].map(x=>+x.toFixed(4)).join(' ');
}
function vignetteCss(v){return v.vignette?`radial-gradient(ellipse at center,transparent ${55-v.vignette*0.2}%,rgba(0,0,0,${(v.vignette/100*0.75).toFixed(3)}) 100%)`:'none'}
function lookGrade(key){return {...project.grade,preset:key}}
function buildGradeControls(){
  const presets=OPTIONS.grade_presets,thumb=`/api/video/projects/${project.id}/thumb`;
  $('gradeAuto').checked=!!project.grade.auto;
  $('autoSummary').innerHTML=(project.analysis?.summary||[]).map(line=>`<li>${esc(line)}</li>`).join('');
  $('gradeStrength').value=project.grade.strength;$('strengthOut').textContent=`${project.grade.strength}%`;
  $('gradePresets').innerHTML=OPTIONS.grade_order.map(key=>`<button type="button" class="preset${key===project.grade.preset?' selected':''}" data-preset="${key}"><span class="swatch" style="background-image:url('${thumb}');filter:url(#grade-${key})"><span class="swatch-vignette" data-vignette="${key}" style="display:block;width:100%;height:100%"></span></span>${esc(presets[key].label)}</button>`).join('');
  $('gradeSliders').innerHTML=Object.entries(SLIDERS).map(([key,label])=>`<label>${label} <output id="out-${key}">${project.grade[key]}</output><input type="range" data-grade="${key}" min="${ZERO_FROM.has(key)?0:-100}" max="100" value="${project.grade[key]}"></label>`).join('');
  $('gradeDefs').innerHTML=OPTIONS.grade_order.map(key=>`<filter id="grade-${key}" color-interpolation-filters="sRGB"><feColorMatrix type="matrix" values=""/></filter>`).join('')+'<filter id="grade-live" color-interpolation-filters="sRGB"><feColorMatrix id="liveMatrix" type="matrix" values="1 0 0 0 0 0 1 0 0 0 0 0 1 0 0 0 0 0 1 0"/></filter>';
  updateSwatches();
}
// Swatches show each look on this video as it would actually come out (auto + strength + sliders).
function updateSwatches(){
  for(const key of OPTIONS.grade_order){
    const g=lookGrade(key);
    document.querySelector(`#grade-${key} feColorMatrix`)?.setAttribute('values',gradeMatrix(g));
    const vig=document.querySelector(`[data-vignette="${key}"]`);if(vig)vig.style.background=vignetteCss(gradeValues(g));
  }
}
function applyGrade(){
  $('liveMatrix').setAttribute('values',gradeMatrix(project.grade));
  player.style.filter='url(#grade-live)';
  $('vignette').style.background=vignetteCss(gradeValues(project.grade));
}
function gradeChanged(swatches=false){if(swatches)updateSwatches();applyGrade();hideExact();scheduleSave()}
$('gradeAuto').onchange=()=>{project.grade.auto=$('gradeAuto').checked;gradeChanged(true)};
$('gradeStrength').oninput=()=>{project.grade.strength=Number($('gradeStrength').value);$('strengthOut').textContent=`${$('gradeStrength').value}%`;gradeChanged(true)};
$('gradePresets').addEventListener('click',e=>{const key=e.target.closest('[data-preset]')?.dataset.preset;if(!key)return;project.grade.preset=key;document.querySelectorAll('.preset').forEach(b=>b.classList.toggle('selected',b.dataset.preset===key));gradeChanged()});
$('gradeSliders').addEventListener('input',e=>{const key=e.target.dataset.grade;if(!key)return;project.grade[key]=Number(e.target.value);$(`out-${key}`).textContent=e.target.value;gradeChanged(true)});
$('gradeReset').onclick=()=>{for(const key of OPTIONS.grade_keys)project.grade[key]=0;buildGradeControls();applyGrade();scheduleSave()};

// Exact frame from FFmpeg
$('exactBtn').onclick=async()=>{
  player.pause();
  const btn=$('exactBtn');btn.disabled=true;btn.textContent='Rendering frame…';
  try{
    await flushSave();
    const res=await fetch(`/api/video/projects/${project.id}/frame?t=${player.currentTime.toFixed(3)}`);
    if(!res.ok){const data=await res.json().catch(()=>({}));throw new Error(data.message||'Frame preview failed')}
    const img=$('exactFrame');URL.revokeObjectURL(img.src);img.src=URL.createObjectURL(await res.blob());
    img.hidden=false;$('exactBadge').hidden=false;$('captionOverlay').hidden=true;$('vignette').hidden=true;
  }catch(err){showToast(err.message,6000)}
  finally{btn.disabled=false;btn.textContent='Check exact frame'}
};
$('exactClose').onclick=hideExact;
function hideExact(){$('exactFrame').hidden=true;$('exactBadge').hidden=true;$('captionOverlay').hidden=false;$('vignette').hidden=false}

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------
const modal=$('exportModal'),card=$('exportCard');
function openModal(html){card.innerHTML=html;modal.classList.add('open');modal.setAttribute('aria-hidden','false')}
function closeModal(){modal.classList.remove('open');modal.setAttribute('aria-hidden','true')}
modal.addEventListener('click',e=>{if(e.target===modal||e.target.closest('[data-close]'))closeModal()});
$('exportBtn').onclick=async()=>{
  player.pause();
  try{
    await flushSave();
    await api(`/api/video/projects/${project.id}/render`,{method:'POST'}).catch(err=>{if(err.status!==409)throw err});
    pollRender(true);
  }catch(err){showToast(err.message,6000)}
};
function pollRender(show){
  clearTimeout(pollTimer);
  if(show)openModal(`<div class="brief-form export-card"><span class="kicker">EXPORTING</span><h2>Rendering your video…</h2><p>Clyp is burning in the captions, mixing the sound and applying the grade. You can keep this tab open while it works.</p><div class="export-progress"><i id="exportBar"></i></div><small id="exportPct">Starting…</small></div>`);
  const step=async()=>{
    let render;
    try{({render}=await api(`/api/video/projects/${project.id}/render`))}catch(err){pollTimer=setTimeout(step,2000);return}
    project.render=render;
    if(render.status==='running'){
      $('exportBtn').textContent=`Exporting ${Math.round(render.progress*100)}%`;
      if($('exportBar')){$('exportBar').style.width=`${render.progress*100}%`;$('exportPct').textContent=`${Math.round(render.progress*100)}%`}
      pollTimer=setTimeout(step,1000);return;
    }
    $('exportBtn').textContent='Export video';
    if(render.status==='done'){
      const src=`/api/video/projects/${project.id}/export?v=${encodeURIComponent(render.finished_at)}`;
      openModal(`<div class="brief-form export-card"><span class="kicker">READY</span><h2>Your video is ready.</h2><video controls playsinline src="${src}"></video><div class="brief-actions"><button class="button ghost" data-close>Keep editing</button><a class="button" href="${src}&download=1" download>Download MP4</a></div></div>`);
    }else if(render.status==='error'&&(show||modal.classList.contains('open'))){
      openModal(`<div class="brief-form export-card"><span class="kicker">EXPORT FAILED</span><h2>Clyp couldn't export this video.</h2><pre class="export-error">${esc(render.error)}</pre><div class="brief-actions"><button class="button ghost" data-close>Close</button></div></div>`);
    }
  };
  step();
}

// ---------------------------------------------------------------------------
(async function init(){
  try{OPTIONS=await api('/api/video/options')}catch(err){showToast(`Video editor unavailable: ${err.message}`,8000);return}
  const id=qs.get('id');
  if(id)showEditor(id);else showLibrary();
})();
