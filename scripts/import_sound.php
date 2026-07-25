<?php
declare(strict_types=1);
require_once __DIR__.'/../app/services.php';

if(PHP_SAPI!=='cli') exit("Run this script from the command line.\n");
[$script,$title,$category,$source]=array_pad($argv,4,'');
$title=trim($title);$category=trim($category);$source=trim($source);
if($title===''||$category===''||$source===''){
    fwrite(STDERR,"Usage: php scripts\\import_sound.php \"Sound title\" \"Category\" \"C:\\path\\track.mp3\"\n");
    exit(1);
}
if(!is_file($source)){fwrite(STDERR,"Sound file not found: {$source}\n");exit(1);}
$ext=strtolower(pathinfo($source,PATHINFO_EXTENSION));
if(!in_array($ext,['mp3','wav','m4a','aac','ogg'],true)){fwrite(STDERR,"Supported formats: MP3, WAV, M4A, AAC and OGG.\n");exit(1);}
$base=preg_replace('/[^a-z0-9]+/i','-',strtolower($title))?:'sound';
$base=trim($base,'-');
$name=$base.'-'.substr(bin2hex(random_bytes(4)),0,8).'.'.$ext;
$destination=storage_path('sounds',$name);
if(!copy($source,$destination)){fwrite(STDERR,"Could not copy the sound file.\n");exit(1);}
try{
    $duration=(new MediaService())->duration($destination);
    $s=db()->prepare('INSERT INTO sounds (title,category,file_path,duration,created_at) VALUES (?,?,?,?,?)');
    $s->execute([mb_substr($title,0,120),mb_substr($category,0,60),relative_storage_path($destination),$duration,date('Y-m-d H:i:s')]);
    echo "Imported {$title} ({$duration}s) as sound #".db()->lastInsertId().".\n";
}catch(Throwable $e){@unlink($destination);fwrite(STDERR,$e->getMessage()."\n");exit(1);}
