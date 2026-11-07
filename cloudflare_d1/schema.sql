-- Bảng quản lý bản quyền phần mềm Tools Marketing / Auto Post
CREATE TABLE IF NOT EXISTS licenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    license_key TEXT UNIQUE NOT NULL,
    machine_id TEXT DEFAULT '',
    customer_name TEXT DEFAULT '',
    expiry_date TEXT NOT NULL,           -- 'YYYY-MM-DD' hoặc 'LIFETIME'
    status TEXT DEFAULT 'ACTIVE',        -- 'ACTIVE', 'BLOCKED', 'EXPIRED'
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_verified_at DATETIME,
    note TEXT DEFAULT ''
);

-- Index tăng tốc tìm kiếm tức thì O(log N) ~1ms
CREATE INDEX IF NOT EXISTS idx_licenses_key ON licenses(license_key);
CREATE INDEX IF NOT EXISTS idx_licenses_machine ON licenses(machine_id);

-- Thêm sẵn 1 Key mẫu dùng thử vĩnh viễn và 1 key 30 ngày để test ngay sau khi tạo DB
INSERT OR IGNORE INTO licenses (license_key, machine_id, customer_name, expiry_date, status, note)
VALUES 
    ('ADMIN-VIP-LIFETIME-2026', '', 'Admin Bản Quyền Vĩnh Viễn', 'LIFETIME', 'ACTIVE', 'Key Admin dùng thử vĩnh viễn'),
    ('TEST-KEY-30DAYS-SAMPLE', '', 'Khách Hàng Mẫu 30 Ngày', date('now', '+30 days'), 'ACTIVE', 'Key dùng thử 30 ngày');
