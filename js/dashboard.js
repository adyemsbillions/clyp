const modal=document.getElementById('createModal'),content=document.getElementById('modalContent'),upload=document.getElementById('flyerUpload');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function openModal(html){content.innerHTML=html;modal.classList.add('open');modal.setAttribute('aria-hidden','false')}
function closeModal(){modal.classList.remove('open');modal.setAttribute('aria-hidden','true')}
function setModalBusy(text,detail='Clyp is building hierarchy, colour, imagery and editable layers.'){content.innerHTML=`<div class="brief-form ai-working"><span class="kicker">CLYP AI</span><h2>${esc(text)}</h2><p>${esc(detail)}</p><div class="ai-loader"><i></i></div></div>`}
function modalError(message,back){content.innerHTML=`<div class="brief-form"><span class="kicker">COULDN'T CONTINUE</span><h2>${esc(message)}</h2><p>Clyp reached the AI service, but the request could not be completed. The error above is the useful part; retry after correcting it.</p><div class="brief-actions"><button class="button ghost" data-close>Close</button><button class="button" id="retryAction">Try again</button></div></div>`;document.getElementById('retryAction').onclick=back}
modal.addEventListener('click',e=>{if(e.target===modal||e.target.matches('[data-close]'))closeModal()});

async function api(url,options={}){const res=await fetch(url,options);const data=await res.json().catch(()=>({ok:false,message:'Invalid server response'}));if(!res.ok||!data.ok)throw Object.assign(new Error(data.message||'Request failed'),{data,status:res.status});return data}

function aiForm(){return `<form class="brief-form" id="briefForm"><span class="kicker">CREATE WITH AI</span><h2>Tell Clyp what you’re making.</h2><p>Start with the idea. Clyp will art-direct the layout, colour, typography and—when useful—a separate visual asset, while keeping the design editable.</p><label>What do you need?<textarea name="brief" rows="4" required placeholder="e.g. I need a flyer for our church youth conference."></textarea></label><label>Format<select name="format"><option>Instagram portrait · 1080 × 1350</option><option>Square · 1080 × 1080</option><option>Story · 1080 × 1920</option><option>A4 document</option></select></label><div class="brief-actions"><button type="button" class="button ghost" data-close>Cancel</button><button class="button" type="submit">Create design</button></div></form>`}
function wireAiForm(){document.getElementById('briefForm').onsubmit=async e=>{e.preventDefault();const payload=Object.fromEntries(new FormData(e.target));const asksImage=/realistic image|realistic photo|photograph|photography|photo of|image of|portrait of|people|person|worshipper|model|illustration|hero image|cinematic/i.test(payload.brief||'');setModalBusy(asksImage?'Art-directing layout + generating hero image…':'Designing your first direction…',asksImage?'Clyp is building the editable composition and creating the separate visual asset. This can take longer than a typography-only design.':'Clyp is building hierarchy, colour and editable layers.');try{const data=await api('/api/ai/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});try{sessionStorage.setItem('clyp:generatedDesign',JSON.stringify(data.design));sessionStorage.setItem('clyp:generationMeta',JSON.stringify({warnings:data.warnings||[],imagery_required:!!data.imagery_required,image_model:data.image_model||''}))}catch{throw new Error('The generated design is too large for temporary browser storage. Clyp created the visual, but this local build needs asset persistence before it can open it safely.')}location.href='editor.html?mode=ai'}catch(err){modalError(err.message,()=>{openModal(aiForm());wireAiForm()})}}}
document.querySelector('[data-action="ai"]').onclick=()=>{openModal(aiForm());wireAiForm()};

document.querySelector('[data-action="upload"]').onclick=()=>openModal(`<div class="brief-form"><span class="kicker">EDIT A FLYER</span><h2>Upload your existing design.</h2><p>Clyp will preserve the source aspect ratio, keep photographs/logos/complex graphics as source image layers, and trace editable text and simple shapes on top.</p><button class="upload-drop" id="pickUpload"><strong>Choose JPG, PNG or PDF</strong><p>Maximum 7 MB in this local build.</p></button></div>`);
modal.addEventListener('click',e=>{if(e.target.closest('#pickUpload'))upload.click()});

function imageDimensions(dataUrl){return new Promise(resolve=>{const img=new Image();img.onload=()=>resolve({width:img.naturalWidth||0,height:img.naturalHeight||0});img.onerror=()=>resolve({width:0,height:0});img.src=dataUrl})}

upload.onchange=async()=>{
  const file=upload.files[0];if(!file)return;
  if(file.size>7*1024*1024){modalError('That file is larger than 7 MB.',()=>upload.click());return}
  const reader=new FileReader();
  reader.onload=async()=>{
    setModalBusy('Tracing the source design…','Clyp is preserving complex visuals, source proportions and editable text/shapes.');
    try{
      const dims=file.type.startsWith('image/')?await imageDimensions(reader.result):{width:0,height:0};
      const data=await api('/api/ai/reconstruct',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({data_url:reader.result,filename:file.name,source_width:dims.width,source_height:dims.height})});
      data.design.assets={...(data.design.assets||{}),source_upload:reader.result};
      data.design.source={filename:file.name,mime:file.type||'',width:dims.width,height:dims.height};
      for(const layer of data.design.layers||[]){if(layer.type==='image')layer.asset='source_upload'}
      try{sessionStorage.setItem('clyp:generatedDesign',JSON.stringify(data.design))}catch{throw new Error('This upload is too large for temporary browser storage in Fast Dev mode. Try a smaller/compressed image for now.')}
      location.href='editor.html?mode=reconstruct';
    }catch(err){modalError(err.message,()=>upload.click())}
  };
  reader.readAsDataURL(file)
};

document.querySelector('[data-action="template"]').onclick=()=>location.href='templates.html';

function formatDate(s){if(!s)return'Just now';const d=new Date(s);return Number.isNaN(d.getTime())?'Just now':new Intl.DateTimeFormat(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}).format(d)}
function renderRecent(){const el=document.getElementById('recentProjects');const projects=ClypStore.list();if(!projects.length){el.innerHTML='<div class="empty-projects"><strong>No designs yet.</strong><span>Create with AI, upload a flyer, or choose a template. Your work saves locally and opens instantly.</span></div>';return}el.innerHTML=projects.slice(0,6).map(p=>`<a class="recent-project" href="editor.html?id=${encodeURIComponent(p.id)}"><div class="project-thumb" style="background:${esc(p.canvas?.bg||'#e6e8ff')}"><div class="mini-title">${esc((p.name||'Untitled').toUpperCase())}</div></div><div class="project-info"><strong>${esc(p.name||'Untitled design')}</strong><small>${formatDate(p.updated_at)} · ${esc(p.format||'1080 × 1350')}</small></div></a>`).join('')}

document.getElementById('refreshProjects').onclick=renderRecent;
document.getElementById('todayLabel').textContent=new Intl.DateTimeFormat(undefined,{weekday:'long',day:'numeric',month:'long'}).format(new Date());
renderRecent();
if(new URLSearchParams(location.search).get('upload')==='1') document.querySelector('[data-action="upload"]').click();
