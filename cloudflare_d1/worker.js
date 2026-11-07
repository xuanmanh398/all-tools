/**
 * Cloudflare Worker: Hệ Thống Bản Quyền Siêu Tốc Cho Tools Marketing (Cloudflare D1 + SQLite)
 * 
 * Tính năng:
 * 1. API Xác Thực Key (/api/verify) siêu tốc ~30ms - 80ms.
 * 2. Tự động gắn Mã Máy (Machine ID) lần đầu kích hoạt (Chống dùng chung 1 key trên nhiều máy).
 * 3. Tự động kiểm tra thời hạn (Hết hạn -> Trả về EXPIRED).
 * 4. Tích hợp sẵn Trang Web Quản Trị (Admin Web Dashboard) tại trang chủ `/` để xem, tạo key, gia hạn, khóa/mở key ngay trên điện thoại hoặc máy tính!
 */

const ADMIN_PASSWORD = "admin123"; // Đổi mật khẩu này hoặc đặt trong Cloudflare Worker Environment Variable ADMIN_PASSWORD

const CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Admin-Key, Authorization",
    "Access-Control-Max-Age": "86400",
};

export default {
    async fetch(request, env, ctx) {
        if (request.method === "OPTIONS") {
            return new Response(null, { headers: CORS_HEADERS });
        }

        const url = new URL(request.url);
        const path = url.pathname;

        try {
            // 1. API XÁC THỰC BẢN QUYỀN TỪ PHẦN MỀM DESKTOP
            if (path === "/api/verify" && request.method === "POST") {
                return await handleVerifyLicense(request, env);
            }

            // 2. API TỰ ĐỘNG ĐĂNG KÝ / LẤY THÔNG TIN MÁY
            if (path === "/api/auto-register" && request.method === "POST") {
                return await handleAutoRegister(request, env);
            }

            // 3. API DÀNH CHO ADMIN QUẢN LÝ
            if (path === "/api/admin/list") {
                return await handleAdminList(request, env);
            }
            if (path === "/api/admin/save" && request.method === "POST") {
                return await handleAdminSave(request, env);
            }
            if (path === "/api/admin/delete" && request.method === "POST") {
                return await handleAdminDelete(request, env);
            }
            if (path === "/api/admin/reset-machine" && request.method === "POST") {
                return await handleAdminResetMachine(request, env);
            }

            // 4. TRANG WEB QUẢN TRỊ ADMIN (GIAO DIỆN TRỰC QUAN ĐẸP MẮT)
            if (path === "/" || path === "/admin") {
                return renderAdminWebPage(env);
            }

            return jsonResponse({ error: "Endpoint not found" }, 404);
        } catch (err) {
            return jsonResponse({ valid: false, error: err.message, stack: String(err.stack) }, 500);
        }
    }
};

/**
 * Xử lý xác thực bản quyền (Endpoint: /api/verify)
 */
async function handleVerifyLicense(request, env) {
    const body = await request.json().catch(() => ({}));
    const key = String(body.license_key || body.key || "").trim().toUpperCase();
    const machineId = String(body.machine_id || "").trim().toUpperCase();

    if (!key) {
        return jsonResponse({ valid: false, message: "Vui lòng nhập Key kích hoạt!" }, 400);
    }
    if (!machineId) {
        return jsonResponse({ valid: false, message: "Không xác định được Mã Máy (Machine ID)!" }, 400);
    }

    if (!env.DB) {
        return jsonResponse({ valid: false, message: "Lỗi cấu hình máy chủ: Chưa liên kết D1 Database (Binding DB)!" }, 500);
    }

    // 1. Tìm Key trong CSDL D1
    const { results } = await env.DB.prepare(
        "SELECT * FROM licenses WHERE UPPER(license_key) = ? LIMIT 1"
    ).bind(key).all();

    if (!results || results.length === 0) {
        return jsonResponse({
            valid: false,
            status: "NOT_FOUND",
            message: "Key kích hoạt không tồn tại trên hệ thống!"
        });
    }

    const row = results[0];
    const boundMachine = (row.machine_id || "").trim().toUpperCase();

    // 2. Kiểm tra trạng thái khóa (BLOCKED / REVOKED)
    const currentStatus = (row.status || "ACTIVE").toUpperCase();
    if (currentStatus === "BLOCKED" || currentStatus === "KHÓA" || currentStatus === "REVOKED") {
        return jsonResponse({
            valid: false,
            status: "BLOCKED",
            customer_name: row.customer_name || "",
            message: "Key kích hoạt này đang bị khóa bởi Quản trị viên!"
        });
    }

    // 3. Tự động gắn Mã Máy nếu key chưa được kích hoạt trên máy nào
    if (!boundMachine) {
        await env.DB.prepare(
            "UPDATE licenses SET machine_id = ?, last_verified_at = datetime('now', '+7 hours') WHERE id = ?"
        ).bind(machineId, row.id).run();
    } else if (boundMachine !== machineId) {
        // Đã gắn với máy khác -> Không cho kích hoạt trùng
        return jsonResponse({
            valid: false,
            status: "DEVICE_MISMATCH",
            customer_name: row.customer_name || "",
            message: `Key này đã được kích hoạt trên một máy tính khác (${boundMachine.slice(0, 10)}...)! Vui lòng liên hệ Admin để đổi thiết bị.`
        });
    } else {
        // Đúng máy -> Cập nhật thời điểm kiểm tra
        await env.DB.prepare(
            "UPDATE licenses SET last_verified_at = datetime('now', '+7 hours') WHERE id = ?"
        ).bind(row.id).run();
    }

    // 4. Kiểm tra thời hạn hết hạn
    const expiryRaw = (row.expiry_date || "").trim();
    const isLifetime = ["LIFETIME", "VINH VIEN", "VĨNH VIỄN", "UNLIMITED"].includes(expiryRaw.toUpperCase());

    if (!isLifetime) {
        const todayStr = getVietnamDateString();
        if (expiryRaw < todayStr) {
            // Đã hết hạn
            await env.DB.prepare(
                "UPDATE licenses SET status = 'EXPIRED' WHERE id = ?"
            ).bind(row.id).run();

            return jsonResponse({
                valid: false,
                status: "EXPIRED",
                license_key: row.license_key,
                machine_id: machineId,
                expiry_raw: expiryRaw,
                expiry_display: `Đã hết hạn vào ngày ${formatDMY(expiryRaw)}`,
                customer_name: row.customer_name || "",
                message: `Bản quyền đã hết hạn sử dụng vào ngày ${formatDMY(expiryRaw)}! Vui lòng liên hệ Admin để gia hạn.`
            });
        }
    }

    // 5. Bản quyền hợp lệ 100%
    const expiryDisplay = isLifetime ? "Vĩnh viễn (Không giới hạn)" : `Còn hạn đến ${formatDMY(expiryRaw)}`;

    return jsonResponse({
        valid: true,
        status: "ACTIVE",
        license_key: row.license_key,
        machine_id: machineId,
        expiry_raw: expiryRaw,
        expiry_display: expiryDisplay,
        customer_name: row.customer_name || "",
        note: row.note || "",
        message: `Kích hoạt thành công! Hạn dùng: ${expiryDisplay}`
    });
}

/**
 * Xử lý Tự động đăng ký máy / Kiểm tra nhanh theo Machine ID (/api/auto-register)
 */
async function handleAutoRegister(request, env) {
    const body = await request.json().catch(() => ({}));
    const machineId = String(body.machine_id || "").trim().toUpperCase();
    const computerName = String(body.computer_name || "").trim();

    if (!machineId) {
        return jsonResponse({ valid: false, message: "Thiếu Machine ID" }, 400);
    }

    // Kiểm tra xem máy này đã từng được cấp key nào chưa
    const { results } = await env.DB.prepare(
        "SELECT * FROM licenses WHERE UPPER(machine_id) = ? LIMIT 1"
    ).bind(machineId).all();

    if (results && results.length > 0) {
        const row = results[0];
        const expiryRaw = (row.expiry_date || "").trim();
        const isLifetime = ["LIFETIME", "VĨNH VIỄN"].includes(expiryRaw.toUpperCase());
        const todayStr = getVietnamDateString();
        const isExpired = !isLifetime && expiryRaw < todayStr;
        const status = isExpired ? "EXPIRED" : (row.status || "ACTIVE");

        return jsonResponse({
            valid: status === "ACTIVE",
            status: status,
            license_key: row.license_key,
            machine_id: machineId,
            expiry_raw: expiryRaw,
            expiry_display: isLifetime ? "Vĩnh viễn" : formatDMY(expiryRaw),
            customer_name: row.customer_name || computerName,
            message: isExpired ? "Bản quyền đã hết hạn" : "Đã đồng bộ thông tin bản quyền!"
        });
    }

    return jsonResponse({
        valid: false,
        status: "UNREGISTERED",
        machine_id: machineId,
        message: "Thiết bị chưa được cấp Key. Vui lòng nhập Key kích hoạt!"
    });
}

/**
 * Admin API: Lấy toàn bộ danh sách licenses
 */
async function handleAdminList(request, env) {
    const authHeader = request.headers.get("X-Admin-Key") || new URL(request.url).searchParams.get("key");
    const configuredSecret = env.ADMIN_PASSWORD || ADMIN_PASSWORD;
    if (authHeader !== configuredSecret) {
        return jsonResponse({ error: "Unauthorized" }, 401);
    }

    const { results } = await env.DB.prepare(
        "SELECT * FROM licenses ORDER BY id DESC"
    ).all();

    return jsonResponse({ success: true, data: results || [] });
}

/**
 * Admin API: Thêm hoặc Cập nhật License
 */
async function handleAdminSave(request, env) {
    const authHeader = request.headers.get("X-Admin-Key");
    const configuredSecret = env.ADMIN_PASSWORD || ADMIN_PASSWORD;
    if (authHeader !== configuredSecret) {
        return jsonResponse({ error: "Unauthorized" }, 401);
    }

    const body = await request.json();
    const id = body.id;
    const licenseKey = String(body.license_key || "").trim().toUpperCase();
    const customerName = String(body.customer_name || "").trim();
    const expiryDate = String(body.expiry_date || "").trim(); // YYYY-MM-DD hoặc LIFETIME
    const status = String(body.status || "ACTIVE").trim().toUpperCase();
    const note = String(body.note || "").trim();
    const machineId = String(body.machine_id || "").trim().toUpperCase();

    if (!licenseKey || !expiryDate) {
        return jsonResponse({ error: "Thiếu License Key hoặc Ngày hết hạn!" }, 400);
    }

    if (id) {
        // Cập nhật
        await env.DB.prepare(`
            UPDATE licenses 
            SET license_key = ?, customer_name = ?, expiry_date = ?, status = ?, note = ?, machine_id = ?
            WHERE id = ?
        `).bind(licenseKey, customerName, expiryDate, status, note, machineId, id).run();
    } else {
        // Thêm mới
        await env.DB.prepare(`
            INSERT INTO licenses (license_key, machine_id, customer_name, expiry_date, status, note)
            VALUES (?, ?, ?, ?, ?, ?)
        `).bind(licenseKey, machineId, customerName, expiryDate, status, note).run();
    }

    return jsonResponse({ success: true, message: "Đã lưu thành công!" });
}

/**
 * Admin API: Xóa License
 */
async function handleAdminDelete(request, env) {
    const authHeader = request.headers.get("X-Admin-Key");
    const configuredSecret = env.ADMIN_PASSWORD || ADMIN_PASSWORD;
    if (authHeader !== configuredSecret) {
        return jsonResponse({ error: "Unauthorized" }, 401);
    }

    const body = await request.json();
    const id = body.id;
    if (!id) return jsonResponse({ error: "Thiếu ID" }, 400);

    await env.DB.prepare("DELETE FROM licenses WHERE id = ?").bind(id).run();
    return jsonResponse({ success: true, message: "Đã xóa license!" });
}

/**
 * Admin API: Reset Mã Máy (Để khách đổi sang máy khác)
 */
async function handleAdminResetMachine(request, env) {
    const authHeader = request.headers.get("X-Admin-Key");
    const configuredSecret = env.ADMIN_PASSWORD || ADMIN_PASSWORD;
    if (authHeader !== configuredSecret) {
        return jsonResponse({ error: "Unauthorized" }, 401);
    }

    const body = await request.json();
    const id = body.id;
    if (!id) return jsonResponse({ error: "Thiếu ID" }, 400);

    await env.DB.prepare("UPDATE licenses SET machine_id = '' WHERE id = ?").bind(id).run();
    return jsonResponse({ success: true, message: "Đã reset mã máy, khách có thể kích hoạt trên máy mới!" });
}

// -------------------------------------------------------------
// HELPER FUNCTIONS
// -------------------------------------------------------------
function jsonResponse(data, status = 200) {
    return new Response(JSON.stringify(data), {
        status: status,
        headers: {
            "Content-Type": "application/json; charset=utf-8",
            ...CORS_HEADERS
        }
    });
}

function getVietnamDateString() {
    const d = new Date(Date.now() + 7 * 3600 * 1000);
    return d.toISOString().slice(0, 10);
}

function formatDMY(dateStr) {
    if (!dateStr) return "";
    if (dateStr.toUpperCase() === "LIFETIME") return "Vĩnh viễn";
    const parts = dateStr.split("-");
    if (parts.length === 3) {
        return `${parts[2]}/${parts[1]}/${parts[0]}`;
    }
    return dateStr;
}

/**
 * HTML Web Admin Dashboard
 */
function renderAdminWebPage(env) {
    const html = `<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Quản Lý Bản Quyền - Tools Marketing (Cloudflare D1)</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #0b0f19; color: #cbd5e1; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        .card { background-color: #111827; border: 1px solid #1f2937; color: #cbd5e1; border-radius: 10px; }
        .table { color: #cbd5e1; border-color: #1f2937; }
        .table-dark { background-color: #111827; }
        .badge-active { background-color: #059669; }
        .badge-blocked { background-color: #dc2626; }
        .badge-expired { background-color: #d97706; }
        .btn-primary { background-color: #2563eb; border: none; }
        .form-control, .form-select { background-color: #1f2937; border-color: #374151; color: #f9fafb; }
        .form-control:focus, .form-select:focus { background-color: #1f2937; color: #ffffff; border-color: #3b82f6; }
    </style>
</head>
<body class="p-4">
    <div class="container-fluid" style="max-width: 1300px;">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <div>
                <h3 class="fw-bold text-white mb-1">⚡ Hệ Thống Bản Quyền Tools Marketing</h3>
                <p class="text-secondary mb-0">Cơ sở dữ liệu: Cloudflare D1 (SQLite Edge) | Tốc độ phản hồi: ~40ms</p>
            </div>
            <div>
                <button class="btn btn-outline-light me-2" onclick="loadData()">🔄 Làm Mới</button>
                <button class="btn btn-primary" onclick="openModalCreate()">➕ Thêm Key Mới</button>
            </div>
        </div>

        <div class="card p-3 mb-4 shadow-sm">
            <div class="row g-2 align-items-center">
                <div class="col-md-3">
                    <input type="password" id="adminKeyInput" class="form-control" placeholder="Nhập Mật Khẩu Admin..." value="admin123">
                </div>
                <div class="col-md-3">
                    <button class="btn btn-secondary w-100" onclick="saveAdminKey()">🔐 Lưu Mật Khẩu</button>
                </div>
                <div class="col-md-6 text-end">
                    <span id="statText" class="badge bg-dark border border-secondary p-2">Đang tải...</span>
                </div>
            </div>
        </div>

        <div class="card shadow-sm">
            <div class="table-responsive">
                <table class="table table-hover align-middle mb-0">
                    <thead class="table-dark">
                        <tr>
                            <th>ID</th>
                            <th>Key Bản Quyền</th>
                            <th>Khách Hàng / Ghi Chú</th>
                            <th>Mã Máy (Machine ID)</th>
                            <th>Hạn Sử Dụng</th>
                            <th>Trạng Thái</th>
                            <th>Kiểm Tra Gần Nhất</th>
                            <th class="text-center">Thao Tác</th>
                        </tr>
                    </thead>
                    <tbody id="licenseTableBody">
                        <tr><td colspan="8" class="text-center py-4">Đang kết nối Cloudflare D1...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- Modal Thêm/Sửa Key -->
    <div class="modal fade" id="licenseModal" tabindex="-1">
        <div class="modal-dialog">
            <div class="modal-content card">
                <div class="modal-header border-secondary">
                    <h5 class="modal-title text-white" id="modalTitle">Thêm Key Bản Quyền Mới</h5>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
                    <input type="hidden" id="editId">
                    <div class="mb-3">
                        <label class="form-label">Key Bản Quyền:</label>
                        <div class="input-group">
                            <input type="text" id="mKey" class="form-control fw-bold" placeholder="VD: CWAI-VIP-9999">
                            <button class="btn btn-outline-secondary" type="button" onclick="generateRandomKey()">🎲 Tạo Tự Động</button>
                        </div>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Tên Khách Hàng:</label>
                        <input type="text" id="mCustomer" class="form-control" placeholder="VD: Anh Nam - Shopee">
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Hạn Dùng:</label>
                        <div class="row g-2">
                            <div class="col-8">
                                <input type="text" id="mExpiry" class="form-control" placeholder="YYYY-MM-DD hoặc LIFETIME" value="LIFETIME">
                            </div>
                            <div class="col-4">
                                <select class="form-select" onchange="applyExpiryPreset(this.value)">
                                    <option value="">Chọn nhanh...</option>
                                    <option value="7">7 Ngày</option>
                                    <option value="30">1 Tháng</option>
                                    <option value="90">3 Tháng</option>
                                    <option value="365">1 Năm</option>
                                    <option value="LIFETIME">Vĩnh viễn</option>
                                </select>
                            </div>
                        </div>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Mã Máy Gắn Liền (Để trống nếu muốn tự gắn máy đầu tiên):</label>
                        <input type="text" id="mMachine" class="form-control" placeholder="Tự động gắn khi khách kích hoạt">
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Trạng Thái:</label>
                        <select id="mStatus" class="form-select">
                            <option value="ACTIVE">ACTIVE (Đang hoạt động)</option>
                            <option value="BLOCKED">BLOCKED (Khóa bản quyền)</option>
                            <option value="EXPIRED">EXPIRED (Hết hạn)</option>
                        </select>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Ghi Chú:</label>
                        <input type="text" id="mNote" class="form-control" placeholder="Ghi chú thêm...">
                    </div>
                </div>
                <div class="modal-footer border-secondary">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Hủy</button>
                    <button type="button" class="btn btn-primary" onclick="saveLicense()">💾 Lưu Key</button>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        let modalInstance = null;
        let adminKey = localStorage.getItem('cf_admin_key') || 'admin123';
        document.getElementById('adminKeyInput').value = adminKey;

        function saveAdminKey() {
            adminKey = document.getElementById('adminKeyInput').value.trim();
            localStorage.setItem('cf_admin_key', adminKey);
            loadData();
        }

        async function loadData() {
            const tbody = document.getElementById('licenseTableBody');
            tbody.innerHTML = '<tr><td colspan="8" class="text-center py-4">Đang tải dữ liệu từ D1...</td></tr>';
            try {
                const res = await fetch('/api/admin/list', {
                    headers: { 'X-Admin-Key': adminKey }
                });
                if (res.status === 401) {
                    tbody.innerHTML = '<tr><td colspan="8" class="text-center text-danger py-4">❌ Mật khẩu Admin chưa đúng! Hãy nhập mật khẩu ở ô trên rồi bấm Lưu.</td></tr>';
                    return;
                }
                const json = await res.json();
                const list = json.data || [];
                document.getElementById('statText').innerText = 'Tổng số Key: ' + list.length;
                if (list.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="8" class="text-center py-4 text-secondary">Chưa có Key nào. Hãy bấm "Thêm Key Mới"!</td></tr>';
                    return;
                }
                let html = '';
                for (const item of list) {
                    let badgeClass = 'badge-active';
                    if (item.status === 'BLOCKED') badgeClass = 'badge-blocked';
                    else if (item.status === 'EXPIRED') badgeClass = 'badge-expired';

                    const boundMac = item.machine_id ? item.machine_id : '<span class="text-muted fst-italic">Chưa gắn máy</span>';
                    html += \`<tr>
                        <td>\${item.id}</td>
                        <td class="fw-bold text-info">\${item.license_key}</td>
                        <td>
                            <div class="fw-semibold text-white">\${item.customer_name || 'Khách lẻ'}</div>
                            <small class="text-muted">\${item.note || ''}</small>
                        </td>
                        <td><small style="font-family: monospace;">\${boundMac}</small></td>
                        <td><span class="badge bg-secondary">\${item.expiry_date}</span></td>
                        <td><span class="badge \${badgeClass}">\${item.status}</span></td>
                        <td><small class="text-muted">\${item.last_verified_at || '--'}</small></td>
                        <td class="text-center">
                            <button class="btn btn-sm btn-outline-info me-1" onclick='editItem(\${JSON.stringify(item)})'>Sửa</button>
                            \${item.machine_id ? \`<button class="btn btn-sm btn-outline-warning me-1" onclick="resetMachine(\${item.id})" title="Cho phép khách đổi máy">Đổi Máy</button>\` : ''}
                            <button class="btn btn-sm btn-outline-danger" onclick="deleteItem(\${item.id})">Xóa</button>
                        </td>
                    </tr>\`;
                }
                tbody.innerHTML = html;
            } catch (e) {
                tbody.innerHTML = '<tr><td colspan="8" class="text-center text-danger py-4">Lỗi kết nối: ' + e.message + '</td></tr>';
            }
        }

        function openModalCreate() {
            document.getElementById('editId').value = '';
            document.getElementById('modalTitle').innerText = 'Thêm Key Bản Quyền Mới';
            document.getElementById('mKey').value = '';
            document.getElementById('mCustomer').value = '';
            document.getElementById('mExpiry').value = 'LIFETIME';
            document.getElementById('mMachine').value = '';
            document.getElementById('mStatus').value = 'ACTIVE';
            document.getElementById('mNote').value = '';
            generateRandomKey();
            if (!modalInstance) modalInstance = new bootstrap.Modal(document.getElementById('licenseModal'));
            modalInstance.show();
        }

        function editItem(item) {
            document.getElementById('editId').value = item.id;
            document.getElementById('modalTitle').innerText = 'Chỉnh Sửa Key #' + item.id;
            document.getElementById('mKey').value = item.license_key;
            document.getElementById('mCustomer').value = item.customer_name || '';
            document.getElementById('mExpiry').value = item.expiry_date || '';
            document.getElementById('mMachine').value = item.machine_id || '';
            document.getElementById('mStatus').value = item.status || 'ACTIVE';
            document.getElementById('mNote').value = item.note || '';
            if (!modalInstance) modalInstance = new bootstrap.Modal(document.getElementById('licenseModal'));
            modalInstance.show();
        }

        async function saveLicense() {
            const id = document.getElementById('editId').value;
            const data = {
                id: id ? parseInt(id) : null,
                license_key: document.getElementById('mKey').value.trim(),
                customer_name: document.getElementById('mCustomer').value.trim(),
                expiry_date: document.getElementById('mExpiry').value.trim(),
                machine_id: document.getElementById('mMachine').value.trim(),
                status: document.getElementById('mStatus').value,
                note: document.getElementById('mNote').value.trim()
            };
            if (!data.license_key) { alert('Vui lòng nhập Key!'); return; }
            const res = await fetch('/api/admin/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey },
                body: JSON.stringify(data)
            });
            const j = await res.json();
            if (j.success) {
                if (modalInstance) modalInstance.hide();
                loadData();
            } else {
                alert(j.error || 'Lỗi khi lưu');
            }
        }

        async function resetMachine(id) {
            if (!confirm('Khách hàng sẽ có thể kích hoạt key này trên một máy tính mới. Tiếp tục?')) return;
            const res = await fetch('/api/admin/reset-machine', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey },
                body: JSON.stringify({ id })
            });
            loadData();
        }

        async function deleteItem(id) {
            if (!confirm('Bạn có chắc muốn xóa Key này không?')) return;
            const res = await fetch('/api/admin/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey },
                body: JSON.stringify({ id })
            });
            loadData();
        }

        function generateRandomKey() {
            const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
            let part1 = '', part2 = '', part3 = '';
            for (let i = 0; i < 4; i++) part1 += chars.charAt(Math.floor(Math.random() * chars.length));
            for (let i = 0; i < 4; i++) part2 += chars.charAt(Math.floor(Math.random() * chars.length));
            for (let i = 0; i < 4; i++) part3 += chars.charAt(Math.floor(Math.random() * chars.length));
            document.getElementById('mKey').value = 'CWAI-' + part1 + '-' + part2 + '-' + part3;
        }

        function applyExpiryPreset(days) {
            if (!days) return;
            if (days === 'LIFETIME') {
                document.getElementById('mExpiry').value = 'LIFETIME';
                return;
            }
            const d = new Date();
            d.setDate(d.getDate() + parseInt(days));
            document.getElementById('mExpiry').value = d.toISOString().slice(0, 10);
        }

        loadData();
    </script>
</body>
</html>`;
    return new Response(html, {
        headers: { "Content-Type": "text/html; charset=utf-8" }
    });
}
