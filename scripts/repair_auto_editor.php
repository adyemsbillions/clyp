<?php
declare(strict_types=1);

/**
 * Repairs an existing Clyp database for the one-click editor.
 * This script deliberately does not depend on clyp_install_schema(), because
 * older Clyp builds did not load app/schema.php from bootstrap.php.
 */

require_once __DIR__ . '/../app/bootstrap.php';

try {
    $pdo = db();
    $driver = strtolower((string)$pdo->getAttribute(PDO::ATTR_DRIVER_NAME));

    if (!in_array($driver, ['sqlite', 'mysql'], true)) {
        throw new RuntimeException("Unsupported database driver: {$driver}");
    }

    $tableExists = static function (string $table) use ($pdo, $driver): bool {
        if ($driver === 'mysql') {
            $statement = $pdo->prepare(
                'SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=?'
            );
            $statement->execute([$table]);
            return (int)$statement->fetchColumn() > 0;
        }

        $statement = $pdo->prepare("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?");
        $statement->execute([$table]);
        return (int)$statement->fetchColumn() > 0;
    };

    if (!$tableExists('projects')) {
        // Try the normal installer when available, but never require it.
        $schemaFile = __DIR__ . '/../app/schema.php';
        if (is_file($schemaFile)) {
            require_once $schemaFile;
        }
        if (function_exists('clyp_install_schema')) {
            clyp_install_schema($pdo, $driver);
        }
    }

    if (!$tableExists('projects')) {
        throw new RuntimeException(
            'The projects table does not exist. Run "php .\\scripts\\install.php" first, then rerun this repair.'
        );
    }

    $columnExists = static function (string $table, string $column) use ($pdo, $driver): bool {
        if ($driver === 'mysql') {
            $statement = $pdo->prepare(
                'SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=? AND COLUMN_NAME=?'
            );
            $statement->execute([$table, $column]);
            return (int)$statement->fetchColumn() > 0;
        }

        // Table and column names are fixed application identifiers, not user input.
        $rows = $pdo->query('PRAGMA table_info(' . $table . ')')->fetchAll(PDO::FETCH_ASSOC);
        foreach ($rows as $row) {
            if ((string)($row['name'] ?? '') === $column) {
                return true;
            }
        }
        return false;
    };

    $definitions = [
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

    $pdo->beginTransaction();
    try {
        foreach ($definitions as $column => $definition) {
            if (!$columnExists('projects', $column)) {
                $pdo->exec('ALTER TABLE projects ADD COLUMN ' . $column . ' ' . $definition);
                echo "Added projects.{$column}" . PHP_EOL;
            }
        }

        // Normalize records created by older Clyp versions.
        $pdo->exec("UPDATE projects SET edit_style='dynamic' WHERE edit_style IS NULL OR edit_style=''");
        $pdo->exec("UPDATE projects SET color_grade='auto' WHERE color_grade IS NULL OR color_grade=''");
        $pdo->exec('UPDATE projects SET auto_edit_enabled=0 WHERE auto_edit_enabled IS NULL');
        $pdo->exec('UPDATE projects SET remove_silence=1 WHERE remove_silence IS NULL');
        $pdo->exec('UPDATE projects SET remove_fillers=1 WHERE remove_fillers IS NULL');
        $pdo->exec('UPDATE projects SET auto_transitions=1 WHERE auto_transitions IS NULL');
        $pdo->exec('UPDATE projects SET auto_punch=1 WHERE auto_punch IS NULL');
        $pdo->exec('UPDATE projects SET auto_music=1 WHERE auto_music IS NULL');
        $pdo->exec('UPDATE projects SET edited_duration=0 WHERE edited_duration IS NULL');

        $pdo->commit();
    } catch (Throwable $error) {
        if ($pdo->inTransaction()) {
            $pdo->rollBack();
        }
        throw $error;
    }

    echo "[OK] Clyp auto-editor database repair completed using {$driver}." . PHP_EOL;
    exit(0);
} catch (Throwable $error) {
    fwrite(STDERR, '[FAIL] ' . $error->getMessage() . PHP_EOL);
    exit(1);
}
