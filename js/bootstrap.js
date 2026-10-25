// Local design storage shared by the dashboard and editor. Designs live in this
// browser's localStorage; nothing is sent to a server.
const ClypStore=(()=>{
  const KEY='clyp:projects';
  function read(){try{const list=JSON.parse(localStorage.getItem(KEY)||'[]');return Array.isArray(list)?list:[]}catch{return []}}
  function write(list){localStorage.setItem(KEY,JSON.stringify(list))}
  function newId(){return 'd_'+Date.now().toString(36)+Math.random().toString(36).slice(2,8)}
  return {
    list(){return read().sort((a,b)=>String(b.updated_at||'').localeCompare(String(a.updated_at||'')))},
    get(id){return read().find(p=>p.id===id)||null},
    // Throws when the browser's storage quota is full, so the editor can report it.
    save(design){
      const list=read(),now=new Date().toISOString();
      const saved={...design,id:design.id||newId(),created_at:design.created_at||now,updated_at:now};
      const index=list.findIndex(p=>p.id===saved.id);
      if(index>=0)list[index]=saved;else list.push(saved);
      write(list);
      return saved;
    },
    remove(id){write(read().filter(p=>p.id!==id))}
  };
})();
