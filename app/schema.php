<?php
declare(strict_types=1);

/**
 * Creates or upgrades the Clyp database schema.
 * Safe to call on every request because all operations are idempotent.
 */
function clyp_install_schema(PDO $pdo, string $driver): void
{
    $id = $driver === 'mysql'
        ? 'BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY'
        : 'INTEGER PRIMARY KEY AUTOINCREMENT';
    $fk = $driver === 'mysql' ? 'BIGINT UNSIGNED' : 'INTEGER';
    $timestamp = $driver === 'mysql' ? 'DATETIME' : 'TEXT';

    $tables = [
        "CREATE TABLE IF NOT EXISTS users (id $id,name VARCHAR(100) NOT NULL,email VARCHAR(190) NOT NULL UNIQUE,password VARCHAR(255) NOT NULL,plan VARCHAR(30) NOT NULL DEFAULT 'free',created_at $timestamp NOT NULL)",
        "CREATE TABLE IF NOT EXISTS projects (id $id,user_id $fk NOT NULL,title VARCHAR(120) NOT NULL,video_file VARCHAR(500) NOT NULL,storage_key VARCHAR(700) NULL,original_name VARCHAR(255) NOT NULL,caption_style VARCHAR(40) NOT NULL DEFAULT 'viral',status VARCHAR(40) NOT NULL DEFAULT 'uploaded',duration DECIMAL(12,3) NOT NULL DEFAULT 0,sound_id $fk NULL,sound_volume DECIMAL(5,3) NOT NULL DEFAULT 0.25,sound_trim_start DECIMAL(12,3) NOT NULL DEFAULT 0,auto_edit_enabled INTEGER NOT NULL DEFAULT 0,edit_style VARCHAR(40) NOT NULL DEFAULT 'dynamic',color_grade VARCHAR(40) NOT NULL DEFAULT 'auto',remove_silence INTEGER NOT NULL DEFAULT 1,remove_fillers INTEGER NOT NULL DEFAULT 1,auto_transitions INTEGER NOT NULL DEFAULT 1,auto_punch INTEGER NOT NULL DEFAULT 1,auto_music INTEGER NOT NULL DEFAULT 1,edit_plan_json TEXT NULL,edited_duration DECIMAL(12,3) NOT NULL DEFAULT 0,created_at $timestamp NOT NULL,updated_at $timestamp NOT NULL,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)",
        "CREATE TABLE IF NOT EXISTS captions (id $id,project_id $fk NOT NULL,caption_text TEXT NOT NULL,start_time DECIMAL(12,3) NOT NULL,end_time DECIMAL(12,3) NOT NULL,position_index INTEGER NOT NULL DEFAULT 0,FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE)",
        "CREATE TABLE IF NOT EXISTS sounds (id $id,title VARCHAR(120) NOT NULL,category VARCHAR(60) NOT NULL,file_path VARCHAR(500) NOT NULL,duration DECIMAL(12,3) NOT NULL DEFAULT 0,created_at $timestamp NOT NULL)",
        "CREATE TABLE IF NOT EXISTS exports (id $id,project_id $fk NOT NULL,export_url VARCHAR(500) NOT NULL,storage_key VARCHAR(700) NULL,created_at $timestamp NOT NULL,FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE)",
        "CREATE TABLE IF NOT EXISTS subscriptions (id $id,user_id $fk NOT NULL,plan VARCHAR(30) NOT NULL,amount INTEGER NOT NULL,status VARCHAR(40) NOT NULL,reference VARCHAR(120) NULL UNIQUE,created_at $timestamp NOT NULL,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)",
        "CREATE TABLE IF NOT EXISTS generated_content (id $id,project_id $fk NOT NULL,content_json TEXT NOT NULL,created_at $timestamp NOT NULL,FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE)",
    ];

    foreach ($tables as $sql) {
        $pdo->exec($sql);
    }

    $columnExists = static function (string $table, string $column) use ($pdo, $driver): bool {
        if ($driver === 'mysql') {
            $statement = $pdo->prepare(
                'SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=? AND COLUMN_NAME=?'
            );
            $statement->execute([$table, $column]);
            return (int)$statement->fetchColumn() > 0;
        }

        $rows = $pdo->query('PRAGMA table_info(' . $table . ')')->fetchAll();
        foreach ($rows as $row) {
            if (($row['name'] ?? '') === $column) return true;
        }
        return false;
    };

    $projectColumns = [
        'storage_key' => 'VARCHAR(700) NULL',
        'auto_edit_enabled' => 'INTEGER NOT NULL DEFAULT 0',
        'edit_style' => "VARCHAR(40) NOT NULL DEFAULT 'dynamic'",
        'color_grade' => "VARCHAR(40) NOT NULL DEFAULT 'auto'",
        'remove_silence' => 'INTEGER NOT NULL DEFAULT 1',
        'remove_fillers' => 'INTEGER NOT NULL DEFAULT 1',
        'auto_transitions' => 'INTEGER NOT NULL DEFAULT 1',
        'auto_punch' => 'INTEGER NOT NULL DEFAULT 1',
        'auto_music' => 'INTEGER NOT NULL DEFAULT 1',
        'edit_plan_json' => 'TEXT NULL',
        'edited_duration' => 'DECIMAL(12,3) NOT NULL DEFAULT 0',
    ];
    foreach ($projectColumns as $column => $definition) {
        if (!$columnExists('projects', $column)) {
            $pdo->exec('ALTER TABLE projects ADD COLUMN ' . $column . ' ' . $definition);
        }
    }
    if (!$columnExists('exports', 'storage_key')) {
        $pdo->exec('ALTER TABLE exports ADD COLUMN storage_key VARCHAR(700) NULL');
    }

    $sounds = [
        ['Cinematic Rise', 'Cinematic', 'cinematic-rise.wav'],
        ['Focused Momentum', 'Business', 'focused-momentum.wav'],
        ['Bright Steps', 'Motivational', 'bright-steps.wav'],
        ['Daylight Vlog', 'Vlog', 'daylight-vlog.wav'],
        ['Afro Pulse', 'Afro-inspired', 'afro-pulse.wav'],
        ['Digital Current', 'Tech', 'digital-current.wav'],
    ];

    $check = $pdo->prepare('SELECT id FROM sounds WHERE title=?');
    $insert = $pdo->prepare('INSERT INTO sounds (title,category,file_path,duration,created_at) VALUES (?,?,?,?,?)');
    foreach ($sounds as [$title, $category, $file]) {
        $check->execute([$title]);
        if (!$check->fetchColumn() && is_file(BASE_PATH . '/storage/sounds/' . $file)) {
            $insert->execute([$title, $category, 'storage/sounds/' . $file, 8, date('Y-m-d H:i:s')]);
        }
    }
}
