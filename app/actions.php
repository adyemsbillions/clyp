<?php
declare(strict_types=1);
require_once __DIR__ . '/services.php';

function api_dispatch(string $action): never {
    try {
        match($action){
          'upload'=>api_upload(), 'transcribe'=>api_transcribe(), 'manual_transcript'=>api_manual_transcript(),
          'save_captions'=>api_save_captions(), 'project_settings'=>api_project_settings(), 'auto_edit'=>api_auto_edit(), 'generate_content'=>api_generate_content(),
          'render'=>api_render(), 'delete_project'=>api_delete_project(), 'subscribe'=>api_subscribe(),
          default=>json_response(['ok'=>false,'message'=>'Unknown action.'],404),
        };
    } catch(Throwable $e){
        error_log('CLYP: '.$e->getMessage().' '.$e->getTraceAsString());
        json_response(['ok'=>false,'message'=>env('APP_DEBUG',false)?$e->getMessage():'Something went wrong. Please try again.'],500);
    }
}
function api_upload(): never {
    $u=require_auth(); verify_csrf();
    if(empty($_FILES['video'])||!is_uploaded_file($_FILES['video']['tmp_name'])) json_response(['ok'=>false,'message'=>'Choose an MP4 or MOV video.'],422);
    $f=$_FILES['video']; if((int)$f['error']!==UPLOAD_ERR_OK) json_response(['ok'=>false,'message'=>'Upload failed with code '.(int)$f['error'].'. Check PHP upload limits.'],422);
    if((int)$f['size']>500*1024*1024) json_response(['ok'=>false,'message'=>'Video must be 500 MB or smaller.'],422);
    $ext=strtolower(pathinfo((string)$f['name'],PATHINFO_EXTENSION)); if(!in_array($ext,['mp4','mov'],true)) json_response(['ok'=>false,'message'=>'Only MP4 and MOV videos are supported.'],422);
    $mime=(new finfo(FILEINFO_MIME_TYPE))->file($f['tmp_name']); if(!in_array($mime,['video/mp4','video/quicktime','application/octet-stream'],true)) json_response(['ok'=>false,'message'=>'This does not appear to be a valid MP4 or MOV video.'],422);
    $name=bin2hex(random_bytes(16)).'.'.$ext; $dest=storage_path('uploads',$name); if(!move_uploaded_file($f['tmp_name'],$dest)) throw new RuntimeException('Could not save the uploaded video.');
    $media=new MediaService(); $duration=$media->duration($dest); $title=trim((string)($_POST['title']??pathinfo((string)$f['name'],PATHINFO_FILENAME))); if($title==='')$title='Untitled video';
    $storageKey=(new CloudStorageService())->put($dest,'uploads/'.(int)$u['id'].'/'.$name);
    $s=db()->prepare('INSERT INTO projects (user_id,title,video_file,storage_key,original_name,caption_style,status,duration,sound_volume,sound_trim_start,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)');
    $now=date('Y-m-d H:i:s'); $s->execute([(int)$u['id'],mb_substr($title,0,120),relative_storage_path($dest),$storageKey,(string)$f['name'],'viral','uploaded',$duration,.25,0,$now,$now]);
    json_response(['ok'=>true,'project_id'=>(int)db()->lastInsertId(),'redirect'=>'/project?id='.(int)db()->lastInsertId()]);
}
function api_transcribe(): never {
    $u=require_auth(); verify_csrf(); $d=json_input()+$_POST; $id=(int)($d['project_id']??0); $p=project_for_user($id,(int)$u['id']);
    $video=BASE_PATH.'/'.$p['video_file']; $media=new MediaService(); $ai=new GeminiService();
    db()->prepare("UPDATE projects SET status='transcribing',updated_at=? WHERE id=?")->execute([date('Y-m-d H:i:s'),$id]);
    try {
        $chunks=$media->audioChunks($video,$id); $offset=0.0; $all=[]; $previous='';
        foreach($chunks as $chunk){ $chunkDuration=max(.5,$media->duration($chunk)); $r=$ai->transcribe($chunk,$previous,$chunkDuration); $segments=$r['segments']??[]; foreach($segments as $seg){ foreach(smart_caption_chunks((string)($seg['text']??''),$offset+(float)($seg['start']??0),$offset+(float)($seg['end']??0)) as $c)$all[]=$c; } $offset+=$chunkDuration; $previous=(string)($r['text']??''); }
        if(!$all) throw new RuntimeException('No speech was detected. Try the manual transcript option.');
        db()->beginTransaction(); db()->prepare('DELETE FROM captions WHERE project_id=?')->execute([$id]); $s=db()->prepare('INSERT INTO captions (project_id,caption_text,start_time,end_time,position_index) VALUES (?,?,?,?,?)'); foreach($all as $i=>$c)$s->execute([$id,$c['text'],$c['start'],$c['end'],$i]); db()->prepare("UPDATE projects SET status='captioned',edit_plan_json=NULL,edited_duration=0,updated_at=? WHERE id=?")->execute([date('Y-m-d H:i:s'),$id]); db()->commit();
    } catch(Throwable $e) {
        if(db()->inTransaction()) db()->rollBack();
        db()->prepare("UPDATE projects SET status='uploaded',updated_at=? WHERE id=?")->execute([date('Y-m-d H:i:s'),$id]);
        throw $e;
    }
    json_response(['ok'=>true,'message'=>'Captions generated.','reload'=>true]);
}
function api_manual_transcript(): never {
    $u=require_auth(); verify_csrf(); $d=json_input()+$_POST; $id=(int)($d['project_id']??0); $p=project_for_user($id,(int)$u['id']); $text=trim((string)($d['transcript']??''));
    if(mb_strlen($text)<3) json_response(['ok'=>false,'message'=>'Paste a transcript first.'],422);
    $sentences=preg_split('/(?<=[.!?])\s+|\n+/',preg_replace('/\s+/',' ',$text)?:$text)?:[$text]; $duration=max(3,(float)$p['duration']); $total=max(1,array_sum(array_map(fn($x)=>max(1,str_word_count($x)),$sentences))); $cursor=0; $all=[];
    foreach($sentences as $sentence){ $portion=max(1,str_word_count($sentence))/$total*$duration; foreach(smart_caption_chunks($sentence,$cursor,min($duration,$cursor+$portion)) as $c)$all[]=$c; $cursor+=$portion; }
    db()->beginTransaction(); db()->prepare('DELETE FROM captions WHERE project_id=?')->execute([$id]); $s=db()->prepare('INSERT INTO captions (project_id,caption_text,start_time,end_time,position_index) VALUES (?,?,?,?,?)'); foreach($all as $i=>$c)$s->execute([$id,$c['text'],$c['start'],$c['end'],$i]); db()->prepare("UPDATE projects SET status='captioned',edit_plan_json=NULL,edited_duration=0,updated_at=? WHERE id=?")->execute([date('Y-m-d H:i:s'),$id]); db()->commit();
    json_response(['ok'=>true,'message'=>'Timed captions created from your transcript.','reload'=>true]);
}
function api_save_captions(): never {
    $u=require_auth(); verify_csrf(); $d=json_input(); $id=(int)($d['project_id']??0); project_for_user($id,(int)$u['id']); $caps=$d['captions']??[]; if(!is_array($caps)) json_response(['ok'=>false,'message'=>'Invalid captions.'],422);
    db()->beginTransaction(); db()->prepare('DELETE FROM captions WHERE project_id=?')->execute([$id]); $s=db()->prepare('INSERT INTO captions (project_id,caption_text,start_time,end_time,position_index) VALUES (?,?,?,?,?)'); foreach(array_values($caps) as $i=>$c){$text=trim((string)($c['text']??''));$start=max(0,(float)($c['start']??0));$end=max($start+.1,(float)($c['end']??$start+.1));if($text!=='')$s->execute([$id,$text,$start,$end,$i]);} db()->prepare("UPDATE projects SET status='captioned',edit_plan_json=NULL,edited_duration=0,updated_at=? WHERE id=?")->execute([date('Y-m-d H:i:s'),$id]); db()->commit(); json_response(['ok'=>true,'message'=>'Captions saved.']);
}
function api_project_settings(): never {
    $u=require_auth(); verify_csrf(); $d=json_input(); $id=(int)($d['project_id']??0); $p=project_for_user($id,(int)$u['id']);
    $style=(string)($d['caption_style']??$p['caption_style']??'viral');
    if(!in_array($style,['viral','professional','business','motivational','educational','comedy'],true)) $style='viral';
    $soundId=array_key_exists('sound_id',$d) && $d['sound_id']!=='' && $d['sound_id']!==null ? (int)$d['sound_id'] : ($p['sound_id']!==null?(int)$p['sound_id']:null);
    if($soundId!==null){$q=db()->prepare('SELECT id FROM sounds WHERE id=?');$q->execute([$soundId]);if(!$q->fetchColumn())$soundId=null;}
    $volume=max(0,min(1,(float)($d['sound_volume']??$p['sound_volume']??.25)));
    $trim=max(0,(float)($d['sound_trim_start']??$p['sound_trim_start']??0));
    $editStyle=(string)($d['edit_style']??$p['edit_style']??'dynamic');
    if(!in_array($editStyle,['dynamic','clean','cinematic','podcast'],true)) $editStyle='dynamic';
    $grade=(string)($d['color_grade']??$p['color_grade']??'auto');
    if(!in_array($grade,['auto','natural','clean','cinematic','warm','cool'],true)) $grade='auto';
    $bool=static fn(string $key,int $fallback): int => array_key_exists($key,$d)?(!empty($d[$key])?1:0):$fallback;
    $removeSilence=$bool('remove_silence',(int)($p['remove_silence']??1));
    $removeFillers=$bool('remove_fillers',(int)($p['remove_fillers']??1));
    $transitions=$bool('auto_transitions',(int)($p['auto_transitions']??1));
    $punch=$bool('auto_punch',(int)($p['auto_punch']??1));
    $music=$bool('auto_music',(int)($p['auto_music']??1));
    db()->prepare('UPDATE projects SET caption_style=?,sound_id=?,sound_volume=?,sound_trim_start=?,edit_style=?,color_grade=?,remove_silence=?,remove_fillers=?,auto_transitions=?,auto_punch=?,auto_music=?,edit_plan_json=NULL,edited_duration=0,updated_at=? WHERE id=?')
        ->execute([$style,$soundId,$volume,$trim,$editStyle,$grade,$removeSilence,$removeFillers,$transitions,$punch,$music,date('Y-m-d H:i:s'),$id]);
    json_response(['ok'=>true,'message'=>'Project settings saved.']);
}

function api_auto_edit(): never {
    $u=require_auth(); verify_csrf(); $d=json_input(); $id=(int)($d['project_id']??0); $p=project_for_user($id,(int)$u['id']);
    $s=db()->prepare('SELECT * FROM captions WHERE project_id=? ORDER BY position_index');$s->execute([$id]);$captions=$s->fetchAll();
    if(!$captions) json_response(['ok'=>false,'message'=>'Generate captions first so Clyp can cut filler words and align the edit.'],422);
    $media=new MediaService();
    $plan=$media->buildAutoEditPlan($p,$captions);
    $soundId=$p['sound_id']!==null?(int)$p['sound_id']:null;
    if((int)($p['auto_music']??1)===1){
        $category=(string)$plan['sound_category'];
        $q=db()->prepare('SELECT id FROM sounds WHERE category=? ORDER BY id LIMIT 1');$q->execute([$category]);
        $found=$q->fetchColumn();
        if(!$found){$q=db()->query('SELECT id FROM sounds ORDER BY id LIMIT 1');$found=$q->fetchColumn();}
        if($found) $soundId=(int)$found;
    }
    $now=date('Y-m-d H:i:s');
    db()->prepare("UPDATE projects SET auto_edit_enabled=1,edit_plan_json=?,edited_duration=?,sound_id=?,sound_volume=?,status='planned',updated_at=? WHERE id=?")
        ->execute([json_encode($plan,JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE),(float)$plan['edited_duration'],$soundId,.18,$now,$id]);
    json_response(['ok'=>true,'message'=>'One-click edit plan created. Clyp found '.count($plan['cuts']).' cuts and will save '.number_format((float)$plan['removed_seconds'],1).' seconds.','plan'=>$plan,'reload'=>true]);
}

function api_generate_content(): never {
    $u=require_auth(); verify_csrf(); $d=json_input(); $id=(int)($d['project_id']??0); $p=project_for_user($id,(int)$u['id']); $s=db()->prepare('SELECT caption_text FROM captions WHERE project_id=? ORDER BY position_index'); $s->execute([$id]); $transcript=implode(' ',array_column($s->fetchAll(),'caption_text')); if(trim($transcript)==='')json_response(['ok'=>false,'message'=>'Generate or add captions first.'],422); $out=(new GeminiService())->generateContent($transcript,(string)$p['caption_style']); db()->prepare('INSERT INTO generated_content (project_id,content_json,created_at) VALUES (?,?,?)')->execute([$id,json_encode($out,JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES),date('Y-m-d H:i:s')]); json_response(['ok'=>true,'content'=>$out,'message'=>!empty($out['_demo'])?'Content created in local demo mode. Add a Gemini API key for richer copy.':'Social content generated.']);
}
function api_render(): never {
    $u=require_auth(); verify_csrf(); $d=json_input(); $id=(int)($d['project_id']??0); $p=project_for_user($id,(int)$u['id']); if(!plan_can_export($u)) json_response(['ok'=>false,'message'=>'You have reached this month’s export limit. Upgrade your plan to continue.'],402); $s=db()->prepare('SELECT * FROM captions WHERE project_id=? ORDER BY position_index');$s->execute([$id]);$caps=$s->fetchAll();if(!$caps)json_response(['ok'=>false,'message'=>'Add captions before exporting.'],422); $sound=null;if($p['sound_id']){$q=db()->prepare('SELECT * FROM sounds WHERE id=?');$q->execute([(int)$p['sound_id']]);$sound=$q->fetch()?:null;}
    db()->prepare("UPDATE projects SET status='rendering',updated_at=? WHERE id=?")->execute([date('Y-m-d H:i:s'),$id]);
    try {
        $output=(new MediaService())->render($p,$caps,$sound,$u['plan']==='free');
        $cloudKey=(new CloudStorageService())->put($output,'exports/'.(int)$u['id'].'/'.basename($output));
        $now=date('Y-m-d H:i:s'); db()->prepare('INSERT INTO exports (project_id,export_url,storage_key,created_at) VALUES (?,?,?,?)')->execute([$id,relative_storage_path($output),$cloudKey,$now]); db()->prepare("UPDATE projects SET status='exported',updated_at=? WHERE id=?")->execute([$now,$id]); $exportId=(int)db()->lastInsertId();
    } catch(Throwable $e) {
        db()->prepare('UPDATE projects SET status=?,updated_at=? WHERE id=?')->execute([(int)($p['auto_edit_enabled']??0)===1?'planned':'captioned',date('Y-m-d H:i:s'),$id]);
        throw $e;
    }
    json_response(['ok'=>true,'message'=>'Your HD video is ready.','download'=>'/media?type=export&id='.$exportId,'reload'=>true]);
}
function api_delete_project(): never {
    $u=require_auth(); verify_csrf(); $d=json_input(); $id=(int)($d['project_id']??0); $p=project_for_user($id,(int)$u['id']); $files=[BASE_PATH.'/'.$p['video_file']];$cloudKeys=[$p['storage_key']??null];$s=db()->prepare('SELECT export_url,storage_key FROM exports WHERE project_id=?');$s->execute([$id]);foreach($s->fetchAll() as $x){$files[]=BASE_PATH.'/'.$x['export_url'];$cloudKeys[]=$x['storage_key']??null;}db()->prepare('DELETE FROM projects WHERE id=? AND user_id=?')->execute([$id,(int)$u['id']]);foreach($files as $f)if(is_file($f))@unlink($f);$cloud=new CloudStorageService();foreach($cloudKeys as $key){try{$cloud->delete(is_string($key)?$key:null);}catch(Throwable $e){error_log('CLYP R2 delete: '.$e->getMessage());}}json_response(['ok'=>true,'redirect'=>'/dashboard']);
}
function api_subscribe(): never {
    $u=require_auth(); verify_csrf(); $d=json_input(); $plan=(string)($d['plan']??''); $plans=plans(); if(!isset($plans[$plan])||$plan==='free')json_response(['ok'=>false,'message'=>'Choose a paid plan.'],422); $pay=new PaystackService(); if(!$pay->configured()){db()->prepare('UPDATE users SET plan=? WHERE id=?')->execute([$plan,(int)$u['id']]);db()->prepare('INSERT INTO subscriptions (user_id,plan,amount,status,reference,created_at) VALUES (?,?,?,?,?,?)')->execute([(int)$u['id'],$plan,$plans[$plan]['amount'],'demo_active','DEMO-'.time(),date('Y-m-d H:i:s')]);json_response(['ok'=>true,'message'=>'Demo plan activated. Add Paystack keys before accepting real payments.','redirect'=>'/dashboard']);} $tx=$pay->initialize($u['email'],$plan,$plans[$plan]['amount']); $_SESSION['pending_plan']=$plan; json_response(['ok'=>true,'redirect'=>$tx['authorization_url']??'/pricing']);
}
