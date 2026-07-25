<?php
declare(strict_types=1);
require_once __DIR__.'/../app/services.php';

try {
    $gemini=new GeminiService();
    if(!$gemini->configured()) throw new RuntimeException('GEMINI_API_KEY is missing. Run configure-gemini.bat first.');
    $result=$gemini->generateContent('Clyp helps creators turn a raw video into polished social content.','professional');
    if(trim((string)($result['title']??''))==='') throw new RuntimeException('Gemini responded, but the structured result was incomplete.');
    echo '[OK] Gemini connection and structured content generation are working.' . PHP_EOL;
    echo 'Model: '.(string)env('GEMINI_MODEL','gemini-3.5-flash').PHP_EOL;
    exit(0);
} catch(Throwable $e) {
    fwrite(STDERR,'[FAIL] '.$e->getMessage().PHP_EOL);
    exit(1);
}
