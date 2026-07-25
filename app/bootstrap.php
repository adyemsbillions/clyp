<?php
declare(strict_types=1);

const BASE_PATH = __DIR__ . '/..';
$schemaFile = __DIR__ . '/schema.php';
if (is_file($schemaFile)) {
    require_once $schemaFile;
}

function load_env(string $path): void {
    if (!is_file($path)) return;
    foreach (file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) ?: [] as $line) {
        $line = trim($line);
        if ($line === '' || str_starts_with($line, '#') || !str_contains($line, '=')) continue;
        [$key, $value] = array_map('trim', explode('=', $line, 2));
        $value = trim($value, "\"'");
        if (getenv($key) === false) putenv($key . '=' . $value);
        $_ENV[$key] = $value;
    }
}
load_env(BASE_PATH . '/.env');

function env(string $key, mixed $default = null): mixed {
    $value = getenv($key);
    if ($value === false || $value === '') return $default;
    return match (strtolower((string)$value)) {
        'true' => true, 'false' => false, 'null' => null,
        default => $value,
    };
}

date_default_timezone_set((string)env('APP_TIMEZONE', 'Africa/Lagos'));
if (session_status() !== PHP_SESSION_ACTIVE) {
    session_name('clyp_session');
    session_set_cookie_params([
        'httponly' => true,
        'secure' => (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off'),
        'samesite' => 'Lax',
        'path' => '/',
    ]);
    session_start();
}

final class DB {
    private static ?PDO $pdo = null;
    public static function conn(): PDO {
        if (self::$pdo) return self::$pdo;
        $driver = (string)env('DB_DRIVER', 'sqlite');
        if ($driver === 'mysql') {
            $dsn = sprintf('mysql:host=%s;port=%s;dbname=%s;charset=utf8mb4', env('DB_HOST','127.0.0.1'), env('DB_PORT','3306'), env('DB_DATABASE','clyp'));
            self::$pdo = new PDO($dsn, (string)env('DB_USERNAME','root'), (string)env('DB_PASSWORD',''));
        } else {
            $path = (string)env('DB_SQLITE_PATH', 'storage/clyp.sqlite');
            if (!str_starts_with($path, '/') && !preg_match('/^[A-Za-z]:[\\\\\/]/', $path)) $path = BASE_PATH . '/' . $path;
            if (!is_dir(dirname($path))) mkdir(dirname($path), 0775, true);
            self::$pdo = new PDO('sqlite:' . $path);
            self::$pdo->exec('PRAGMA foreign_keys = ON');
        }
        self::$pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        self::$pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
        self::$pdo->setAttribute(PDO::ATTR_EMULATE_PREPARES, false);

        // Keep first-run local installs from opening with an empty database.
        // Older upgrade bundles may temporarily be missing schema.php, so avoid
        // a fatal error and let the standalone repair script handle migration.
        if (function_exists('clyp_install_schema')) {
            clyp_install_schema(self::$pdo, $driver);
        }

        return self::$pdo;
    }
}

function db(): PDO { return DB::conn(); }
function e(?string $value): string { return htmlspecialchars((string)$value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8'); }
function url(string $path = ''): string { return rtrim((string)env('APP_URL', 'http://localhost:8000'), '/') . '/' . ltrim($path, '/'); }
function redirect(string $path): never { header('Location: ' . (str_starts_with($path, 'http') ? $path : url($path))); exit; }
function csrf_token(): string { if (empty($_SESSION['_csrf'])) $_SESSION['_csrf'] = bin2hex(random_bytes(32)); return $_SESSION['_csrf']; }
function csrf_field(): string { return '<input type="hidden" name="_csrf" value="' . e(csrf_token()) . '">'; }
function verify_csrf(): void {
    $token = $_POST['_csrf'] ?? ($_SERVER['HTTP_X_CSRF_TOKEN'] ?? '');
    if (!is_string($token) || !hash_equals(csrf_token(), $token)) json_response(['ok'=>false,'message'=>'Your session token expired. Refresh the page and try again.'], 419);
}
function json_input(): array { $d=json_decode(file_get_contents('php://input') ?: '{}', true); return is_array($d)?$d:[]; }
function json_response(array $data, int $status=200): never { http_response_code($status); header('Content-Type: application/json; charset=utf-8'); echo json_encode($data, JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE); exit; }
function flash(string $type, string $message): void { $_SESSION['_flash'][]=['type'=>$type,'message'=>$message]; }
function flashes(): array { $f=$_SESSION['_flash']??[]; unset($_SESSION['_flash']); return $f; }
function auth_user(): ?array {
    $id = $_SESSION['user_id'] ?? null;
    if (!$id) return null;
    $s=db()->prepare('SELECT * FROM users WHERE id=?'); $s->execute([(int)$id]);
    return $s->fetch() ?: null;
}
function require_auth(): array {
    $u=auth_user();
    if(!$u){
        $path=(string)(parse_url($_SERVER['REQUEST_URI']??'',PHP_URL_PATH)??'');
        if($path==='/api'||str_starts_with($path,'/api/')) json_response(['ok'=>false,'message'=>'Please sign in.'],401);
        redirect('/login');
    }
    return $u;
}
function project_for_user(int $id, int $userId): array {
    $s=db()->prepare('SELECT p.*, s.title AS sound_title, s.file_path AS sound_path FROM projects p LEFT JOIN sounds s ON s.id=p.sound_id WHERE p.id=? AND p.user_id=?');
    $s->execute([$id,$userId]); $p=$s->fetch(); if(!$p) json_response(['ok'=>false,'message'=>'Project not found.'],404); return $p;
}
function storage_path(string $folder, string $name=''): string {
    $dir=BASE_PATH.'/storage/'.trim($folder,'/'); if(!is_dir($dir)) mkdir($dir,0775,true); return $dir.($name!==''?'/'.$name:'');
}
function relative_storage_path(string $absolute): string { return str_replace('\\','/', ltrim(str_replace(str_replace('\\','/',BASE_PATH).'/','',str_replace('\\','/',$absolute)),'/')); }
function icon(string $name, string $class='w-5 h-5'): string {
    $paths=[
      'sparkles'=>'<path d="m12 3-1.8 4.2L6 9l4.2 1.8L12 15l1.8-4.2L18 9l-4.2-1.8L12 3Z"/><path d="m5 16-.8 1.8L2.5 18.5l1.7.7L5 21l.8-1.8 1.7-.7-1.7-.7L5 16Z"/><path d="m19 14-1 2.3-2.3 1 2.3 1L19 21l1-2.7 2.5-1-2.5-1L19 14Z"/>',
      'upload'=>'<path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M20 16.5v2.25A2.25 2.25 0 0 1 17.75 21h-11.5A2.25 2.25 0 0 1 4 18.75V16.5"/>',
      'video'=>'<path d="m16 13 5 3V8l-5 3"/><rect width="13" height="14" x="3" y="5" rx="2"/>',
      'music'=>'<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
      'caption'=>'<rect width="20" height="14" x="2" y="5" rx="2"/><path d="M7 15h4M14 15h3M7 11h2M12 11h5"/>',
      'download'=>'<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
      'grid'=>'<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
      'plus'=>'<path d="M12 5v14M5 12h14"/>',
      'play'=>'<path d="m5 3 14 9-14 9V3Z"/>',
      'wand'=>'<path d="m15 4 5 5L8 21l-5-5L15 4Z"/><path d="m14 5 5 5M6 4v3M4.5 5.5h3M19 15v3M17.5 16.5h3"/>',
      'settings'=>'<path d="M12 15.5A3.5 3.5 0 1 0 12 8a3.5 3.5 0 0 0 0 7.5Z"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 8.5 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 8.5a1.7 1.7 0 0 0-.34-1.88L4.2 6.56a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3a2 2 0 1 1 4 0v.09A1.7 1.7 0 0 0 15.5 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9c.15.36.37.7.66.98.3.27.68.42 1.08.42H21a2 2 0 1 1 0 4h-.09c-.4 0-.78.14-1.08.42-.29.28-.51.62-.66.98Z"/>',
      'logout'=>'<path d="M10 17l5-5-5-5M15 12H3"/><path d="M14 3h5a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-5"/>',
      'check'=>'<path d="m20 6-11 11-5-5"/>',
      'copy'=>'<rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
      'trash'=>'<path d="M3 6h18M8 6V4h8v2M19 6l-1 15H6L5 6M10 11v6M14 11v6"/>',
      'arrow'=>'<path d="M5 12h14M13 6l6 6-6 6"/>',
      'clock'=>'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
      'user'=>'<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
      'menu'=>'<path d="M4 6h16M4 12h16M4 18h16"/>',
      'x'=>'<path d="M18 6 6 18M6 6l12 12"/>',
    ];
    return '<svg class="'.e($class).'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'.($paths[$name]??$paths['sparkles']).'</svg>';
}
function plans(): array { return [
 'free'=>['name'=>'Free','amount'=>0,'exports'=>3,'features'=>['3 videos monthly','Watermarked exports','Standard captions']],
 'creator'=>['name'=>'Creator','amount'=>3000,'exports'=>30,'features'=>['30 exports monthly','Premium captions','Full sound library']],
 'pro'=>['name'=>'Pro','amount'=>7500,'exports'=>-1,'features'=>['Unlimited exports','HD video','Priority rendering']],
 'agency'=>['name'=>'Agency','amount'=>20000,'exports'=>-1,'features'=>['Team-ready account','Unlimited exports','Commercial usage']],
]; }
function monthly_usage(int $userId): int { $s=db()->prepare("SELECT COUNT(*) FROM exports e JOIN projects p ON p.id=e.project_id WHERE p.user_id=? AND e.created_at>=?"); $s->execute([$userId,date('Y-m-01 00:00:00')]); return (int)$s->fetchColumn(); }
function plan_can_export(array $user): bool { $p=plans()[$user['plan']]??plans()['free']; return $p['exports']<0 || monthly_usage((int)$user['id'])<$p['exports']; }
