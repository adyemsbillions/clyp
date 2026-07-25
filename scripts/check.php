<?php
declare(strict_types=1);
require_once __DIR__.'/../app/services.php';

$driver=(string)env('DB_DRIVER','sqlite');
$checks=[
  'PHP 8.3+'=>version_compare(PHP_VERSION,'8.3.0','>='),
  'PDO'=>extension_loaded('pdo'),
  'Database driver'=>in_array($driver,PDO::getAvailableDrivers(),true),
  'cURL'=>extension_loaded('curl'),
  'Fileinfo'=>extension_loaded('fileinfo'),
  'mbstring'=>extension_loaded('mbstring'),
  'JSON'=>extension_loaded('json'),
];
$ok=true;
foreach($checks as $name=>$pass){echo ($pass?'[OK] ':'[FAIL] ').$name."\n";$ok=$ok&&$pass;}

foreach(['FFMPEG_PATH'=>'ffmpeg','FFPROBE_PATH'=>'ffprobe'] as $key=>$default){
    $bin=(string)env($key,$default);
    $cmd=escapeshellarg($bin).' -version 2>&1';
    exec($cmd,$out,$code);
    $pass=$code===0;
    echo ($pass?'[OK] ':'[FAIL] ').$key.' ('.$bin.")\n";
    $ok=$ok&&$pass;
}

$ffmpeg=(string)env('FFMPEG_PATH','ffmpeg');
$cmd=escapeshellarg($ffmpeg).' -hide_banner -filters 2>&1';
exec($cmd,$filterOut,$filterCode);
$filterText=implode("\n",$filterOut);
foreach(['ass','xfade','sidechaincompress','silencedetect','signalstats'] as $filter){
    $pass=$filterCode===0 && preg_match('/\b'.preg_quote($filter,'/').'\b/',$filterText)===1;
    echo ($pass?'[OK] ':'[FAIL] ').'FFmpeg filter: '.$filter."\n";
    $ok=$ok&&$pass;
}

foreach(['uploads','exports','tmp','sounds'] as $dir){
    $path=storage_path($dir);
    $pass=is_writable($path);
    echo ($pass?'[OK] ':'[FAIL] ').'Writable storage/'.$dir."\n";
    $ok=$ok&&$pass;
}

$gemini=new GeminiService();
echo ($gemini->configured()?'[OK] ':'[INFO] ').($gemini->configured()?'Gemini API key configured':'Gemini API key not configured; manual transcript mode remains available')."\n";
$cloud=new CloudStorageService();
if($cloud->isR2()){
    $pass=$cloud->configured();
    echo ($pass?'[OK] ':'[FAIL] ').'Cloudflare R2 configuration'."\n";
    $ok=$ok&&$pass;
}
exit($ok?0:1);
