-- 1. 图片资产表
CREATE TABLE IF NOT EXISTS image_assets (
    image_hash   VARCHAR(64) PRIMARY KEY,
    file_path    TEXT NOT NULL,
    file_size    INT,
    created_time DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. 视频资产表
CREATE TABLE IF NOT EXISTS video_assets (
    video_hash   VARCHAR(64) PRIMARY KEY,
    file_path    TEXT NOT NULL,
    file_size    INT,
    created_time DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. 消息主表
CREATE TABLE IF NOT EXISTS messages (
    message_id    VARCHAR(191) PRIMARY KEY,
    platform_type VARCHAR(50) NOT NULL,
    self_id       VARCHAR(255) NOT NULL,
    session_id    VARCHAR(255) NOT NULL,
    group_id      VARCHAR(255),
    group_name    VARCHAR(255),
    sender        JSON NOT NULL,
    message_str   TEXT NOT NULL,
    raw_message   LONGTEXT,
    image_ids     JSON,
    video_ids     JSON,
    month         VARCHAR(20), 
    month_saved   BOOLEAN DEFAULT FALSE,
    timestamp     INT NOT NULL,
    created_time  DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;