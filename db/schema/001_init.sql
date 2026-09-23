-- SynTime 数据库基线 DDL（对应 docs/backend/database.md V1.21 口径，15 张表）
-- 目标：PostgreSQL 15+（当前 syntime_dev = PG 17.11）
-- 约定：时间一律 timestamptz；金额/汇率一律 NUMERIC(20,8)；枚举用 VARCHAR+CHECK（字典/映射仍以字典表为唯一来源）；
--       唯一键含可空维度列时用 NULLS NOT DISTINCT，保证同步幂等语义（database.md §0.2/§1 说明）；
--       不启用 RLS、不含 tenant_id（ADR-0001 单组织部署）。

BEGIN;

-- 1. 云账号表
CREATE TABLE cloud_account (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vendor                  VARCHAR(32)  NOT NULL,
    account_name            VARCHAR(128) NOT NULL,
    account_alias           VARCHAR(128),
    account_type            VARCHAR(16)  NOT NULL CHECK (account_type IN ('main', 'sub')),
    ak_cipher               TEXT         NOT NULL,
    sk_cipher               TEXT         NOT NULL,
    dek_id                  VARCHAR(64),
    key_version             INTEGER      NOT NULL DEFAULT 1,
    status                  VARCHAR(16)  NOT NULL DEFAULT 'enabled' CHECK (status IN ('enabled', 'disabled')),
    last_sync_time          TIMESTAMPTZ,
    last_sync_attempt_time  TIMESTAMPTZ,
    last_sync_error         TEXT,
    create_time             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    update_time             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uk_account UNIQUE (vendor, account_name)
);

-- 2. 云账单明细表（按 bill_date 声明式分区；月度分区由 beat 任务预建，DEFAULT 兜底承接）
CREATE TABLE cloud_bill_detail (
    id                BIGINT GENERATED ALWAYS AS IDENTITY,
    cloud_account_id  BIGINT        NOT NULL REFERENCES cloud_account(id) ON DELETE RESTRICT,
    region            VARCHAR(64),
    instance_id       VARCHAR(128),
    resource_type     VARCHAR(32)   NOT NULL,
    project_tag       VARCHAR(128),
    raw_tags          TEXT,
    tag_status        VARCHAR(16)   NOT NULL CHECK (tag_status IN ('normal', 'unassigned', 'conflict')),
    charge_type       VARCHAR(32)   NOT NULL,
    currency          VARCHAR(8)    NOT NULL,
    amount            NUMERIC(20,8) NOT NULL,
    exchange_rate     NUMERIC(20,8),
    amount_cny        NUMERIC(20,8),
    bill_date         DATE          NOT NULL,
    bill_month        VARCHAR(7)    NOT NULL CHECK (bill_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
    create_time       TIMESTAMPTZ   NOT NULL DEFAULT now(),
    update_time       TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (id, bill_date),
    CONSTRAINT uk_bill UNIQUE NULLS NOT DISTINCT
        (cloud_account_id, resource_type, instance_id, bill_date, charge_type)
) PARTITION BY RANGE (bill_date);

CREATE TABLE cloud_bill_detail_default PARTITION OF cloud_bill_detail DEFAULT;
CREATE INDEX idx_bill_date    ON cloud_bill_detail (bill_date);
CREATE INDEX idx_project      ON cloud_bill_detail (project_tag, bill_date);
CREATE INDEX idx_account_date ON cloud_bill_detail (cloud_account_id, bill_date);

-- 3. 项目预算表
CREATE TABLE project_budget (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_tag    VARCHAR(128) NOT NULL,
    bill_month     VARCHAR(7)   NOT NULL CHECK (bill_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
    budget_amount  NUMERIC(20,8) NOT NULL CHECK (budget_amount >= 0),
    create_time    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    update_time    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uk_project_month UNIQUE (project_tag, bill_month)
);

-- 4. 项目成本预聚合表（天粒度 rollup）
CREATE TABLE project_cost_daily (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stat_date         DATE          NOT NULL,
    project_tag       VARCHAR(128)  NOT NULL,
    tag_status        VARCHAR(16)   NOT NULL CHECK (tag_status IN ('normal', 'unassigned', 'conflict')),
    cloud_account_id  BIGINT        NOT NULL REFERENCES cloud_account(id) ON DELETE RESTRICT,
    region            VARCHAR(64),
    resource_type     VARCHAR(32)   NOT NULL,
    amount            NUMERIC(20,8) NOT NULL,
    bill_count        INTEGER       NOT NULL DEFAULT 0,
    create_time       TIMESTAMPTZ   NOT NULL DEFAULT now(),
    update_time       TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT uk_daily UNIQUE NULLS NOT DISTINCT
        (stat_date, project_tag, tag_status, cloud_account_id, region, resource_type)
);
CREATE INDEX idx_date_project ON project_cost_daily (stat_date, project_tag);

-- 5. 异步任务表
CREATE TABLE async_task (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_type        VARCHAR(64)  NOT NULL CHECK (task_type IN ('export', 'sync', 'aggregate')),
    status           VARCHAR(16)  NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'success', 'failed')),
    params_snapshot  JSONB,
    data_version     VARCHAR(64),
    file_path        TEXT,
    file_size        BIGINT,
    expire_time      TIMESTAMPTZ,
    retry_count      INTEGER      NOT NULL DEFAULT 0,
    error_msg        TEXT,
    creator          VARCHAR(150),
    create_time      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    finish_time      TIMESTAMPTZ
);

-- 6. 审计日志表
CREATE TABLE audit_log (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    operator         VARCHAR(150),
    role             VARCHAR(32),
    action           VARCHAR(32)  NOT NULL CHECK (action IN ('query', 'export', 'sync', 'aggregate', 'budget_import')),
    params_snapshot  JSONB,
    result           VARCHAR(16),
    client_ip        VARCHAR(45),
    cost_ms          INTEGER,
    create_time      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- 7. 账单同步日志表
CREATE TABLE sync_log (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cloud_account_id  BIGINT       NOT NULL REFERENCES cloud_account(id) ON DELETE RESTRICT,
    sync_type         VARCHAR(16)  NOT NULL CHECK (sync_type IN ('auto', 'manual')),
    bill_date_start   DATE         NOT NULL,
    bill_date_end     DATE         NOT NULL,
    status            VARCHAR(16)  NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    insert_count      INTEGER      NOT NULL DEFAULT 0,
    update_count      INTEGER      NOT NULL DEFAULT 0,
    error_msg         TEXT,
    start_time        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    end_time          TIMESTAMPTZ,
    CONSTRAINT uk_sync_window UNIQUE (cloud_account_id, sync_type, bill_date_start, bill_date_end),
    CONSTRAINT chk_sync_range CHECK (bill_date_end >= bill_date_start)
);

-- 8. 资源类型字典表
CREATE TABLE resource_type_dict (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code          VARCHAR(64)  NOT NULL,
    display_name  VARCHAR(128) NOT NULL,
    sort_order    INTEGER      NOT NULL DEFAULT 0,
    enabled       BOOLEAN      NOT NULL DEFAULT TRUE,
    create_time   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    update_time   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uk_code UNIQUE (code)
);

-- 9. 汇率表
CREATE TABLE exchange_rate (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    currency     VARCHAR(8)   NOT NULL,
    rate_date    DATE         NOT NULL,
    rate_to_cny  NUMERIC(20,8) NOT NULL CHECK (rate_to_cny > 0),
    source       VARCHAR(64),
    create_time  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uk_currency_date UNIQUE (currency, rate_date)
);

-- 10. 云资产表（cloud_account_id 可空：域名可无归属云账号）
CREATE TABLE cloud_asset (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cloud_account_id  BIGINT REFERENCES cloud_account(id) ON DELETE RESTRICT,
    region            VARCHAR(64),
    instance_id       VARCHAR(128) NOT NULL,
    instance_name     VARCHAR(256),
    resource_type     VARCHAR(32)  NOT NULL,
    project_tag       VARCHAR(128),
    raw_tags          TEXT,
    status            VARCHAR(16)  NOT NULL DEFAULT 'unknown' CHECK (status IN
                        ('running', 'stopped', 'bound', 'unbound', 'normal', 'abnormal',
                         'expiring', 'expired', 'unknown')),
    vendor_status     VARCHAR(64),
    status_changed_at TIMESTAMPTZ,
    spec              VARCHAR(128),
    private_ip        VARCHAR(256),
    public_ip         VARCHAR(256),
    charge_type       VARCHAR(32),
    expire_time       TIMESTAMPTZ,
    registrar         VARCHAR(64),
    realname_status   VARCHAR(32),
    dns_servers       VARCHAR(256),
    auto_renew        BOOLEAN,
    remark            TEXT,
    first_seen_at     TIMESTAMPTZ,
    last_seen_at      TIMESTAMPTZ,
    released_at       TIMESTAMPTZ,
    create_time       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    update_time       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uk_asset UNIQUE NULLS NOT DISTINCT (cloud_account_id, resource_type, instance_id)
);
CREATE INDEX idx_asset_type_status ON cloud_asset (resource_type, status);
CREATE INDEX idx_asset_project     ON cloud_asset (project_tag);
CREATE INDEX idx_asset_account     ON cloud_asset (cloud_account_id);
CREATE INDEX idx_asset_idle        ON cloud_asset (charge_type, status);

-- 11. 事件表
CREATE TABLE cloud_event (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_no           VARCHAR(64),
    event_type         VARCHAR(64)  NOT NULL,
    event_level        VARCHAR(16)  NOT NULL CHECK (event_level IN ('info', 'warning', 'critical')),
    source             VARCHAR(16)  NOT NULL CHECK (source IN ('vendor', 'rule', 'manual')),
    resource_type      VARCHAR(32),
    resource_id        VARCHAR(128),
    instance_name      VARCHAR(256),
    cloud_account_id   BIGINT REFERENCES cloud_account(id) ON DELETE RESTRICT,
    provider           VARCHAR(32),
    vendor_event_code  VARCHAR(64),
    vendor_event_name  VARCHAR(128),
    region             VARCHAR(64),
    project_tag        VARCHAR(128),
    title              VARCHAR(256) NOT NULL,
    content            TEXT,
    metric_json        JSONB,
    raw_payload        TEXT,
    occurred_at        TIMESTAMPTZ,
    received_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    status             VARCHAR(16)  NOT NULL DEFAULT 'unread' CHECK (status IN ('unread', 'read', 'handled', 'ignored')),
    handled_by         VARCHAR(150),
    handled_at         TIMESTAMPTZ,
    dedup_key          VARCHAR(128) NOT NULL,
    create_time        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uk_event_dedup UNIQUE (dedup_key)
);
CREATE INDEX idx_evt_time         ON cloud_event (occurred_at);
CREATE INDEX idx_evt_status_level ON cloud_event (status, event_level);
CREATE INDEX idx_evt_resource     ON cloud_event (resource_type, resource_id);

-- 12. 事件类型字典表
CREATE TABLE event_type_dict (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code           VARCHAR(64)  NOT NULL,
    display_name   VARCHAR(128) NOT NULL,
    default_level  VARCHAR(16)  NOT NULL CHECK (default_level IN ('info', 'warning', 'critical')),
    data_source    VARCHAR(128),
    enabled        BOOLEAN      NOT NULL DEFAULT TRUE,
    sort_order     INTEGER      NOT NULL DEFAULT 0,
    description    TEXT,
    create_time    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    update_time    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uk_event_code UNIQUE (code)
);

-- 13. 厂商消息流水表
CREATE TABLE vendor_message_log (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider            VARCHAR(32)  NOT NULL,
    cloud_account_id    BIGINT REFERENCES cloud_account(id) ON DELETE RESTRICT,
    message_id          VARCHAR(128) NOT NULL,
    vendor_event_code   VARCHAR(64),
    vendor_event_name   VARCHAR(128),
    raw_payload         TEXT         NOT NULL,
    mapped_event_type   VARCHAR(64),
    mapped_status       VARCHAR(16)  CHECK (mapped_status IN ('mapped', 'unmapped', 'duplicated')),
    cloud_event_id      BIGINT REFERENCES cloud_event(id) ON DELETE SET NULL,
    occurred_at         TIMESTAMPTZ,
    received_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    create_time         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uk_vendor_msg UNIQUE (provider, message_id)
);
CREATE INDEX idx_vmsg_unmapped ON vendor_message_log (mapped_status, received_at);
CREATE INDEX idx_vmsg_time     ON vendor_message_log (received_at);

-- 14. 厂商映射表
CREATE TABLE vendor_mapping (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mapping_kind    VARCHAR(32)  NOT NULL CHECK (mapping_kind IN
                        ('resource_type', 'region', 'charge_type', 'status', 'event_type')),
    provider        VARCHAR(32)  NOT NULL,
    vendor_code     VARCHAR(128) NOT NULL,
    vendor_name     VARCHAR(128),
    standard_code   VARCHAR(64)  NOT NULL,
    standard_name   VARCHAR(128),
    enabled         BOOLEAN      NOT NULL DEFAULT TRUE,
    remark          TEXT,
    create_time     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    update_time     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uk_vendor_map UNIQUE (mapping_kind, provider, vendor_code)
);
CREATE INDEX idx_map_lookup ON vendor_mapping (mapping_kind, provider, vendor_code, enabled);

-- 15. 平台配置表
CREATE TABLE platform_setting (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    setting_key    VARCHAR(64) NOT NULL,
    setting_value  JSONB       NOT NULL,
    remark         TEXT,
    updated_by     VARCHAR(150),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uk_setting UNIQUE (setting_key)
);

COMMIT;
