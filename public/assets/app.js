(() => {
  const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
  const escapeHTML=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[ch]));
  const toast=(message,type='success')=>{const el=document.createElement('div');el.className=`toast ${type}`;el.textContent=message;document.body.append(el);setTimeout(()=>el.remove(),5000)};
  const api=async(action,body,form=false)=>{const opts={method:'POST',headers:{'X-CSRF-Token':window.CLYP.csrf}};if(form){opts.body=body}else{opts.headers['Content-Type']='application/json';opts.body=JSON.stringify(body||{})}const r=await fetch(`/api?action=${encodeURIComponent(action)}`,opts);const d=await r.json().catch(()=>({ok:false,message:'Invalid server response.'}));if(!r.ok||!d.ok)throw new Error(d.message||'Request failed.');return d};
  const busy=(btn,on,label='Working…')=>{if(!btn)return;if(on){btn.dataset.old=btn.innerHTML;btn.disabled=true;btn.innerHTML=`<span class="spinner"></span>${label}`}else{btn.disabled=false;btn.innerHTML=btn.dataset.old||btn.innerHTML}};
  const openPane=name=>{const btn=$(`[data-tab="${name}"]`);if(!btn)return;$$('[data-tab]').forEach(x=>x.classList.toggle('active',x===btn));$$('[data-pane]').forEach(x=>x.classList.toggle('active',x.dataset.pane===name))};
  $$('[data-toast]').forEach(x=>setTimeout(()=>x.remove(),4500));
  $('[data-sidebar-toggle]')?.addEventListener('click',()=>$('#sidebar')?.classList.toggle('open'));

  const upload=$('#upload-form');
  if(upload){
    upload.addEventListener('submit',e=>{e.preventDefault();const file=$('#video-file')?.files?.[0];if(!file)return toast('Choose a video first.','error');if(file.size>500*1024*1024)return toast('Video must be 500 MB or smaller.','error');const data=new FormData(upload),xhr=new XMLHttpRequest(),box=$('#upload-progress'),bar=$('#upload-bar'),percent=$('#upload-percent'),status=$('#upload-status'),btn=$('button[type=submit]',upload);box.classList.remove('hidden');busy(btn,true,'Uploading…');xhr.upload.onprogress=ev=>{if(ev.lengthComputable){const p=Math.round(ev.loaded/ev.total*100);bar.style.width=p+'%';percent.textContent=p+'%';status.textContent=p<100?'Uploading video…':'Creating project…'}};xhr.onload=()=>{busy(btn,false);let d={};try{d=JSON.parse(xhr.responseText)}catch{}if(xhr.status>=200&&xhr.status<300&&d.ok)location.href=d.redirect;else toast(d.message||'Upload failed.','error')};xhr.onerror=()=>{busy(btn,false);toast('Network error during upload.','error')};xhr.open('POST','/api?action=upload');xhr.setRequestHeader('X-CSRF-Token',window.CLYP.csrf);xhr.send(data)});
    const dz=$('#drop-zone'),input=$('#video-file');input?.addEventListener('change',()=>{if(input.files[0]){$('h3',dz).textContent=input.files[0].name;$('p',dz).textContent=(input.files[0].size/1024/1024).toFixed(1)+' MB'}});['dragenter','dragover'].forEach(x=>dz?.addEventListener(x,e=>{e.preventDefault();dz.classList.add('dragging')}));['dragleave','drop'].forEach(x=>dz?.addEventListener(x,e=>{e.preventDefault();dz.classList.remove('dragging')}));dz?.addEventListener('drop',e=>{if(e.dataTransfer.files[0]){input.files=e.dataTransfer.files;input.dispatchEvent(new Event('change'))}})
  }

  $$('[data-subscribe]').forEach(btn=>btn.addEventListener('click',async()=>{busy(btn,true,'Opening checkout…');try{const d=await api('subscribe',{plan:btn.dataset.subscribe});toast(d.message||'Opening checkout.');if(d.redirect)location.href=d.redirect}catch(e){toast(e.message,'error');busy(btn,false)}}));

  const studio=$('.studio');if(!studio)return;
  const projectId=Number(studio.dataset.projectId),video=$('#studio-video'),preview=$('#caption-preview');
  let captions=window.PROJECT_CAPTIONS||[],selectedSound=$('.sound-item.selected')?.dataset.soundId||'',audio=null;

  const captionWords=(caption,time)=>{const words=String(caption.text||'').trim().split(/\s+/).filter(Boolean);if(!words.length)return '';const duration=Math.max(.1,Number(caption.end)-Number(caption.start));const progress=Math.max(0,Math.min(.999,(time-Number(caption.start))/duration));const active=Math.min(words.length-1,Math.floor(progress*words.length));return words.map((word,i)=>`<span class="${i===active?'active':i<active?'spoken':''}">${escapeHTML(word)}</span>`).join(' ')};
  const updatePreview=()=>{if(!video||!preview)return;const c=captions.find(x=>video.currentTime>=Number(x.start)&&video.currentTime<Number(x.end));if(c){preview.innerHTML=captionWords(c,video.currentTime);preview.classList.add('show')}else{preview.textContent='';preview.classList.remove('show')}};
  video?.addEventListener('timeupdate',updatePreview);
  $$('[data-tab]').forEach(btn=>btn.addEventListener('click',()=>openPane(btn.dataset.tab)));
  $$('[data-open-pane]').forEach(btn=>btn.addEventListener('click',()=>openPane(btn.dataset.openPane)));

  $$('[data-style]').forEach(btn=>btn.addEventListener('click',async()=>{$$('[data-style]').forEach(x=>x.classList.toggle('selected',x===btn));preview.className=`caption-preview style-${btn.dataset.style}`;updatePreview();try{await api('project_settings',{project_id:projectId,caption_style:btn.dataset.style});toast('Caption design updated. Rebuild the auto edit before exporting.')}catch(e){toast(e.message,'error')}}));

  $('[data-transcribe]')?.addEventListener('click',async e=>{const btn=e.currentTarget;busy(btn,true,'Transcribing speech…');try{const d=await api('transcribe',{project_id:projectId});toast(d.message);if(d.reload)location.reload()}catch(err){toast(err.message,'error');busy(btn,false)}});
  $('[data-manual-transcript]')?.addEventListener('click',async e=>{const btn=e.currentTarget,text=$('#manual-transcript')?.value||'';busy(btn,true,'Creating captions…');try{const d=await api('manual_transcript',{project_id:projectId,transcript:text});toast(d.message);location.reload()}catch(err){toast(err.message,'error');busy(btn,false)}});
  $('[data-save-captions]')?.addEventListener('click',async e=>{const btn=e.currentTarget;captions=$$('.caption-row').map(row=>{const inputs=$$('input',row);return{text:$('textarea',row).value.trim(),start:Number(inputs[0].value),end:Number(inputs[1].value)}});busy(btn,true,'Saving…');try{const d=await api('save_captions',{project_id:projectId,captions});toast(d.message+' Rebuild the auto edit to use the changes.')}catch(err){toast(err.message,'error')}busy(btn,false)});
  $$('.caption-row').forEach(row=>row.addEventListener('click',e=>{if(e.target.matches('textarea,input'))return;if(video){video.currentTime=Number($('input',row).value||0);video.play().catch(()=>{})}}));

  $$('[data-edit-style]').forEach(btn=>btn.addEventListener('click',()=>{$$('[data-edit-style]').forEach(x=>x.classList.toggle('selected',x===btn))}));
  const editSettings=()=>({
    project_id:projectId,
    edit_style:$('[data-edit-style].selected')?.dataset.editStyle||'dynamic',
    color_grade:$('#color-grade')?.value||'auto',
    remove_silence:$('#remove-silence')?.checked??true,
    remove_fillers:$('#remove-fillers')?.checked??true,
    auto_punch:$('#auto-punch')?.checked??true,
    auto_transitions:$('#auto-transitions')?.checked??true,
    auto_music:$('#auto-music')?.checked??true
  });
  $('[data-auto-edit]')?.addEventListener('click',async e=>{const btn=e.currentTarget;busy(btn,true,'Analysing and cutting…');try{await api('project_settings',editSettings());const d=await api('auto_edit',{project_id:projectId});toast(d.message);if(d.reload)location.reload()}catch(err){toast(err.message,'error');busy(btn,false)}});

  $('#sound-volume')?.addEventListener('input',e=>{$('#volume-output').textContent=Math.round(e.target.value*100)+'%';if(audio)audio.volume=Number(e.target.value)});
  let soundCategory='all';
  const filterSounds=()=>{const query=($('#sound-search')?.value||'').trim().toLowerCase();$$('.sound-item').forEach(item=>{const category=item.dataset.category||'';const haystack=(item.dataset.title||'')+' '+category;const categoryMatch=soundCategory==='all'||category===soundCategory||category==='none';item.hidden=!(categoryMatch&&(!query||haystack.includes(query)))})};
  $('#sound-search')?.addEventListener('input',filterSounds);
  $$('[data-sound-category]').forEach(btn=>btn.addEventListener('click',()=>{$$('[data-sound-category]').forEach(x=>x.classList.toggle('selected',x===btn));soundCategory=btn.dataset.soundCategory||'all';filterSounds()}));
  $$('.sound-item').forEach(item=>item.addEventListener('click',()=>{$$('.sound-item').forEach(x=>x.classList.toggle('selected',x===item));selectedSound=item.dataset.soundId||'';if(audio){audio.pause();audio=null}if(item.dataset.audio){audio=new Audio(item.dataset.audio);audio.volume=Number($('#sound-volume')?.value||.25);audio.currentTime=Number($('#sound-trim')?.value||0);audio.play().catch(()=>{})}}));
  $('[data-save-settings]')?.addEventListener('click',async e=>{const btn=e.currentTarget;busy(btn,true,'Saving…');try{const d=await api('project_settings',{project_id:projectId,sound_id:selectedSound||null,sound_volume:Number($('#sound-volume')?.value||.25),sound_trim_start:Number($('#sound-trim')?.value||0)});toast(d.message+' Rebuild the auto edit if automatic music is enabled.')}catch(err){toast(err.message,'error')}busy(btn,false)});

  const renderContent=c=>{const labels={hook:'Hook',title:'Video title',instagram:'Instagram caption',whatsapp:'WhatsApp status',facebook:'Facebook post',x:'X post',hashtags:'Hashtags'};return Object.entries(labels).map(([k,l])=>`<article><div><span>${l}</span><button data-copy aria-label="Copy">⧉</button></div><textarea readonly rows="${['instagram','facebook'].includes(k)?5:3}">${escapeHTML(Array.isArray(c[k])?c[k].join(' '):(c[k]||''))}</textarea></article>`).join('')};
  $('[data-generate-content]')?.addEventListener('click',async e=>{const btn=e.currentTarget;busy(btn,true,'Writing…');try{const d=await api('generate_content',{project_id:projectId});$('#content-results').innerHTML=renderContent(d.content);toast(d.message)}catch(err){toast(err.message,'error')}busy(btn,false)});
  $('#content-results')?.addEventListener('click',e=>{const btn=e.target.closest('[data-copy]');if(!btn)return;const text=btn.closest('article').querySelector('textarea').value;navigator.clipboard.writeText(text).then(()=>toast('Copied.'))});
  $('[data-render]')?.addEventListener('click',async e=>{const btn=e.currentTarget;busy(btn,true,'Building final edit…');try{const d=await api('render',{project_id:projectId});toast(d.message);if(d.download){const a=document.createElement('a');a.href=d.download;a.download='';document.body.append(a);a.click();a.remove()}setTimeout(()=>location.reload(),1200)}catch(err){toast(err.message,'error');busy(btn,false)}});
  $('[data-delete-project]')?.addEventListener('click',async()=>{if(!confirm('Delete this project and all of its exports?'))return;try{const d=await api('delete_project',{project_id:projectId});location.href=d.redirect}catch(e){toast(e.message,'error')}});
})();
