-- kb_platform 初始化 Schema（13 表 = 规范10 + 工程表3）
-- 约定：逻辑外键不建物理约束（便于 reindex/重建）；全部 utf8mb4；InnoDB

CREATE DATABASE IF NOT EXISTS kb_platform DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
USE kb_platform;

-- ===== 组织与权限（规范表）=====
CREATE TABLE IF NOT EXISTS departments (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    parent_id   BIGINT NULL COMMENT '父部门id，根为NULL',
    name        VARCHAR(64) NOT NULL,
    leader_id   BIGINT NULL,
    sort_order  INT NOT NULL DEFAULT 0,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_departments_parent (parent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS users (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    username      VARCHAR(64) NOT NULL,
    password_hash VARCHAR(128) NOT NULL,
    display_name  VARCHAR(64) NOT NULL DEFAULT '',
    department_id BIGINT NULL COMMENT '逻辑FK departments.id',
    status        TINYINT NOT NULL DEFAULT 1 COMMENT '1启用 0停用',
    is_super      TINYINT NOT NULL DEFAULT 0 COMMENT '超管旁路标志',
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_users_username (username),
    KEY idx_users_dept (department_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS roles (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    role_name  VARCHAR(64) NOT NULL,
    role_code  VARCHAR(64) NOT NULL,
    description VARCHAR(255) NOT NULL DEFAULT '',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_roles_code (role_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS user_roles (
    id      BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL COMMENT '逻辑FK users.id',
    role_id BIGINT NOT NULL COMMENT '逻辑FK roles.id',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_user_role (user_id, role_id),
    KEY idx_ur_role (role_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS role_permissions (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    role_id         BIGINT NOT NULL COMMENT '逻辑FK roles.id',
    permission_code VARCHAR(64) NOT NULL COMMENT '如 org:user:edit / kb:import / ai:chat',
    permission_type VARCHAR(16) NOT NULL DEFAULT 'api' COMMENT 'api|menu|button',
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_role_perm (role_id, permission_code),
    KEY idx_rp_code (permission_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ===== 知识（规范表 + 工程表）=====
CREATE TABLE IF NOT EXISTS knowledge_units (
    id               BIGINT AUTO_INCREMENT PRIMARY KEY,
    unit_code        VARCHAR(64) NOT NULL,
    title            VARCHAR(255) NOT NULL,
    content          MEDIUMTEXT NOT NULL COMMENT '全文正本',
    summary          VARCHAR(512) NOT NULL DEFAULT '',
    category         VARCHAR(64) NOT NULL DEFAULT '' COMMENT '如 IT制度/HR制度/财务制度',
    source_file_name VARCHAR(255) NOT NULL DEFAULT '',
    file_type        VARCHAR(16) NOT NULL DEFAULT '',
    status           TINYINT NOT NULL DEFAULT 1 COMMENT '1启用(可检索) 0下架',
    creator_id       BIGINT NULL COMMENT '逻辑FK users.id',
    created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_units_code (unit_code),
    KEY idx_units_category (category),
    KEY idx_units_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    unit_id      BIGINT NOT NULL COMMENT '逻辑FK knowledge_units.id',
    seq_no       INT NOT NULL DEFAULT 0,
    content      TEXT NOT NULL,
    content_hash CHAR(64) NOT NULL COMMENT 'sha256，reindex 增量比对',
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_chunk (unit_id, seq_no),
    FULLTEXT KEY ft_content (content) WITH PARSER ngram
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS unit_permissions (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    unit_id     BIGINT NOT NULL COMMENT '逻辑FK knowledge_units.id',
    target_type VARCHAR(16) NOT NULL COMMENT 'global|department|role|user',
    target_id   BIGINT NULL COMMENT 'global 时为 NULL',
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_unit_perm (unit_id, target_type, target_id),
    KEY idx_up_target (target_type, target_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ===== 问答会话与日志（工程表 + 规范表）=====
CREATE TABLE IF NOT EXISTS qa_sessions (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id    BIGINT NOT NULL COMMENT '逻辑FK users.id',
    title      VARCHAR(128) NOT NULL DEFAULT '新会话',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_sessions_user (user_id, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS qa_access_logs (
    id                    BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id            BIGINT NULL COMMENT '逻辑FK qa_sessions.id',
    user_id               BIGINT NOT NULL,
    question              TEXT NOT NULL,
    answer                MEDIUMTEXT NULL,
    recalled_unit_ids     JSON NULL COMMENT '[..] 召回单元',
    authorized_unit_ids   JSON NULL COMMENT '[..] 授权命中',
    unauthorized_unit_ids JSON NULL COMMENT '[..] 权限缺失',
    faq_hit               TINYINT NOT NULL DEFAULT 0 COMMENT '是否FAQ缓存直答',
    degraded              TINYINT NOT NULL DEFAULT 0 COMMENT '是否降级检索',
    prompt_tokens         INT NOT NULL DEFAULT 0,
    completion_tokens     INT NOT NULL DEFAULT 0,
    total_tokens          INT NOT NULL DEFAULT 0,
    response_time_ms      INT NOT NULL DEFAULT 0,
    created_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_qal_user_time (user_id, created_at),
    KEY idx_qal_time (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ===== 沉淀闭环（规范表）=====
CREATE TABLE IF NOT EXISTS faqs (
    id             BIGINT AUTO_INCREMENT PRIMARY KEY,
    question       VARCHAR(512) NOT NULL,
    answer         MEDIUMTEXT NOT NULL,
    category       VARCHAR(64) NOT NULL DEFAULT '',
    related_unit_id BIGINT NULL,
    source_type    VARCHAR(16) NOT NULL DEFAULT 'manual' COMMENT 'manual|auto_mined',
    status         VARCHAR(16) NOT NULL DEFAULT 'pending_review' COMMENT 'pending_review|published|rejected',
    hit_count      INT NOT NULL DEFAULT 0,
    reviewer_id    BIGINT NULL,
    reviewed_at    DATETIME NULL,
    created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_faqs_status (status),
    KEY idx_faqs_hit (hit_count)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS knowledge_gaps (
    id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
    question_pattern   VARCHAR(512) NOT NULL COMMENT '聚类代表问题',
    sample_questions   JSON NULL,
    ask_count          INT NOT NULL DEFAULT 1,
    last_asked_at      DATETIME NULL,
    status             VARCHAR(16) NOT NULL DEFAULT 'unresolved' COMMENT 'unresolved|resolved|ignored',
    resolved_unit_id   BIGINT NULL,
    created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_gaps_status (status, ask_count)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ===== 导入任务（工程表）=====
CREATE TABLE IF NOT EXISTS import_tasks (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    batch_no      CHAR(32) NOT NULL COMMENT '同一次批量上传',
    file_name     VARCHAR(255) NOT NULL,
    file_type     VARCHAR(16) NOT NULL DEFAULT '',
    size_bytes    BIGINT NOT NULL DEFAULT 0,
    task_status   VARCHAR(16) NOT NULL DEFAULT 'pending' COMMENT 'pending|parsing|embedding|done|failed',
    error_message VARCHAR(512) NULL,
    unit_id       BIGINT NULL COMMENT '成功后关联的知识单元',
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at   DATETIME NULL,
    KEY idx_import_batch (batch_no),
    KEY idx_import_status (task_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
