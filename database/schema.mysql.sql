CREATE DATABASE IF NOT EXISTS clyp CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE clyp;

CREATE TABLE IF NOT EXISTS users (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  email VARCHAR(190) NOT NULL UNIQUE,
  password VARCHAR(255) NOT NULL,
  plan VARCHAR(30) NOT NULL DEFAULT 'free',
  created_at DATETIME NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS sounds (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  title VARCHAR(120) NOT NULL,
  category VARCHAR(60) NOT NULL,
  file_path VARCHAR(500) NOT NULL,
  duration DECIMAL(12,3) NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL,
  INDEX idx_sounds_category (category)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS projects (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  title VARCHAR(120) NOT NULL,
  video_file VARCHAR(500) NOT NULL,
  storage_key VARCHAR(700) NULL,
  original_name VARCHAR(255) NOT NULL,
  caption_style VARCHAR(40) NOT NULL DEFAULT 'viral',
  status VARCHAR(40) NOT NULL DEFAULT 'uploaded',
  duration DECIMAL(12,3) NOT NULL DEFAULT 0,
  sound_id BIGINT UNSIGNED NULL,
  sound_volume DECIMAL(5,3) NOT NULL DEFAULT 0.25,
  sound_trim_start DECIMAL(12,3) NOT NULL DEFAULT 0,
  auto_edit_enabled TINYINT(1) NOT NULL DEFAULT 0,
  edit_style VARCHAR(40) NOT NULL DEFAULT 'dynamic',
  color_grade VARCHAR(40) NOT NULL DEFAULT 'auto',
  remove_silence TINYINT(1) NOT NULL DEFAULT 1,
  remove_fillers TINYINT(1) NOT NULL DEFAULT 1,
  auto_transitions TINYINT(1) NOT NULL DEFAULT 1,
  auto_punch TINYINT(1) NOT NULL DEFAULT 1,
  auto_music TINYINT(1) NOT NULL DEFAULT 1,
  edit_plan_json LONGTEXT NULL,
  edited_duration DECIMAL(12,3) NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  CONSTRAINT fk_projects_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_projects_sound FOREIGN KEY (sound_id) REFERENCES sounds(id) ON DELETE SET NULL,
  INDEX idx_projects_user_updated (user_id, updated_at),
  INDEX idx_projects_status (status)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS captions (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  project_id BIGINT UNSIGNED NOT NULL,
  caption_text TEXT NOT NULL,
  start_time DECIMAL(12,3) NOT NULL,
  end_time DECIMAL(12,3) NOT NULL,
  position_index INT NOT NULL DEFAULT 0,
  CONSTRAINT fk_captions_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  INDEX idx_captions_project_position (project_id, position_index)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS exports (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  project_id BIGINT UNSIGNED NOT NULL,
  export_url VARCHAR(500) NOT NULL,
  storage_key VARCHAR(700) NULL,
  created_at DATETIME NOT NULL,
  CONSTRAINT fk_exports_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  INDEX idx_exports_project_created (project_id, created_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS subscriptions (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  plan VARCHAR(30) NOT NULL,
  amount INT NOT NULL,
  status VARCHAR(40) NOT NULL,
  reference VARCHAR(120) NULL UNIQUE,
  created_at DATETIME NOT NULL,
  CONSTRAINT fk_subscriptions_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_subscriptions_user_created (user_id, created_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS generated_content (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  project_id BIGINT UNSIGNED NOT NULL,
  content_json LONGTEXT NOT NULL,
  created_at DATETIME NOT NULL,
  CONSTRAINT fk_generated_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  INDEX idx_generated_project_created (project_id, created_at)
) ENGINE=InnoDB;
