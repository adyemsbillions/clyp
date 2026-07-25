<?php
declare(strict_types=1);
require_once __DIR__ . '/bootstrap.php';

final class HttpClient {
    public static function json(string $url, string $method='GET', array $headers=[], ?array $body=null): array {
        if(!function_exists('curl_init')) throw new RuntimeException('The PHP cURL extension is required for external API requests.');
        $ch=curl_init($url);
        curl_setopt_array($ch,[CURLOPT_RETURNTRANSFER=>true,CURLOPT_CUSTOMREQUEST=>$method,CURLOPT_TIMEOUT=>180,CURLOPT_HTTPHEADER=>$headers]);
        if($body!==null) curl_setopt($ch,CURLOPT_POSTFIELDS,json_encode($body,JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE));
        $raw=curl_exec($ch); $status=(int)curl_getinfo($ch,CURLINFO_HTTP_CODE); $error=curl_error($ch); curl_close($ch);
        if($raw===false) throw new RuntimeException('Network error: '.$error);
        $data=json_decode($raw,true);
        if($status<200||$status>=300) throw new RuntimeException((string)($data['error']['message']??$data['message']??'Remote service error').' (HTTP '.$status.')');
        return is_array($data)?$data:[];
    }
}


/**
 * Optional Cloudflare R2 mirror using the S3-compatible API and AWS Signature V4.
 * Local files remain available for FFmpeg and authenticated media streaming.
 */
final class CloudStorageService {
    private string $driver;
    private string $accountId;
    private string $accessKey;
    private string $secretKey;
    private string $bucket;

    public function __construct(){
        $this->driver=strtolower((string)env('STORAGE_DRIVER','local'));
        $this->accountId=(string)env('R2_ACCOUNT_ID','');
        $this->accessKey=(string)env('R2_ACCESS_KEY_ID','');
        $this->secretKey=(string)env('R2_SECRET_ACCESS_KEY','');
        $this->bucket=(string)env('R2_BUCKET','');
    }
    public function isR2(): bool { return $this->driver==='r2'; }
    public function configured(): bool {
        return $this->isR2() && $this->accountId!=='' && $this->accessKey!=='' && $this->secretKey!=='' && $this->bucket!=='';
    }
    public function put(string $localFile,string $key): ?string {
        if(!$this->isR2()) return null;
        if(!$this->configured()) throw new RuntimeException('STORAGE_DRIVER is r2, but one or more R2 credentials are missing.');
        if(!is_file($localFile)) throw new RuntimeException('The file selected for cloud storage is missing.');
        $key=$this->normaliseKey($key);
        $mime=(new finfo(FILEINFO_MIME_TYPE))->file($localFile) ?: 'application/octet-stream';
        $handle=fopen($localFile,'rb');
        if($handle===false) throw new RuntimeException('Could not open the local file for R2 upload.');
        try {
            $this->request('PUT',$key,$mime,hash_file('sha256',$localFile),$handle,(int)filesize($localFile));
        } finally { fclose($handle); }
        return $key;
    }
    public function delete(?string $key): void {
        if(!$this->configured()||$key===null||trim($key)==='') return;
        $this->request('DELETE',$this->normaliseKey($key),'application/octet-stream',hash('sha256',''),null,0);
    }
    private function request(string $method,string $key,string $contentType,string $payloadHash,$handle,int $size): void {
        if(!function_exists('curl_init')) throw new RuntimeException('The PHP cURL extension is required for Cloudflare R2.');
        $host=$this->accountId.'.r2.cloudflarestorage.com';
        $canonicalUri='/'.rawurlencode($this->bucket).'/'.implode('/',array_map('rawurlencode',explode('/',$key)));
        $url='https://'.$host.$canonicalUri;
        $amzDate=gmdate('Ymd\\THis\\Z');
        $date=substr($amzDate,0,8);
        $headers=[
            'content-type'=>trim($contentType),
            'host'=>$host,
            'x-amz-content-sha256'=>$payloadHash,
            'x-amz-date'=>$amzDate,
        ];
        ksort($headers);
        $canonicalHeaders='';
        foreach($headers as $name=>$value) $canonicalHeaders.=$name.':'.preg_replace('/\\s+/',' ',trim($value))."\n";
        $signedHeaders=implode(';',array_keys($headers));
        $canonicalRequest=$method."\n".$canonicalUri."\n\n".$canonicalHeaders."\n".$signedHeaders."\n".$payloadHash;
        $scope=$date.'/auto/s3/aws4_request';
        $stringToSign="AWS4-HMAC-SHA256\n{$amzDate}\n{$scope}\n".hash('sha256',$canonicalRequest);
        $kDate=hash_hmac('sha256',$date,'AWS4'.$this->secretKey,true);
        $kRegion=hash_hmac('sha256','auto',$kDate,true);
        $kService=hash_hmac('sha256','s3',$kRegion,true);
        $kSigning=hash_hmac('sha256','aws4_request',$kService,true);
        $signature=hash_hmac('sha256',$stringToSign,$kSigning);
        $authorization='AWS4-HMAC-SHA256 Credential='.$this->accessKey.'/'.$scope.', SignedHeaders='.$signedHeaders.', Signature='.$signature;
        $requestHeaders=[
            'Authorization: '.$authorization,
            'Content-Type: '.$headers['content-type'],
            'Host: '.$host,
            'x-amz-content-sha256: '.$payloadHash,
            'x-amz-date: '.$amzDate,
        ];
        $ch=curl_init($url);
        $options=[
            CURLOPT_RETURNTRANSFER=>true,
            CURLOPT_CUSTOMREQUEST=>$method,
            CURLOPT_HTTPHEADER=>$requestHeaders,
            CURLOPT_TIMEOUT=>900,
        ];
        if($method==='PUT'){
            $options[CURLOPT_UPLOAD]=true;
            $options[CURLOPT_INFILE]=$handle;
            $options[CURLOPT_INFILESIZE]=$size;
        }
        curl_setopt_array($ch,$options);
        $raw=curl_exec($ch);
        $status=(int)curl_getinfo($ch,CURLINFO_HTTP_CODE);
        $error=curl_error($ch);
        curl_close($ch);
        if($raw===false) throw new RuntimeException('R2 connection failed: '.$error);
        if($status<200||$status>=300){
            $message=trim(strip_tags((string)$raw));
            throw new RuntimeException('R2 request failed (HTTP '.$status.').'.($message!==''?' '.$message:''));
        }
    }
    private function normaliseKey(string $key): string {
        $key=str_replace('\\','/',trim($key));
        $key=preg_replace('#/+#','/',$key)??$key;
        return ltrim($key,'/');
    }
}

final class GeminiService {
    private string $key;
    private string $model;
    private string $apiBase;

    public function __construct(){
        $this->key=trim((string)env('GEMINI_API_KEY',''));
        $this->model=trim((string)env('GEMINI_MODEL','gemini-3.5-flash'));
        if($this->model==='gemini-3.6-flash') $this->model='gemini-3.5-flash';
        $this->apiBase=rtrim((string)env('GEMINI_API_BASE','https://generativelanguage.googleapis.com/v1beta'),'/');
    }

    public function configured(): bool { return $this->key!==''; }

    public function transcribe(string $file,string $previous='',float $duration=0): array {
        if(!$this->configured()) throw new RuntimeException('Add GEMINI_API_KEY to .env, or use the manual transcript option.');
        if(!is_file($file)) throw new RuntimeException('The extracted audio file is missing.');

        // Inline Gemini requests are limited to 20 MB including JSON/base64 overhead.
        // Clyp's 10-minute 64 kbps chunks are normally about 5 MB, so this guard
        // catches custom settings that are too large before an expensive request.
        $size=(int)filesize($file);
        if($size>14*1024*1024){
            throw new RuntimeException('This audio chunk is too large for Gemini inline upload. Reduce TRANSCRIPTION_CHUNK_SECONDS in .env to 600 or lower.');
        }
        $bytes=file_get_contents($file);
        if($bytes===false) throw new RuntimeException('Clyp could not read the extracted audio file.');

        $language=trim((string)env('GEMINI_LANGUAGE','auto'));
        $context=$previous!=='' ? "
The previous chunk ended with this context: ".mb_substr(preg_replace('/\s+/',' ',trim($previous))?:$previous,-500).". Use it only to resolve a cut-off word; do not repeat it." : '';
        $prompt="Transcribe all spoken words in this audio accurately. Preserve the spoken language and wording; do not summarize or translate. Add natural punctuation. Return short chronological segments with start and end times in seconds relative to this audio chunk. Detect the language automatically".($language!==''&&strtolower($language)!=='auto'?", but expect {$language}":'').". Ignore music and non-speech sounds.{$context}";
        $schema=[
          'type'=>'object',
          'properties'=>[
            'text'=>['type'=>'string','description'=>'Complete punctuated transcript in chronological order.'],
            'segments'=>[
              'type'=>'array',
              'items'=>[
                'type'=>'object',
                'properties'=>[
                  'start'=>['type'=>'number','minimum'=>0,'description'=>'Segment start time in seconds.'],
                  'end'=>['type'=>'number','minimum'=>0,'description'=>'Segment end time in seconds.'],
                  'text'=>['type'=>'string','description'=>'Exact spoken words for this segment with punctuation.'],
                ],
                'required'=>['start','end','text'],
                'additionalProperties'=>false,
              ],
            ],
          ],
          'required'=>['text','segments'],
          'additionalProperties'=>false,
        ];
        $mime=$this->audioMime($file);
        $out=$this->generateJson([
          ['text'=>$prompt],
          ['inlineData'=>['mimeType'=>$mime,'data'=>base64_encode($bytes)]],
        ],$schema,900,8192);

        $text=trim((string)($out['text']??''));
        $segments=[];
        foreach(($out['segments']??[]) as $segment){
            if(!is_array($segment)) continue;
            $segmentText=trim((string)($segment['text']??''));
            if($segmentText==='') continue;
            $start=$this->seconds($segment['start']??0);
            $end=$this->seconds($segment['end']??$start+.5);
            if($duration>0){
                $start=min(max(0,$duration-.1),max(0,$start));
                $end=min($duration,max($start+.1,$end));
            } else {
                $start=max(0,$start);
                $end=max($start+.1,$end);
            }
            $segments[]=['start'=>$start,'end'=>$end,'text'=>$segmentText];
        }
        usort($segments,fn(array $a,array $b): int=>$a['start']<=>$b['start']);

        if($text==='' && $segments) $text=implode(' ',array_column($segments,'text'));
        if(!$segments && $text!==''){
            $segments[]=['start'=>0.0,'end'=>max(.5,$duration),'text'=>$text];
        }
        return ['text'=>$text,'segments'=>$segments,'duration'=>max(0,$duration)];
    }

    public function generateContent(string $transcript,string $style): array {
        if(!$this->configured()) return $this->fallbackContent($transcript,$style);
        $prompt="Create platform-ready social content from the video transcript below. Tone: {$style}. Write naturally, avoid unsupported claims, keep the X post under 260 characters, and return exactly 12 useful hashtags.

Transcript:
".mb_substr($transcript,0,30000);
        $schema=[
          'type'=>'object',
          'properties'=>[
            'hook'=>['type'=>'string'],
            'instagram'=>['type'=>'string'],
            'whatsapp'=>['type'=>'string'],
            'facebook'=>['type'=>'string'],
            'x'=>['type'=>'string'],
            'hashtags'=>['type'=>'array','minItems'=>12,'maxItems'=>12,'items'=>['type'=>'string']],
            'title'=>['type'=>'string'],
          ],
          'required'=>['hook','instagram','whatsapp','facebook','x','hashtags','title'],
          'additionalProperties'=>false,
        ];
        $out=$this->generateJson([
          ['text'=>$prompt],
        ],$schema,240,8192,'You are Clyp, a precise social-video copywriter. Produce concise, polished copy suitable for the requested platforms.');

        $fallback=$this->fallbackContent($transcript,$style);
        foreach(['hook','instagram','whatsapp','facebook','x','title'] as $key){
            $value=trim((string)($out[$key]??''));
            $out[$key]=$value!==''?$value:$fallback[$key];
        }
        $out['x']=mb_substr($out['x'],0,260);
        $tags=[];
        foreach(($out['hashtags']??[]) as $tag){
            $tag=preg_replace('/\s+/','',trim((string)$tag))?:'';
            if($tag==='') continue;
            if(!str_starts_with($tag,'#')) $tag='#'.$tag;
            if(!in_array($tag,$tags,true)) $tags[]=$tag;
        }
        foreach($fallback['hashtags'] as $tag){
            if(count($tags)>=12) break;
            if(!in_array($tag,$tags,true)) $tags[]=$tag;
        }
        $out['hashtags']=array_slice($tags,0,12);
        unset($out['_demo']);
        return $out;
    }

    private function generateJson(array $parts,array $schema,int $timeout,int $maxOutputTokens=8192,string $systemInstruction=''): array {
        if(!function_exists('curl_init')) throw new RuntimeException('The PHP cURL extension is required for Gemini API requests.');
        $url=$this->apiBase.'/models/'.rawurlencode($this->model).':generateContent';
        $body=[
          'contents'=>[['role'=>'user','parts'=>$parts]],
          'generationConfig'=>[
            'responseMimeType'=>'application/json',
            'responseJsonSchema'=>$schema,
            'maxOutputTokens'=>$maxOutputTokens,
          ],
        ];
        if($systemInstruction!=='') $body['systemInstruction']=['parts'=>[['text'=>$systemInstruction]]];
        $encoded=json_encode($body,JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE);
        if($encoded===false) throw new RuntimeException('Clyp could not prepare the Gemini request.');

        $ch=curl_init($url);
        curl_setopt_array($ch,[
          CURLOPT_RETURNTRANSFER=>true,
          CURLOPT_POST=>true,
          CURLOPT_POSTFIELDS=>$encoded,
          CURLOPT_HTTPHEADER=>['Content-Type: application/json','x-goog-api-key: '.$this->key],
          CURLOPT_CONNECTTIMEOUT=>30,
          CURLOPT_TIMEOUT=>$timeout,
        ]);
        $raw=curl_exec($ch);
        $status=(int)curl_getinfo($ch,CURLINFO_HTTP_CODE);
        $error=curl_error($ch);
        curl_close($ch);
        if($raw===false) throw new RuntimeException('Gemini connection failed: '.$error);
        $data=json_decode($raw,true);
        if($status<200||$status>=300){
            $message=is_array($data)?(string)($data['error']['message']??$data['message']??'Gemini request failed'):'Gemini request failed';
            throw new RuntimeException($message.' (HTTP '.$status.').');
        }
        if(!is_array($data)) throw new RuntimeException('Gemini returned an unreadable response.');
        $text='';
        foreach(($data['candidates'][0]['content']['parts']??[]) as $part){
            if(is_array($part)&&isset($part['text'])) $text.=(string)$part['text'];
        }
        if(trim($text)===''){
            $reason=(string)($data['promptFeedback']['blockReason']??$data['candidates'][0]['finishReason']??'');
            throw new RuntimeException('Gemini returned no usable content'.($reason!==''?' ('.$reason.')':'').'.');
        }
        $text=trim($text);
        if(str_starts_with($text,'```')){
            $text=preg_replace('/^```(?:json)?\s*/i','',$text)??$text;
            $text=preg_replace('/\s*```$/','',$text)??$text;
        }
        $out=json_decode($text,true);
        if(!is_array($out)) throw new RuntimeException('Gemini returned content in an unexpected format.');
        return $out;
    }

    private function audioMime(string $file): string {
        return match(strtolower(pathinfo($file,PATHINFO_EXTENSION))){
          'mp3'=>'audio/mp3',
          'wav'=>'audio/wav',
          'm4a'=>'audio/mp4',
          'aac'=>'audio/aac',
          'ogg'=>'audio/ogg',
          default=>(mime_content_type($file)?:'audio/mp3'),
        };
    }

    private function seconds(mixed $value): float {
        if(is_int($value)||is_float($value)||is_numeric($value)) return max(0,(float)$value);
        $text=trim((string)$value);
        if($text==='') return 0.0;
        $parts=array_map('floatval',explode(':',$text));
        if(count($parts)===3) return max(0,$parts[0]*3600+$parts[1]*60+$parts[2]);
        if(count($parts)===2) return max(0,$parts[0]*60+$parts[1]);
        return max(0,(float)$text);
    }

    private function fallbackContent(string $transcript,string $style): array {
        $clean=preg_replace('/\s+/',' ',trim($transcript))?:'A fresh video worth sharing.';
        $summary=mb_substr($clean,0,220).(mb_strlen($clean)>220?'…':'');
        $first=mb_substr($clean,0,90).(mb_strlen($clean)>90?'…':'');
        return [
          'hook'=>'Stop scrolling — '.$first,
          'instagram'=>$summary."

Save this and share it with someone who needs it.",
          'whatsapp'=>$first,
          'facebook'=>$summary."

What is your take?",
          'x'=>mb_substr($summary,0,245),
          'hashtags'=>['#Clyp','#VideoCreator','#ContentCreation','#SocialMedia','#CreatorTools','#VideoMarketing','#Reels','#TikTokTips','#InstagramReels','#NigeriaCreators','#DigitalContent','#CreateBetter'],
          'title'=>ucfirst($style).' video: '.mb_substr($clean,0,55),
          '_demo'=>true,
        ];
    }
}

final class MediaService {
    private string $ffmpeg;
    private string $ffprobe;

    public function __construct(){
        $this->ffmpeg=(string)env('FFMPEG_PATH','ffmpeg');
        $this->ffprobe=(string)env('FFPROBE_PATH','ffprobe');
    }

    private function run(array $parts): string {
        $cmd=implode(' ',array_map(fn($p)=>escapeshellarg((string)$p),$parts)).' 2>&1';
        exec($cmd,$out,$code);
        if($code!==0) throw new RuntimeException("Media processing failed.\n".implode("\n",array_slice($out,-18)));
        return implode("\n",$out);
    }

    private function runSoft(array $parts): array {
        $cmd=implode(' ',array_map(fn($p)=>escapeshellarg((string)$p),$parts)).' 2>&1';
        exec($cmd,$out,$code);
        return ['code'=>$code,'output'=>implode("\n",$out)];
    }

    public function duration(string $file): float {
        $result=$this->runSoft([$this->ffprobe,'-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',$file]);
        if($result['code']!==0) return 0.0;
        return max(0,(float)trim($result['output']));
    }

    public function hasAudio(string $file): bool {
        $result=$this->runSoft([$this->ffprobe,'-v','error','-select_streams','a:0','-show_entries','stream=index','-of','csv=p=0',$file]);
        return $result['code']===0 && trim($result['output'])!=='';
    }

    public function audioChunks(string $video,int $projectId): array {
        $dir=storage_path('tmp','project_'.$projectId);
        if(is_dir($dir)) {
            foreach(glob($dir.'/*')?:[] as $file) if(is_file($file)) @unlink($file);
        } elseif(!mkdir($dir,0775,true) && !is_dir($dir)) {
            throw new RuntimeException('Clyp could not create its temporary audio folder.');
        }
        if(!$this->hasAudio($video)) throw new RuntimeException('No audio track was detected in this video.');

        $chunkSeconds=max(60,(int)env('TRANSCRIPTION_CHUNK_SECONDS','600'));
        $duration=$this->duration($video);
        $chunkCount=$duration>0 ? max(1,(int)ceil($duration/$chunkSeconds)) : 1;
        $files=[];
        for($index=0;$index<$chunkCount;$index++) {
            $offset=$index*$chunkSeconds;
            $output=$dir.'/audio_'.str_pad((string)$index,3,'0',STR_PAD_LEFT).'.mp3';
            $args=[$this->ffmpeg,'-y'];
            if($offset>0) $args=array_merge($args,['-ss',(string)$offset]);
            $args=array_merge($args,['-i',$video]);
            if($duration>0) $args=array_merge($args,['-t',(string)min($chunkSeconds,max(.1,$duration-$offset))]);
            $args=array_merge($args,['-map','0:a:0','-vn','-ac','1','-ar','16000','-b:a','64k',$output]);
            $this->run($args);
            if(is_file($output) && filesize($output)>0) $files[]=$output;
        }
        if(!$files) throw new RuntimeException('Clyp could not extract audio from this video.');
        return $files;
    }

    public function buildAutoEditPlan(array $project,array $captions): array {
        $video=BASE_PATH.'/'.$project['video_file'];
        if(!is_file($video)) throw new RuntimeException('The original video file is missing.');
        $duration=max(.1,(float)$project['duration'],$this->duration($video));
        $removeSilence=(int)($project['remove_silence']??1)===1;
        $removeFillers=(int)($project['remove_fillers']??1)===1;
        $style=(string)($project['edit_style']??'dynamic');
        if(!in_array($style,['dynamic','clean','cinematic','podcast'],true)) $style='dynamic';

        $cuts=[];
        $silences=[];
        if($removeSilence && $this->hasAudio($video)) {
            $silences=$this->detectSilences($video,(float)env('AUTO_SILENCE_DB','-34'),(float)env('AUTO_SILENCE_MIN','0.48'));
            foreach($silences as $interval) {
                $pad=$style==='podcast'?.08:.12;
                $start=(float)$interval['start']+$pad;
                $end=(float)$interval['end']-$pad;
                if($end-$start>=.18) $cuts[]=['start'=>$start,'end'=>$end,'reason'=>'silence'];
            }
        }
        $fillers=[];
        if($removeFillers) {
            $fillers=$this->fillerIntervals($captions);
            foreach($fillers as $interval) $cuts[]=$interval+['reason'=>'filler'];
        }

        $cuts=$this->mergeIntervals($cuts,$duration,.13);
        // Avoid an over-edited result. Keep the largest cuts when an unusually noisy
        // transcript produces too many tiny filler ranges.
        if(count($cuts)>36) {
            usort($cuts,fn($a,$b)=>(($b['end']-$b['start'])<=>($a['end']-$a['start'])));
            $cuts=array_slice($cuts,0,36);
            $cuts=$this->mergeIntervals($cuts,$duration,.18);
        }
        $keeps=$this->complementIntervals($cuts,$duration);
        if(!$keeps) $keeps=[['start'=>0.0,'end'=>$duration]];

        $transition=$this->transitionDuration($style,count($keeps),(int)($project['auto_transitions']??1)===1);
        if($transition>0){$shortest=min(array_map(fn($x)=>(float)$x['end']-(float)$x['start'],$keeps));$transition=min($transition,max(.03,$shortest*.35));}
        $editedDuration=array_sum(array_map(fn($x)=>$x['end']-$x['start'],$keeps))-max(0,count($keeps)-1)*$transition;
        $editedDuration=max(.1,$editedDuration);
        $stats=$this->videoStats($video,$duration);
        $grade=(string)($project['color_grade']??'auto');
        if(!in_array($grade,['auto','natural','clean','cinematic','warm','cool'],true)) $grade='auto';

        $punchIndices=[];
        if((int)($project['auto_punch']??1)===1 && count($keeps)>1) {
            $every=$style==='dynamic'?2:($style==='cinematic'?3:4);
            foreach($keeps as $i=>$segment) {
                if($i>0 && $i%$every===0 && ($segment['end']-$segment['start'])>.75) $punchIndices[]=$i;
            }
        }

        return [
            'version'=>2,
            'source_duration'=>round($duration,3),
            'edited_duration'=>round($editedDuration,3),
            'removed_seconds'=>round(max(0,$duration-$editedDuration),3),
            'cuts'=>$cuts,
            'keeps'=>$keeps,
            'silence_count'=>count($silences),
            'filler_count'=>count($fillers),
            'edit_style'=>$style,
            'color_grade'=>$grade,
            'video_stats'=>$stats,
            'transition_duration'=>$transition,
            'punch_indices'=>$punchIndices,
            'sound_category'=>$this->autoSoundCategory((string)($project['caption_style']??'viral'),$style),
            'created_at'=>date(DATE_ATOM),
        ];
    }

    public function autoSoundCategory(string $captionStyle,string $editStyle): string {
        if($editStyle==='cinematic') return 'Cinematic';
        if($editStyle==='podcast'||in_array($captionStyle,['business','professional','educational'],true)) return 'Business';
        if($captionStyle==='motivational') return 'Motivational';
        if($captionStyle==='comedy') return 'Vlog';
        return $editStyle==='dynamic'?'Afro-inspired':'Tech';
    }

    public function render(array $project,array $captions,?array $sound,bool $watermark): string {
        $video=BASE_PATH.'/'.$project['video_file'];
        if(!is_file($video)) throw new RuntimeException('The original video file is missing.');
        $auto=(int)($project['auto_edit_enabled']??0)===1;
        $plan=json_decode((string)($project['edit_plan_json']??''),true);
        if($auto && (!is_array($plan)||empty($plan['keeps']))) $plan=$this->buildAutoEditPlan($project,$captions);
        if(!$auto) return $this->renderBasic($project,$captions,$sound,$watermark);
        return $this->renderAuto($project,$captions,$sound,$watermark,$plan);
    }

    private function renderBasic(array $project,array $captions,?array $sound,bool $watermark): string {
        $video=BASE_PATH.'/'.$project['video_file'];
        $duration=max((float)$project['duration'],$this->duration($video));
        $ass=$this->makeAss((int)$project['id'],$captions,(string)$project['caption_style'],$duration,$watermark);
        $name='clyp_'.$project['id'].'_'.date('Ymd_His').'.mp4';
        $output=storage_path('exports',$name);
        $filter='ass='.$this->escapeFilterPath($ass);
        $args=[$this->ffmpeg,'-y','-i',$video];
        if($sound && is_file(BASE_PATH.'/'.$sound['file_path'])) {
            $args=array_merge($args,['-stream_loop','-1','-i',BASE_PATH.'/'.$sound['file_path']]);
            $volume=max(0,min(1,(float)$project['sound_volume']));
            $trim=max(0,(float)$project['sound_trim_start']);
            if($this->hasAudio($video)) {
                $complex="[0:a]loudnorm=I=-16:LRA=11:TP=-1.5[a0];[1:a]atrim=start={$trim},asetpts=PTS-STARTPTS,volume={$volume}[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=2,alimiter=limit=.95[aout]";
                $args=array_merge($args,['-filter_complex',$complex,'-vf',$filter,'-map','0:v:0','-map','[aout]']);
            } else {
                $complex="[1:a]atrim=start={$trim},asetpts=PTS-STARTPTS,volume={$volume},alimiter=limit=.95[aout]";
                $args=array_merge($args,['-filter_complex',$complex,'-vf',$filter,'-map','0:v:0','-map','[aout]','-shortest']);
            }
        } else {
            $args=array_merge($args,['-vf',$filter,'-map','0:v:0','-map','0:a?']);
        }
        $args=array_merge($args,['-c:v','libx264','-preset','veryfast','-crf','19','-c:a','aac','-b:a','192k','-movflags','+faststart',$output]);
        $this->run($args);
        return $output;
    }

    private function renderAuto(array $project,array $captions,?array $sound,bool $watermark,array $plan): string {
        $video=BASE_PATH.'/'.$project['video_file'];
        $keeps=array_values(array_filter($plan['keeps']??[],fn($x)=>is_array($x)&&isset($x['start'],$x['end'])&&$x['end']>$x['start']));
        if(!$keeps) $keeps=[['start'=>0.0,'end'=>max(.1,(float)$project['duration'])]];
        $hasAudio=$this->hasAudio($video);
        $transition=max(0,(float)($plan['transition_duration']??0));
        if(count($keeps)>12) $transition=0;
        if($transition>0){$shortest=min(array_map(fn($x)=>(float)$x['end']-(float)$x['start'],$keeps));$transition=min($transition,max(.03,$shortest*.35));} // xfade graphs become expensive on very fragmented clips.
        $punchIndices=array_map('intval',$plan['punch_indices']??[]);
        $stats=(array)($plan['video_stats']??[]);
        $grade=$this->gradeFilter((string)($plan['color_grade']??'auto'),$stats);
        $targetW=max(2,(int)($stats['width']??0));$targetH=max(2,(int)($stats['height']??0));
        $filters=[];
        $durations=[];
        foreach($keeps as $i=>$segment) {
            $start=max(0,(float)$segment['start']);
            $end=max($start+.08,(float)$segment['end']);
            $durations[]=$end-$start;
            $vf="trim=start={$this->num($start)}:end={$this->num($end)},setpts=PTS-STARTPTS,{$grade},scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1";
            if(in_array($i,$punchIndices,true)) {
                $x=$i%2===0?'(iw-iw/1.065)*0.42':'(iw-iw/1.065)*0.58';
                $vf.=',crop=iw/1.065:ih/1.065:'.$x.':(ih-ih/1.065)/2,scale='.$targetW.':'.$targetH;
            }
            $vf.=',scale='.$targetW.':'.$targetH.',fps=30,settb=AVTB,format=yuv420p';
            $filters[]="[0:v]{$vf}[v{$i}]";
            if($hasAudio) $filters[]="[0:a]atrim=start={$this->num($start)}:end={$this->num($end)},asetpts=PTS-STARTPTS,aresample=async=1:first_pts=0[a{$i}]";
        }

        $count=count($keeps);
        if($count===1) {
            $videoLabel='v0';
            $audioLabel=$hasAudio?'a0':null;
        } elseif($transition>0) {
            $videoLabel='v0';
            $audioLabel=$hasAudio?'a0':null;
            $cumulative=$durations[0];
            for($i=1;$i<$count;$i++) {
                $out='vx'.$i;
                $offset=max(.01,$cumulative-$transition*$i);
                $kind=$this->transitionKind((string)($plan['edit_style']??'dynamic'),$i);
                $filters[]="[{$videoLabel}][v{$i}]xfade=transition={$kind}:duration={$this->num($transition)}:offset={$this->num($offset)}[{$out}]";
                $videoLabel=$out;
                if($hasAudio) {
                    $aout='ax'.$i;
                    $filters[]="[{$audioLabel}][a{$i}]acrossfade=d={$this->num($transition)}:c1=tri:c2=tri[{$aout}]";
                    $audioLabel=$aout;
                }
                $cumulative+=$durations[$i];
            }
        } else {
            if($hasAudio) {
                $inputs='';
                for($i=0;$i<$count;$i++) $inputs.="[v{$i}][a{$i}]";
                $filters[]=$inputs."concat=n={$count}:v=1:a=1[vcat][acat]";
                $videoLabel='vcat';
                $audioLabel='acat';
            } else {
                $inputs='';
                for($i=0;$i<$count;$i++) $inputs.="[v{$i}]";
                $filters[]=$inputs."concat=n={$count}:v=1:a=0[vcat]";
                $videoLabel='vcat';
                $audioLabel=null;
            }
        }

        $timeline=$this->timelineForKeeps($keeps,$transition);
        $editedCaptions=$this->remapCaptions($captions,$timeline,(int)($project['remove_fillers']??1)===1);
        $editedDuration=max(.1,(float)end($timeline)['output_end']);
        $ass=$this->makeAss((int)$project['id'],$editedCaptions,(string)$project['caption_style'],$editedDuration,$watermark);
        $filters[]="[{$videoLabel}]ass={$this->escapeFilterPath($ass)}[vout]";

        $args=[$this->ffmpeg,'-y','-i',$video];
        $soundFile=$sound ? BASE_PATH.'/'.$sound['file_path'] : '';
        $hasSound=$sound && is_file($soundFile);
        if($hasSound) $args=array_merge($args,['-stream_loop','-1','-i',$soundFile]);

        $audioOut=null;
        if($hasSound) {
            $volume=max(.03,min(.55,(float)$project['sound_volume']));
            $trim=max(0,(float)$project['sound_trim_start']);
            $filters[]="[1:a]atrim=start={$this->num($trim)}:duration={$this->num($editedDuration)},asetpts=PTS-STARTPTS,aresample=48000,volume={$this->num($volume)}[music]";
            if($audioLabel!==null) {
                $filters[]="[{$audioLabel}]loudnorm=I=-16:LRA=11:TP=-1.5,asplit=2[voice][side]";
                $filters[]="[music][side]sidechaincompress=threshold=.025:ratio=8:attack=20:release=350[ducked]";
                $filters[]="[voice][ducked]amix=inputs=2:duration=first:dropout_transition=2,alimiter=limit=.95[aout]";
            } else {
                $filters[]="[music]afade=t=in:st=0:d=.35,afade=t=out:st={$this->num(max(0,$editedDuration-.6))}:d=.6,alimiter=limit=.95[aout]";
            }
            $audioOut='aout';
        } elseif($audioLabel!==null) {
            $filters[]="[{$audioLabel}]loudnorm=I=-16:LRA=11:TP=-1.5,alimiter=limit=.95[aout]";
            $audioOut='aout';
        }

        $name='clyp_auto_'.$project['id'].'_'.date('Ymd_His').'.mp4';
        $output=storage_path('exports',$name);
        $args=array_merge($args,['-filter_complex',implode(';',$filters),'-map','[vout]']);
        if($audioOut!==null) $args=array_merge($args,['-map','['.$audioOut.']']);
        $args=array_merge($args,['-t',$this->num($editedDuration),'-c:v','libx264','-preset','veryfast','-crf','18','-c:a','aac','-b:a','192k','-movflags','+faststart',$output]);
        $this->run($args);
        return $output;
    }

    private function detectSilences(string $video,float $db,float $minimum): array {
        $result=$this->runSoft([$this->ffmpeg,'-hide_banner','-i',$video,'-af','silencedetect=noise='.$db.'dB:d='.$minimum,'-f','null','-']);
        $starts=[];$intervals=[];
        foreach(preg_split('/\R/',$result['output'])?:[] as $line) {
            if(preg_match('/silence_start:\s*([0-9.]+)/',$line,$m)) $starts[]=(float)$m[1];
            if(preg_match('/silence_end:\s*([0-9.]+)/',$line,$m)) {
                $start=array_shift($starts);
                if($start!==null && (float)$m[1]>$start) $intervals[]=['start'=>$start,'end'=>(float)$m[1]];
            }
        }
        return $intervals;
    }

    private function fillerIntervals(array $captions): array {
        $single=['um','uh','uhm','erm','er','hmm','mm','ah','eh'];
        $phrases=[['you','know'],['i','mean']];
        $out=[];
        foreach($captions as $caption) {
            $text=mb_strtolower(trim((string)($caption['caption_text']??'')));
            if($text==='') continue;
            preg_match_all("/[\\p{L}']+/u",$text,$matches);
            $words=$matches[0]??[];
            $count=count($words);
            if(!$count) continue;
            $start=(float)$caption['start_time'];
            $end=max($start+.1,(float)$caption['end_time']);
            $wordDuration=($end-$start)/$count;
            for($i=0;$i<$count;$i++) {
                $length=1;
                $isFiller=in_array($words[$i],$single,true);
                foreach($phrases as $phrase) {
                    if(array_slice($words,$i,count($phrase))===$phrase){$isFiller=true;$length=count($phrase);break;}
                }
                if(!$isFiller) continue;
                $s=max($start,$start+$i*$wordDuration-.015);
                $e=min($end,$start+($i+$length)*$wordDuration+.015);
                if($e-$s>=.08) $out[]=['start'=>$s,'end'=>$e,'reason'=>'filler'];
                $i+=$length-1;
            }
        }
        return $out;
    }

    private function cleanFillers(string $text): string {
        $text=preg_replace('/\b(?:um+|uh+|uhm+|erm+|hmm+|mm+|ah+|eh+)\b[,.]?\s*/iu','',$text)??$text;
        $text=preg_replace('/\b(?:you\s+know|i\s+mean)\b[,.]?\s*/iu','',$text)??$text;
        $text=preg_replace('/\s+([,.!?])/u','$1',$text)??$text;
        $text=preg_replace('/\s{2,}/u',' ',$text)??$text;
        return trim($text," \t\n\r\0\x0B,.-");
    }

    private function mergeIntervals(array $intervals,float $duration,float $gap=.1): array {
        $items=[];
        foreach($intervals as $item) {
            $start=max(0,min($duration,(float)($item['start']??0)));
            $end=max($start,min($duration,(float)($item['end']??$start)));
            if($end-$start<.06) continue;
            $items[]=['start'=>$start,'end'=>$end,'reason'=>(string)($item['reason']??'cut')];
        }
        usort($items,fn($a,$b)=>$a['start']<=>$b['start']);
        $merged=[];
        foreach($items as $item) {
            $last=count($merged)-1;
            if($last>=0 && $item['start']<=$merged[$last]['end']+$gap) {
                $merged[$last]['end']=max($merged[$last]['end'],$item['end']);
                if(!str_contains($merged[$last]['reason'],$item['reason'])) $merged[$last]['reason'].='+'.$item['reason'];
            } else $merged[]=$item;
        }
        return $merged;
    }

    private function complementIntervals(array $cuts,float $duration): array {
        $keeps=[];$cursor=0.0;
        foreach($cuts as $cut) {
            $start=(float)$cut['start'];$end=(float)$cut['end'];
            if($start-$cursor>=.18) $keeps[]=['start'=>$cursor,'end'=>$start];
            $cursor=max($cursor,$end);
        }
        if($duration-$cursor>=.18) $keeps[]=['start'=>$cursor,'end'=>$duration];
        return $keeps;
    }

    private function transitionDuration(string $style,int $segments,bool $enabled): float {
        if(!$enabled||$segments<2||$segments>12) return 0.0;
        return match($style){'cinematic'=>.20,'clean'=>.09,'podcast'=>.07,default=>.13};
    }

    private function transitionKind(string $style,int $index): string {
        if($style==='cinematic') return $index%2===0?'smoothleft':'fade';
        if($style==='clean'||$style==='podcast') return 'fade';
        return $index%3===0?'slideleft':'fadefast';
    }

    private function videoStats(string $video,float $duration): array {
        $probe=$this->runSoft([$this->ffprobe,'-v','error','-select_streams','v:0','-show_entries','stream=width,height','-of','json',$video]);
        $probeData=json_decode($probe['output'],true);$stream=$probeData['streams'][0]??[];
        $width=max(2,(int)($stream['width']??1080));$height=max(2,(int)($stream['height']??1920));
        if($width%2!==0)$width--;if($height%2!==0)$height--;
        $at=max(0,min($duration-.1,$duration*.35));
        $result=$this->runSoft([$this->ffmpeg,'-hide_banner','-ss',$this->num($at),'-i',$video,'-frames:v','1','-vf','signalstats,metadata=print','-f','null','-']);
        $values=[];
        foreach(['YAVG','SATAVG'] as $key) if(preg_match('/lavfi\.signalstats\.'.$key.'=([0-9.]+)/',$result['output'],$m)) $values[$key]=(float)$m[1];
        return ['brightness'=>round($values['YAVG']??112,2),'saturation'=>round($values['SATAVG']??45,2),'width'=>$width,'height'=>$height];
    }

    private function gradeFilter(string $profile,array $stats): string {
        $brightness=(float)($stats['brightness']??112);
        $saturation=(float)($stats['saturation']??45);
        if($profile==='auto') {
            $b=max(-.06,min(.07,(112-$brightness)/420));
            $sat=$saturation<35?1.18:($saturation>70?.94:1.07);
            $contrast=$brightness<72?1.04:1.07;
            $gamma=$brightness<80?1.08:1.01;
            return 'hqdn3d=1.0:1.0:4:4,eq=brightness='.$this->num($b).':contrast='.$this->num($contrast).':saturation='.$this->num($sat).':gamma='.$this->num($gamma).',colorbalance=rs=.015:gs=.005:bs=-.01,unsharp=5:5:.42:5:5:0';
        }
        return match($profile){
            'clean'=>'hqdn3d=1.2:1.2:5:5,eq=brightness=.015:contrast=1.045:saturation=1.04:gamma=1.02,colorbalance=rs=.006:bs=-.006,unsharp=5:5:.35:5:5:0',
            'cinematic'=>'hqdn3d=1.0:1.0:4:4,eq=brightness=-.015:contrast=1.13:saturation=.94:gamma=.98,colorbalance=rs=.035:gs=-.01:bs=.025,unsharp=5:5:.48:5:5:0',
            'warm'=>'hqdn3d=1.0:1.0:4:4,eq=brightness=.01:contrast=1.07:saturation=1.09:gamma=1.01,colorbalance=rs=.055:gs=.012:bs=-.045,unsharp=5:5:.4:5:5:0',
            'cool'=>'hqdn3d=1.0:1.0:4:4,eq=brightness=.005:contrast=1.07:saturation=1.04:gamma=1.01,colorbalance=rs=-.035:gs=.005:bs=.055,unsharp=5:5:.4:5:5:0',
            default=>'hqdn3d=.8:.8:3:3,eq=brightness=0:contrast=1.025:saturation=1.02:gamma=1.0,unsharp=5:5:.28:5:5:0',
        };
    }

    private function timelineForKeeps(array $keeps,float $transition): array {
        $timeline=[];$cursor=0.0;
        foreach($keeps as $i=>$keep) {
            $duration=(float)$keep['end']-(float)$keep['start'];
            $start=$i===0?0:$cursor-$transition;
            $end=$start+$duration;
            $timeline[]=['source_start'=>(float)$keep['start'],'source_end'=>(float)$keep['end'],'output_start'=>$start,'output_end'=>$end];
            $cursor=$end;
        }
        return $timeline;
    }

    private function remapCaptions(array $captions,array $timeline,bool $removeFillers): array {
        $out=[];
        foreach($captions as $caption) {
            $text=trim((string)$caption['caption_text']);
            if($removeFillers) $text=$this->cleanFillers($text);
            if($text==='') continue;
            $start=(float)$caption['start_time'];$end=(float)$caption['end_time'];
            foreach($timeline as $segment) {
                $s=max($start,(float)$segment['source_start']);
                $e=min($end,(float)$segment['source_end']);
                if($e-$s<.06) continue;
                $out[]=['caption_text'=>$text,'start_time'=>(float)$segment['output_start']+$s-(float)$segment['source_start'],'end_time'=>(float)$segment['output_start']+$e-(float)$segment['source_start']];
            }
        }
        usort($out,fn($a,$b)=>$a['start_time']<=>$b['start_time']);
        return $out;
    }

    private function makeAss(int $id,array $captions,string $style,float $duration,bool $watermark): string {
        $styles=[
          'viral'=>['font'=>'Impact','size'=>72,'primary'=>'&H0000E8FF','secondary'=>'&H00FFFFFF','outline'=>'&H00000000','back'=>'&H56000000','bold'=>-1,'border'=>1,'outlineSize'=>5,'shadow'=>2,'marginV'=>170,'transform'=>'upper'],
          'professional'=>['font'=>'Segoe UI Semibold','size'=>52,'primary'=>'&H00FFFFFF','secondary'=>'&H00D8D8D8','outline'=>'&H00302A27','back'=>'&H9A171717','bold'=>-1,'border'=>3,'outlineSize'=>1,'shadow'=>0,'marginV'=>150,'transform'=>'normal'],
          'business'=>['font'=>'Arial','size'=>54,'primary'=>'&H00FFF3DD','secondary'=>'&H00FFFFFF','outline'=>'&H00542E10','back'=>'&H770F172A','bold'=>-1,'border'=>3,'outlineSize'=>2,'shadow'=>0,'marginV'=>145,'transform'=>'normal'],
          'motivational'=>['font'=>'Arial Black','size'=>64,'primary'=>'&H0000E5FF','secondary'=>'&H00FFFFFF','outline'=>'&H00190C2F','back'=>'&H52000000','bold'=>-1,'border'=>1,'outlineSize'=>5,'shadow'=>2,'marginV'=>165,'transform'=>'upper'],
          'educational'=>['font'=>'Segoe UI Semibold','size'=>50,'primary'=>'&H00FFFFFF','secondary'=>'&H00E6F7FF','outline'=>'&H00683B16','back'=>'&HBB4E2612','bold'=>-1,'border'=>3,'outlineSize'=>1,'shadow'=>0,'marginV'=>135,'transform'=>'normal'],
          'comedy'=>['font'=>'Arial Black','size'=>66,'primary'=>'&H0065F7FF','secondary'=>'&H00FFFFFF','outline'=>'&H00420B37','back'=>'&H52000000','bold'=>-1,'border'=>1,'outlineSize'=>5,'shadow'=>3,'marginV'=>160,'transform'=>'upper'],
        ];
        $s=$styles[$style]??$styles['viral'];
        $head="[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nScaledBorderAndShadow: yes\nWrapStyle: 2\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n";
        $head.="Style: Caption,{$s['font']},{$s['size']},{$s['primary']},{$s['secondary']},{$s['outline']},{$s['back']},{$s['bold']},0,0,0,100,100,0,0,{$s['border']},{$s['outlineSize']},{$s['shadow']},2,70,70,{$s['marginV']},1\n";
        $head.="Style: Watermark,Arial,24,&HCCFFFFFF,&H000000FF,&H88000000,&H66000000,-1,0,0,0,100,100,0,0,3,1,0,9,30,30,30,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n";
        foreach($captions as $c) {
            $raw=trim((string)$c['caption_text']);
            if($raw==='') continue;
            if($s['transform']==='upper') $raw=mb_strtoupper($raw);
            $seconds=max(.12,(float)$c['end_time']-(float)$c['start_time']);
            $text=$this->karaokeText($raw,$seconds,$style);
            $head.='Dialogue: 0,'.$this->assTime((float)$c['start_time']).','.$this->assTime((float)$c['end_time']).",Caption,,0,0,0,,{$text}\n";
        }
        if($watermark) $head.='Dialogue: 1,0:00:00.00,'.$this->assTime($duration).",Watermark,,0,0,0,,Made with Clyp\n";
        $file=storage_path('tmp','captions_'.$id.'.ass');
        file_put_contents($file,$head);
        return $file;
    }

    private function karaokeText(string $text,float $duration,string $style): string {
        $safe=$this->assText($text);
        $words=preg_split('/\s+/u',$safe,-1,PREG_SPLIT_NO_EMPTY)?:[$safe];
        $count=max(1,count($words));
        $total=max($count,(int)round($duration*100));
        $base=(int)floor($total/$count);$remaining=$total-$base*$count;
        $parts=[];$lineLength=0;
        foreach($words as $i=>$word) {
            $k=$base+($i<$remaining?1:0);
            $plain=preg_replace('/\\[Nn]/','',$word)??$word;
            $length=mb_strlen($plain);
            $break=$lineLength>0 && $lineLength+$length+1>($style==='professional'||$style==='educational'?28:22);
            if($break){$parts[]='\\N';$lineLength=0;}
            $parts[]='{\\kf'.$k.'}'.$word;
            $lineLength+=$length+1;
        }
        $intro='{\\fad(70,110)\\fscx92\\fscy92\\t(0,130,\\fscx100\\fscy100)}';
        return $intro.implode(' ',$parts);
    }

    private function assText(string $t): string {
        $t=str_replace(['\\','{','}'],['\\\\','\\{','\\}'],$t);
        return str_replace("\n",'\\N',trim($t));
    }
    private function assTime(float $seconds): string {
        $seconds=max(0,$seconds);$h=floor($seconds/3600);$m=floor(($seconds%3600)/60);$s=$seconds%60;
        return sprintf('%d:%02d:%05.2f',$h,$m,$s);
    }
    private function escapeFilterPath(string $path): string {
        $p=str_replace('\\','/',$path);$p=str_replace(':','\\:',$p);
        return "'".str_replace("'","\\'",$p)."'";
    }
    private function num(float $value): string { return rtrim(rtrim(number_format($value,4,'.',''),'0'),'.') ?: '0'; }
}


final class PaystackService {
    private string $key;
    public function __construct(){ $this->key=(string)env('PAYSTACK_SECRET_KEY',''); }
    public function configured(): bool { return $this->key!==''; }
    public function initialize(string $email,string $plan,int $amount): array {
        if(!$this->configured()) throw new RuntimeException('Paystack is not configured.');
        $reference='CLYP-'.strtoupper(bin2hex(random_bytes(6)));
        $data=HttpClient::json('https://api.paystack.co/transaction/initialize','POST',['Authorization: Bearer '.$this->key,'Content-Type: application/json'],[
          'email'=>$email,'amount'=>(string)($amount*100),'currency'=>(string)env('PAYSTACK_CURRENCY','NGN'),'reference'=>$reference,
          'callback_url'=>url('/payment/callback'),'metadata'=>json_encode(['plan'=>$plan]),
        ]);
        return $data['data']??[];
    }
    public function verify(string $reference): array {
        if(!$this->configured()) throw new RuntimeException('Paystack is not configured.');
        $data=HttpClient::json('https://api.paystack.co/transaction/verify/'.rawurlencode($reference),'GET',['Authorization: Bearer '.$this->key]);
        return $data['data']??[];
    }
}

function smart_caption_chunks(string $text,float $start,float $end,int $maxWords=7): array {
    $words=preg_split('/\s+/',trim($text))?:[]; if(!$words) return [];
    $groups=array_chunk($words,$maxWords); $duration=max(.5,$end-$start); $weight=max(1,count($words)); $cursor=$start; $out=[];
    foreach($groups as $i=>$g){ $portion=count($g)/$weight*$duration; $finish=($i===array_key_last($groups))?$end:$cursor+$portion; $out[]=['text'=>implode(' ',$g),'start'=>$cursor,'end'=>max($cursor+.25,$finish)]; $cursor=$finish; }
    return $out;
}
