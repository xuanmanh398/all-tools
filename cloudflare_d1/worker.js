import { connect } from "cloudflare:sockets";

/**
 * Cloudflare Worker: Hệ Thống Bản Quyền, Quản Lý Upload File & Trang Tải/Hướng Dẫn
 * (Cloudflare D1 + Cloudflare KV Streaming)
 *
 * Tính năng:
 * 1. API Xác Thực Key (/api/verify) & Auto Register (/api/auto-register).
 * 2. Chuyển hướng Link Rút Gọn (/s/:code) & API Rút Gọn (/api/shorten).
 * 3. Trang Quản Trị Admin (/ hoặc /admin):
 *    - Quản lý Key bản quyền
 *    - Upload File dung lượng lớn (chia chunk 4MB lưu Cloudflare KV) & Link tải ngoài
 *    - Quản lý bài viết / video Hướng dẫn
 * 4. Trang Công Khai "Tải và hướng dẫn" (/tai-va-huong-dan, /download, /huong-dan):
 *    - Cho phép người dùng tải phần mềm, file mẫu và xem hướng dẫn chi tiết.
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
            // 0. CHUYỂN HƯỚNG LINK RÚT GỌN (VD: /s/abc12)
            if (path.startsWith("/s/")) {
                const sCode = path.replace("/s/", "").trim();
                return await handleRedirectShortLink(sCode, env, request);
            }

            // 0.1 API TẠO LINK RÚT GỌN
            if (path === "/api/shorten" && request.method === "POST") {
                return await handleShortenLink(request, env);
            }

            // 1. API XÁC THỰC BẢN QUYỀN TỪ PHẦN MỀM DESKTOP
            if (path === "/api/verify" && request.method === "POST") {
                return await handleVerifyLicense(request, env);
            }

            // 2. API TỰ ĐỘNG ĐĂNG KÝ / LẤY THÔNG TIN MÁY
            if (path === "/api/auto-register" && request.method === "POST") {
                return await handleAutoRegister(request, env);
            }

            // 3. API ADMIN QUẢN LÝ KEY BẢN QUYỀN
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

            // 4. API ADMIN QUẢN LÝ FILE UPLOAD & LINK TẢI
            if (path === "/api/admin/files/list") {
                return await handleAdminFilesList(request, env);
            }
            if (path === "/api/admin/files/init" && request.method === "POST") {
                return await handleAdminFilesInit(request, env);
            }
            if (path === "/api/admin/files/chunk" && request.method === "POST") {
                return await handleAdminFilesChunk(request, env);
            }
            if (path === "/api/admin/files/complete" && request.method === "POST") {
                return await handleAdminFilesComplete(request, env);
            }
            if (path === "/api/admin/files/save-link" && request.method === "POST") {
                return await handleAdminFilesSaveLink(request, env);
            }
            if (path === "/api/admin/files/delete" && request.method === "POST") {
                return await handleAdminFilesDelete(request, env);
            }

            // 5. API ADMIN QUẢN LÝ HƯỚNG DẪN
            if (path === "/api/admin/guides/list") {
                return await handleAdminGuidesList(request, env);
            }
            if (path === "/api/admin/guides/save" && request.method === "POST") {
                return await handleAdminGuidesSave(request, env);
            }
            if (path === "/api/admin/guides/delete" && request.method === "POST") {
                return await handleAdminGuidesDelete(request, env);
            }

            // 5.5 API SEPAY & NẠP TỰ ĐỘNG BẢN QUYỀN
            if (path === "/api/admin/sepay/settings") {
                return await handleAdminSepaySettings(request, env);
            }
            if (path === "/api/admin/sepay/orders") {
                return await handleAdminSepayOrders(request, env);
            }
            if (path === "/api/admin/sepay/test-email" && request.method === "POST") {
                return await handleAdminTestEmail(request, env);
            }
            if (path === "/api/admin/revenue/summary") {
                return await handleAdminRevenueSummary(request, env);
            }
            if (path === "/api/admin/revenue/reset" && request.method === "POST") {
                return await handleAdminRevenueReset(request, env);
            }
            if (path === "/api/admin/vouchers/list") {
                return await handleAdminVouchersList(request, env);
            }
            if (path === "/api/admin/vouchers/save" && request.method === "POST") {
                return await handleAdminVouchersSave(request, env);
            }
            if (path === "/api/admin/vouchers/delete" && request.method === "POST") {
                return await handleAdminVouchersDelete(request, env);
            }
            if (path === "/api/payment/packages") {
                return await handlePaymentPackages(env);
            }
            if (path === "/api/payment/apply-voucher" && request.method === "POST") {
                return await handlePaymentApplyVoucher(request, env);
            }
            if (path === "/api/payment/create-order" && request.method === "POST") {
                return await handlePaymentCreateOrder(request, env);
            }
            if (path === "/api/payment/status") {
                return await handlePaymentStatus(request, env);
            }
            if (path === "/api/sepay/webhook" && request.method === "POST") {
                return await handleSepayWebhook(request, env);
            }

            // 6. API CÔNG KHAI & TẢI FILE STREAMING
            if (path === "/api/public/resources") {
                return await handlePublicResources(env);
            }
            if (path.startsWith("/download/file/") || path.startsWith("/api/files/download/")) {
                const parts = path.split("/").filter(Boolean);
                const fileId = parts[parts.length - 1];
                return await handleDownloadFile(fileId, env, request);
            }

            // 7. TRANG CÔNG KHAI: TẢI VÀ HƯỚNG DẪN
            if (
                path === "/tai-va-huong-dan" ||
                path === "/download" ||
                path === "/huong-dan" ||
                path === "/guide"
            ) {
                return await renderDownloadAndGuidePage(env, url);
            }

            // 8. TRANG WEB QUẢN TRỊ ADMIN
            if (path === "/" || path === "/admin") {
                return renderAdminWebPage(env);
            }

            return jsonResponse({ error: "Endpoint not found" }, 404);
        } catch (err) {
            return jsonResponse({ valid: false, error: err.message, stack: String(err.stack) }, 500);
        }
    }
};

// =============================================================
// BẢO ĐẢM CẤU TRÚC BẢNG & DỮ LIỆU MẶC ĐỊNH
// =============================================================
async function ensureExtraTables(env) {
    if (!env.DB) return;
    await env.DB.prepare(`
        CREATE TABLE IF NOT EXISTS app_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_size INTEGER DEFAULT 0,
            version TEXT DEFAULT '',
            category TEXT DEFAULT 'software',
            description TEXT DEFAULT '',
            storage_type TEXT DEFAULT 'kv',
            external_url TEXT DEFAULT '',
            chunk_count INTEGER DEFAULT 0,
            content_type TEXT DEFAULT 'application/octet-stream',
            download_count INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT (datetime('now', '+7 hours'))
        )
    `).run();

    await env.DB.prepare(`
        CREATE TABLE IF NOT EXISTS guides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            video_url TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            updated_at DATETIME DEFAULT (datetime('now', '+7 hours'))
        )
    `).run();

    await env.DB.prepare(`
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        )
    `).run();

    await env.DB.prepare(`
        CREATE TABLE IF NOT EXISTS payment_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_code TEXT UNIQUE NOT NULL,
            machine_id TEXT NOT NULL,
            license_key TEXT DEFAULT '',
            package_id TEXT DEFAULT '1m',
            original_amount INTEGER DEFAULT 0,
            discount_amount INTEGER DEFAULT 0,
            voucher_code TEXT DEFAULT '',
            amount INTEGER NOT NULL,
            days_to_add INTEGER NOT NULL,
            status TEXT DEFAULT 'PENDING',
            sepay_tx_id TEXT DEFAULT '',
            created_at DATETIME DEFAULT (datetime('now', '+7 hours')),
            paid_at DATETIME DEFAULT NULL
        )
    `).run();

    await env.DB.prepare("ALTER TABLE payment_orders ADD COLUMN original_amount INTEGER DEFAULT 0").run().catch(() => {});
    await env.DB.prepare("ALTER TABLE payment_orders ADD COLUMN discount_amount INTEGER DEFAULT 0").run().catch(() => {});
    await env.DB.prepare("ALTER TABLE payment_orders ADD COLUMN voucher_code TEXT DEFAULT ''").run().catch(() => {});

    await env.DB.prepare(`
        CREATE TABLE IF NOT EXISTS vouchers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            discount_type TEXT DEFAULT 'percent',
            discount_value INTEGER NOT NULL,
            max_uses INTEGER DEFAULT 0,
            used_count INTEGER DEFAULT 0,
            expires_at TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT (datetime('now', '+7 hours'))
        )
    `).run();

    // Tự động thêm hướng dẫn mẫu nếu bảng guides đang trống
    const { results } = await env.DB.prepare("SELECT COUNT(*) as cnt FROM guides").all();
    const count = results && results[0] ? Number(results[0].cnt) : 0;
    if (count === 0) {
        const defaults = [
            {
                sort_order: 1,
                title: "Bước 1: Tải và Cài đặt Phần mềm Auto Post",
                content: "1. Bấm nút Tải Ngay bộ cài đặt (AutoPost_Setup_v1.0.exe) ở mục phía trên.\n2. Mở file vừa tải về. Nếu Windows SmartScreen hiện cảnh báo, bấm 'More info' -> 'Run anyway' để tiếp tục cài đặt.\n3. Sau khi cài đặt hoàn tất, mở biểu tượng Auto Post ngoài màn hình Desktop.",
                video_url: ""
            },
            {
                sort_order: 2,
                title: "Bước 2: Kích hoạt Bản quyền Phần mềm",
                content: "1. Khi mở phần mềm lần đầu, phần mềm sẽ hiển thị Mã Máy (Machine ID) của bạn.\n2. Nhập Key bản quyền được Admin cung cấp và bấm 'Kích hoạt'.\n3. Hệ thống sẽ tự động liên kết Key với máy tính của bạn trong ~1 giây.",
                video_url: ""
            },
            {
                sort_order: 3,
                title: "Bước 3: Đăng nhập Tài khoản Facebook & Nhập Kịch bản Excel",
                content: "1. Vào mục Quản Lý Tài Khoản -> Thêm tài khoản Facebook (hỗ trợ Cookie hoặc Đăng nhập trực tiếp trên trình duyệt Chrome).\n2. Bấm 'Đồng bộ Nhóm / Fanpage' để lấy danh sách nhóm cần đăng.\n3. Nhập file Excel kịch bản nội dung, đường dẫn video/hình ảnh và cấu hình thời gian giãn cách an toàn chống checkpoint.\n4. Bấm 'BẮT ĐẦU CHẠY' để phần mềm tự động đăng bài và seeding bình luận.",
                video_url: ""
            }
        ];
        for (const g of defaults) {
            await env.DB.prepare(
                "INSERT INTO guides (title, content, video_url, sort_order, is_active) VALUES (?, ?, ?, ?, 1)"
            ).bind(g.title, g.content, g.video_url, g.sort_order).run();
        }
    }
}

function checkAdminAuth(request, env) {
    return true;
}

// =============================================================
// LICENSE VERIFICATION & MANAGEMENT HANDLERS
// =============================================================
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
    const currentStatus = (row.status || "ACTIVE").toUpperCase();

    if (currentStatus === "BLOCKED" || currentStatus === "KHÓA" || currentStatus === "REVOKED") {
        return jsonResponse({
            valid: false,
            status: "BLOCKED",
            customer_name: row.customer_name || "",
            message: "Key kích hoạt này đang bị khóa bởi Quản trị viên!"
        });
    }

    const expiryRaw = (row.expiry_date || "").trim();
    const isPending = currentStatus === "PENDING" || ["PENDING", "", "CHỜ KÍCH HOẠT"].includes(expiryRaw.toUpperCase());

    if (isPending) {
        return jsonResponse({
            valid: false,
            status: "PENDING",
            license_key: row.license_key,
            machine_id: machineId,
            expiry_raw: expiryRaw,
            expiry_display: "Chờ Admin kích hoạt",
            customer_name: row.customer_name || "",
            message: "Key này đang chờ Quản trị viên cấp thời hạn sử dụng!"
        });
    }

    if (!boundMachine) {
        await env.DB.prepare(
            "UPDATE licenses SET machine_id = ?, last_verified_at = datetime('now', '+7 hours') WHERE id = ?"
        ).bind(machineId, row.id).run();
    } else if (boundMachine !== machineId) {
        return jsonResponse({
            valid: false,
            status: "DEVICE_MISMATCH",
            customer_name: row.customer_name || "",
            message: `Key này đã được kích hoạt trên một máy tính khác (${boundMachine.slice(0, 10)}...)! Vui lòng liên hệ Admin để đổi thiết bị.`
        });
    } else {
        await env.DB.prepare(
            "UPDATE licenses SET last_verified_at = datetime('now', '+7 hours') WHERE id = ?"
        ).bind(row.id).run();
    }

    const isLifetime = ["LIFETIME", "VINH VIEN", "VĨNH VIỄN", "UNLIMITED"].includes(expiryRaw.toUpperCase());

    if (!isLifetime) {
        const todayStr = getVietnamDateString();
        if (expiryRaw < todayStr) {
            await env.DB.prepare("UPDATE licenses SET status = 'EXPIRED' WHERE id = ?").bind(row.id).run();
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

async function handleAutoRegister(request, env) {
    const body = await request.json().catch(() => ({}));
    const machineId = String(body.machine_id || "").trim().toUpperCase();
    const computerName = String(body.computer_name || "").trim();

    if (!machineId) {
        return jsonResponse({ valid: false, message: "Thiếu Machine ID" }, 400);
    }

    const { results } = await env.DB.prepare(
        "SELECT * FROM licenses WHERE UPPER(machine_id) = ? LIMIT 1"
    ).bind(machineId).all();

    if (results && results.length > 0) {
        const row = results[0];
        const expiryRaw = (row.expiry_date || "").trim();
        const rawStatus = (row.status || "ACTIVE").trim().toUpperCase();

        await env.DB.prepare(
            "UPDATE licenses SET last_verified_at = datetime('now', '+7 hours') WHERE id = ?"
        ).bind(row.id).run().catch(() => {});

        if (rawStatus === "BLOCKED" || rawStatus === "KHÓA" || rawStatus === "REVOKED") {
            return jsonResponse({
                valid: false,
                status: "BLOCKED",
                license_key: row.license_key,
                machine_id: machineId,
                expiry_raw: expiryRaw,
                expiry_display: "Đã bị khóa",
                customer_name: row.customer_name || computerName,
                message: "Bản quyền máy này đang bị khóa bởi Quản trị viên!"
            });
        }

        const isPending = rawStatus === "PENDING" || ["PENDING", "", "CHỜ KÍCH HOẠT"].includes(expiryRaw.toUpperCase());
        if (isPending) {
            return jsonResponse({
                valid: false,
                status: "PENDING",
                license_key: row.license_key,
                machine_id: machineId,
                expiry_raw: expiryRaw,
                expiry_display: "Chờ Admin kích hoạt",
                customer_name: row.customer_name || computerName,
                message: "Thiết bị đã được ghi nhận. Vui lòng chờ Admin kích hoạt thời hạn!"
            });
        }

        const isLifetime = ["LIFETIME", "VINH VIEN", "VĨNH VIỄN", "UNLIMITED"].includes(expiryRaw.toUpperCase());
        const todayStr = getVietnamDateString();
        const isExpired = !isLifetime && expiryRaw < todayStr;
        const status = isExpired ? "EXPIRED" : "ACTIVE";

        return jsonResponse({
            valid: status === "ACTIVE",
            status: status,
            license_key: row.license_key,
            machine_id: machineId,
            expiry_raw: expiryRaw,
            expiry_display: isLifetime ? "Vĩnh viễn" : formatDMY(expiryRaw),
            customer_name: row.customer_name || computerName,
            message: isExpired ? `Bản quyền đã hết hạn (${formatDMY(expiryRaw)})` : "Đã đồng bộ thông tin bản quyền!"
        });
    }

    // Máy mới cài đặt chưa có trên hệ thống -> Tự động sinh Key và cấp 5 ngày dùng thử miễn phí
    const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
    const randPart = () => {
        let s = "";
        for (let i = 0; i < 4; i++) s += chars.charAt(Math.floor(Math.random() * chars.length));
        return s;
    };
    const newKey = `CWAI-${randPart()}-${randPart()}-${randPart()}`;
    const defaultCustomer = computerName ? `Máy mới: ${computerName}` : "Khách hàng mới";
    const trialExpiry = new Date(Date.now() + 7 * 3600 * 1000 + 5 * 86400 * 1000).toISOString().slice(0, 10);

    await env.DB.prepare(`
        INSERT INTO licenses (license_key, machine_id, customer_name, expiry_date, status, last_verified_at, note)
        VALUES (?, ?, ?, ?, 'ACTIVE', datetime('now', '+7 hours'), 'Dùng thử miễn phí 5 ngày')
    `).bind(newKey, machineId, defaultCustomer, trialExpiry).run();

    return jsonResponse({
        valid: true,
        status: "ACTIVE",
        license_key: newKey,
        machine_id: machineId,
        expiry_raw: trialExpiry,
        expiry_display: formatDMY(trialExpiry),
        customer_name: defaultCustomer,
        message: `Đã tự động kích hoạt dùng thử miễn phí 5 ngày (đến ${formatDMY(trialExpiry)})!`
    });
}

async function handleAdminList(request, env) {
    if (!checkAdminAuth(request, env)) return jsonResponse({ error: "Unauthorized" }, 401);
    const { results } = await env.DB.prepare("SELECT * FROM licenses ORDER BY id DESC").all();
    return jsonResponse({ success: true, data: results || [] });
}

async function handleAdminSave(request, env) {
    if (!checkAdminAuth(request, env)) return jsonResponse({ error: "Unauthorized" }, 401);

    const body = await request.json();
    const id = body.id;
    const licenseKey = String(body.license_key || "").trim().toUpperCase();
    const customerName = String(body.customer_name || "").trim();
    const expiryDate = String(body.expiry_date || "").trim();
    const status = String(body.status || "ACTIVE").trim().toUpperCase();
    const note = String(body.note || "").trim();
    const machineId = String(body.machine_id || "").trim().toUpperCase();

    if (!licenseKey || !expiryDate) {
        return jsonResponse({ error: "Thiếu License Key hoặc Ngày hết hạn!" }, 400);
    }

    if (id) {
        await env.DB.prepare(`
            UPDATE licenses 
            SET license_key = ?, customer_name = ?, expiry_date = ?, status = ?, note = ?, machine_id = ?
            WHERE id = ?
        `).bind(licenseKey, customerName, expiryDate, status, note, machineId, id).run();
    } else {
        await env.DB.prepare(`
            INSERT INTO licenses (license_key, machine_id, customer_name, expiry_date, status, note)
            VALUES (?, ?, ?, ?, ?, ?)
        `).bind(licenseKey, machineId, customerName, expiryDate, status, note).run();
    }

    return jsonResponse({ success: true, message: "Đã lưu thành công!" });
}

async function handleAdminDelete(request, env) {
    if (!checkAdminAuth(request, env)) return jsonResponse({ error: "Unauthorized" }, 401);
    const body = await request.json();
    const id = body.id;
    if (!id) return jsonResponse({ error: "Thiếu ID" }, 400);
    await env.DB.prepare("DELETE FROM licenses WHERE id = ?").bind(id).run();
    return jsonResponse({ success: true, message: "Đã xóa license!" });
}

async function handleAdminResetMachine(request, env) {
    if (!checkAdminAuth(request, env)) return jsonResponse({ error: "Unauthorized" }, 401);
    const body = await request.json().catch(() => ({}));
    const id = body.id;
    const newMachineId = String(body.new_machine_id || "").trim().toUpperCase();
    if (!id) return jsonResponse({ error: "Thiếu ID" }, 400);
    if (!newMachineId) {
        return jsonResponse({ error: "Vui lòng nhập Mã Máy Mới thì mới cho phép đổi máy!" }, 400);
    }
    await env.DB.prepare("UPDATE licenses SET machine_id = ? WHERE id = ?").bind(newMachineId, id).run();
    return jsonResponse({ success: true, message: "Đã đổi sang mã máy mới: " + newMachineId });
}

// =============================================================
// FILE UPLOAD & MANAGEMENT HANDLERS (CLOUDFLARE KV + D1)
// =============================================================
async function handleAdminFilesList(request, env) {
    if (!checkAdminAuth(request, env)) return jsonResponse({ error: "Unauthorized" }, 401);
    await ensureExtraTables(env);
    const { results } = await env.DB.prepare("SELECT * FROM app_files ORDER BY id DESC").all();
    return jsonResponse({ success: true, data: results || [] });
}

async function handleAdminFilesInit(request, env) {
    if (!checkAdminAuth(request, env)) return jsonResponse({ error: "Unauthorized" }, 401);
    if (!env.FILES_KV) {
        return jsonResponse({ error: "Chưa cấu hình KV FILES_KV trên Worker!" }, 500);
    }
    await ensureExtraTables(env);

    const body = await request.json().catch(() => ({}));
    const replaceId = body.replace_id ? Number(body.replace_id) : null;
    const title = String(body.title || body.file_name || "").trim();
    const fileName = String(body.file_name || "file.bin").trim();
    const fileSize = Number(body.file_size || 0);
    const version = String(body.version || "").trim();
    const category = String(body.category || "software").trim();
    const description = String(body.description || "").trim();
    const contentType = String(body.content_type || "application/octet-stream").trim();
    const chunkCount = Number(body.chunk_count || 0);

    if (!title || !fileName || chunkCount <= 0) {
        return jsonResponse({ error: "Thiếu thông tin file hoặc số chunk không hợp lệ!" }, 400);
    }

    if (replaceId) {
        const existing = await env.DB.prepare("SELECT storage_type, chunk_count FROM app_files WHERE id = ? LIMIT 1").bind(replaceId).all();
        if (!existing.results || existing.results.length === 0) {
            return jsonResponse({ error: "Không tìm thấy bản ghi file cần thay thế!" }, 404);
        }
        const oldRow = existing.results[0];
        if (oldRow.storage_type === "kv" && env.FILES_KV) {
            const oldCount = Number(oldRow.chunk_count || 0);
            for (let i = 0; i < oldCount; i++) {
                await env.FILES_KV.delete(`file_${replaceId}_chunk_${i}`).catch(() => {});
            }
        }
        await env.DB.prepare(`
            UPDATE app_files
            SET title = ?, file_name = ?, file_size = ?, version = ?, category = ?, description = ?,
                storage_type = 'kv', external_url = '', chunk_count = ?, content_type = ?, created_at = datetime('now', '+7 hours')
            WHERE id = ?
        `).bind(title, fileName, fileSize, version, category, description, chunkCount, contentType, replaceId).run();

        return jsonResponse({ success: true, file_id: replaceId });
    }

    const res = await env.DB.prepare(`
        INSERT INTO app_files (title, file_name, file_size, version, category, description, storage_type, external_url, chunk_count, content_type, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'kv', '', ?, ?, 0, datetime('now', '+7 hours'))
    `).bind(title, fileName, fileSize, version, category, description, chunkCount, contentType).run();

    const fileId = res.meta && res.meta.last_row_id ? res.meta.last_row_id : null;
    if (!fileId) {
        return jsonResponse({ error: "Không thể khởi tạo bản ghi file trong D1!" }, 500);
    }

    return jsonResponse({ success: true, file_id: fileId });
}

async function handleAdminFilesChunk(request, env) {
    if (!checkAdminAuth(request, env)) return jsonResponse({ error: "Unauthorized" }, 401);
    if (!env.FILES_KV) return jsonResponse({ error: "Chưa cấu hình KV FILES_KV!" }, 500);

    const url = new URL(request.url);
    const fileId = url.searchParams.get("file_id");
    const chunkIndex = url.searchParams.get("chunk_index");

    if (!fileId || chunkIndex === null || chunkIndex === undefined) {
        return jsonResponse({ error: "Thiếu file_id hoặc chunk_index!" }, 400);
    }

    const buf = await request.arrayBuffer();
    if (!buf || buf.byteLength === 0) {
        return jsonResponse({ error: "Dữ liệu chunk rỗng!" }, 400);
    }

    const kvKey = `file_${fileId}_chunk_${chunkIndex}`;
    await env.FILES_KV.put(kvKey, buf);

    return jsonResponse({ success: true, chunk_index: Number(chunkIndex), bytes: buf.byteLength });
}

async function handleAdminFilesComplete(request, env) {
    if (!checkAdminAuth(request, env)) return jsonResponse({ error: "Unauthorized" }, 401);
    const body = await request.json().catch(() => ({}));
    const fileId = body.file_id;
    if (!fileId) return jsonResponse({ error: "Thiếu file_id!" }, 400);

    await env.DB.prepare("UPDATE app_files SET is_active = 1 WHERE id = ?").bind(fileId).run();
    return jsonResponse({ success: true, message: "Upload file hoàn tất!" });
}

async function handleAdminFilesSaveLink(request, env) {
    if (!checkAdminAuth(request, env)) return jsonResponse({ error: "Unauthorized" }, 401);
    await ensureExtraTables(env);

    const body = await request.json().catch(() => ({}));
    const id = body.id;
    const title = String(body.title || "").trim();
    const fileName = String(body.file_name || "").trim() || title;
    const version = String(body.version || "").trim();
    const category = String(body.category || "software").trim();
    const description = String(body.description || "").trim();
    const externalUrl = String(body.external_url || "").trim();
    const isActive = body.is_active !== undefined ? (body.is_active ? 1 : 0) : 1;

    if (!title) return jsonResponse({ error: "Vui lòng nhập Tên hiển thị!" }, 400);

    if (id) {
        // Chỉ cập nhật metadata (nếu là external link thì cập nhật thêm external_url)
        const existing = await env.DB.prepare("SELECT storage_type FROM app_files WHERE id = ? LIMIT 1").bind(id).all();
        const stType = (existing.results && existing.results[0]) ? existing.results[0].storage_type : "external";
        if (stType === "external") {
            await env.DB.prepare(`
                UPDATE app_files
                SET title = ?, file_name = ?, version = ?, category = ?, description = ?, external_url = ?, is_active = ?
                WHERE id = ?
            `).bind(title, fileName, version, category, description, externalUrl, isActive, id).run();
        } else {
            await env.DB.prepare(`
                UPDATE app_files
                SET title = ?, file_name = ?, version = ?, category = ?, description = ?, is_active = ?
                WHERE id = ?
            `).bind(title, fileName, version, category, description, isActive, id).run();
        }
    } else {
        if (!externalUrl) return jsonResponse({ error: "Vui lòng nhập Link tải ngoài!" }, 400);
        await env.DB.prepare(`
            INSERT INTO app_files (title, file_name, file_size, version, category, description, storage_type, external_url, chunk_count, is_active, created_at)
            VALUES (?, ?, 0, ?, ?, ?, 'external', ?, 0, ?, datetime('now', '+7 hours'))
        `).bind(title, fileName, version, category, description, externalUrl, isActive).run();
    }

    return jsonResponse({ success: true, message: "Đã lưu thông tin tài liệu / file!" });
}

async function handleAdminFilesDelete(request, env) {
    if (!checkAdminAuth(request, env)) return jsonResponse({ error: "Unauthorized" }, 401);
    const body = await request.json().catch(() => ({}));
    const id = body.id;
    if (!id) return jsonResponse({ error: "Thiếu ID file!" }, 400);

    const { results } = await env.DB.prepare("SELECT storage_type, chunk_count FROM app_files WHERE id = ? LIMIT 1").bind(id).all();
    if (results && results.length > 0 && results[0].storage_type === "kv" && env.FILES_KV) {
        const count = Number(results[0].chunk_count || 0);
        for (let i = 0; i < count; i++) {
            await env.FILES_KV.delete(`file_${id}_chunk_${i}`).catch(() => {});
        }
    }

    await env.DB.prepare("DELETE FROM app_files WHERE id = ?").bind(id).run();
    return jsonResponse({ success: true, message: "Đã xóa file và giải phóng dung lượng!" });
}

// =============================================================
// GUIDES MANAGEMENT HANDLERS
// =============================================================
async function handleAdminGuidesList(request, env) {
    if (!checkAdminAuth(request, env)) return jsonResponse({ error: "Unauthorized" }, 401);
    await ensureExtraTables(env);
    const { results } = await env.DB.prepare("SELECT * FROM guides ORDER BY sort_order ASC, id ASC").all();
    return jsonResponse({ success: true, data: results || [] });
}

async function handleAdminGuidesSave(request, env) {
    if (!checkAdminAuth(request, env)) return jsonResponse({ error: "Unauthorized" }, 401);
    await ensureExtraTables(env);

    const body = await request.json().catch(() => ({}));
    const id = body.id;
    const title = String(body.title || "").trim();
    const content = String(body.content || "").trim();
    const videoUrl = String(body.video_url || "").trim();
    const sortOrder = Number(body.sort_order || 0);
    const isActive = body.is_active !== undefined ? (body.is_active ? 1 : 0) : 1;

    if (!title || !content) {
        return jsonResponse({ error: "Vui lòng nhập đầy đủ Tiêu đề và Nội dung hướng dẫn!" }, 400);
    }

    if (id) {
        await env.DB.prepare(`
            UPDATE guides SET title = ?, content = ?, video_url = ?, sort_order = ?, is_active = ?, updated_at = datetime('now', '+7 hours')
            WHERE id = ?
        `).bind(title, content, videoUrl, sortOrder, isActive, id).run();
    } else {
        await env.DB.prepare(`
            INSERT INTO guides (title, content, video_url, sort_order, is_active, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now', '+7 hours'))
        `).bind(title, content, videoUrl, sortOrder, isActive).run();
    }

    return jsonResponse({ success: true, message: "Đã lưu mục hướng dẫn!" });
}

async function handleAdminGuidesDelete(request, env) {
    if (!checkAdminAuth(request, env)) return jsonResponse({ error: "Unauthorized" }, 401);
    const body = await request.json().catch(() => ({}));
    const id = body.id;
    if (!id) return jsonResponse({ error: "Thiếu ID hướng dẫn!" }, 400);
    await env.DB.prepare("DELETE FROM guides WHERE id = ?").bind(id).run();
    return jsonResponse({ success: true, message: "Đã xóa mục hướng dẫn!" });
}

// =============================================================
// PUBLIC RESOURCES & STREAMING DOWNLOAD HANDLERS
// =============================================================
async function handlePublicResources(env) {
    await ensureExtraTables(env);
    const filesRes = await env.DB.prepare(
        "SELECT id, title, file_name, file_size, version, category, description, storage_type, external_url, download_count, created_at FROM app_files WHERE is_active = 1 ORDER BY id DESC"
    ).all();
    const guidesRes = await env.DB.prepare(
        "SELECT id, title, content, video_url, sort_order, updated_at FROM guides WHERE is_active = 1 ORDER BY sort_order ASC, id ASC"
    ).all();

    return jsonResponse({
        success: true,
        files: filesRes.results || [],
        guides: guidesRes.results || []
    });
}

async function handleDownloadFile(fileId, env, request) {
    if (!env.DB) return new Response("Missing DB binding", { status: 500 });
    await ensureExtraTables(env);

    const { results } = await env.DB.prepare(
        "SELECT * FROM app_files WHERE id = ? AND is_active = 1 LIMIT 1"
    ).bind(fileId).all();

    if (!results || results.length === 0) {
        return new Response("File không tồn tại hoặc đã bị gỡ bỏ.", {
            status: 404,
            headers: { "Content-Type": "text/plain; charset=utf-8" }
        });
    }

    const file = results[0];
    const rangeHeader = request ? request.headers.get("Range") : null;
    if (!rangeHeader && file.category !== "guide_video") {
        env.DB.prepare("UPDATE app_files SET download_count = download_count + 1 WHERE id = ?").bind(file.id).run().catch(() => {});
    }

    if (file.storage_type === "external" && file.external_url) {
        return Response.redirect(file.external_url, 302);
    }

    if (!env.FILES_KV) {
        return new Response("Chưa cấu hình Cloudflare KV (FILES_KV) trên Worker!", { status: 500 });
    }

    const totalChunks = Number(file.chunk_count || 0);
    const totalSize = Number(file.file_size || 0);
    const CHUNK_SIZE = 4 * 1024 * 1024;
    const rawName = (file.file_name || "download.bin").replace(/"/g, "");
    const safeFilename = encodeURIComponent(rawName).replace(/'/g, "%27");
    const isVideo = (file.content_type || "").startsWith("video/") || /\.(mp4|webm|ogg)$/i.test(rawName);
    const dispositionType = isVideo ? "inline" : "attachment";

    if (rangeHeader && totalSize > 0) {
        const m = rangeHeader.match(/bytes=(\d+)-(\d*)/);
        if (m) {
            const start = Math.min(Number(m[1]), totalSize - 1);
            const end = m[2] ? Math.min(Number(m[2]), totalSize - 1) : totalSize - 1;
            const startChunk = Math.floor(start / CHUNK_SIZE);
            const endChunk = Math.floor(end / CHUNK_SIZE);
            let curChunk = startChunk;

            const rangeStream = new ReadableStream({
                async pull(controller) {
                    if (curChunk > endChunk || curChunk >= totalChunks) {
                        controller.close();
                        return;
                    }
                    const chunkIdx = curChunk++;
                    const kvKey = `file_${file.id}_chunk_${chunkIdx}`;
                    const chunkBuf = await env.FILES_KV.get(kvKey, { type: "arrayBuffer" });
                    if (!chunkBuf) {
                        controller.error(new Error("Thiếu dữ liệu chunk: " + kvKey));
                        return;
                    }
                    let u8 = new Uint8Array(chunkBuf);
                    const sliceStart = chunkIdx === startChunk ? (start % CHUNK_SIZE) : 0;
                    const sliceEnd = chunkIdx === endChunk ? ((end % CHUNK_SIZE) + 1) : u8.byteLength;
                    if (sliceStart > 0 || sliceEnd < u8.byteLength) {
                        u8 = u8.slice(sliceStart, sliceEnd);
                    }
                    controller.enqueue(u8);
                }
            });

            return new Response(rangeStream, {
                status: 206,
                headers: {
                    "Content-Type": file.content_type || (isVideo ? "video/mp4" : "application/octet-stream"),
                    "Content-Disposition": `${dispositionType}; filename="${rawName}"; filename*=UTF-8''${safeFilename}`,
                    "Content-Range": `bytes ${start}-${end}/${totalSize}`,
                    "Content-Length": String(end - start + 1),
                    "Accept-Ranges": "bytes",
                    "Cache-Control": "public, max-age=3600",
                    ...CORS_HEADERS
                }
            });
        }
    }

    let currentChunk = 0;

    const stream = new ReadableStream({
        async pull(controller) {
            if (currentChunk >= totalChunks) {
                controller.close();
                return;
            }
            const kvKey = `file_${file.id}_chunk_${currentChunk}`;
            currentChunk++;
            const chunkBuf = await env.FILES_KV.get(kvKey, { type: "arrayBuffer" });
            if (chunkBuf) {
                controller.enqueue(new Uint8Array(chunkBuf));
            } else {
                controller.error(new Error("Thiếu dữ liệu chunk: " + kvKey));
            }
        }
    });

    const headers = {
        "Content-Type": file.content_type || (isVideo ? "video/mp4" : "application/octet-stream"),
        "Content-Disposition": `${dispositionType}; filename="${rawName}"; filename*=UTF-8''${safeFilename}`,
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=3600",
        ...CORS_HEADERS
    };
    if (totalSize > 0) {
        headers["Content-Length"] = String(totalSize);
    }

    return new Response(stream, { status: 200, headers });
}

// =============================================================
// HELPER FUNCTIONS
// =============================================================
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

function formatBytes(bytes) {
    const b = Number(bytes || 0);
    if (b === 0) return "Link Ngoài";
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(b) / Math.log(1024));
    return (b / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 2) + " " + sizes[i];
}

function escapeHtml(str) {
    return String(str || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function extractYoutubeEmbedUrl(url) {
    if (!url) return "";
    const match = url.match(/(?:youtube\.com\/(?:watch\?v=|embed\/|shorts\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})/);
    if (match && match[1]) {
        return `https://www.youtube.com/embed/${match[1]}`;
    }
    return "";
}

// =============================================================
// TRANG CÔNG KHAI: "TẢI VÀ HƯỚNG DẪN" (/tai-va-huong-dan)
// =============================================================
async function renderDownloadAndGuidePage(env, url) {
    await ensureExtraTables(env);
    const filesRes = await env.DB.prepare(
        "SELECT * FROM app_files WHERE is_active = 1 ORDER BY id DESC"
    ).all();
    const guidesRes = await env.DB.prepare(
        "SELECT * FROM guides WHERE is_active = 1 ORDER BY sort_order ASC, id ASC"
    ).all();

    const files = filesRes.results || [];
    const guides = guidesRes.results || [];

    const softwareFiles = files.filter(f => (f.category || "software") === "software");
    const otherFiles = files.filter(f => (f.category || "software") !== "software" && f.category !== "guide_video");

    const latestSoftware = softwareFiles.length > 0 ? softwareFiles[0] : null;
    const olderSoftwares = softwareFiles.length > 1 ? softwareFiles.slice(1) : [];

    const categoryBadge = (cat) => {
        if (cat === "software") return `<span class="badge bg-primary">💿 Phần mềm / Bộ cài</span>`;
        if (cat === "template") return `<span class="badge bg-success">📊 File Excel Mẫu</span>`;
        return `<span class="badge bg-info text-dark">📄 Tài liệu</span>`;
    };

    const getDownloadHref = (f) => `/download/file/${f.id}`;

    let heroHtml = "";
    if (latestSoftware) {
        heroHtml = `
        <div class="hero-card p-4 p-md-5 mb-5">
            <div class="row align-items-center g-4">
                <div class="col-lg-8">
                    <div class="d-flex flex-wrap align-items-center gap-2 mb-3">
                        <span class="badge bg-primary px-3 py-2 fs-6">⭐ PHIÊN BẢN MỚI NHẤT</span>
                        ${latestSoftware.version ? `<span class="badge bg-success px-3 py-2 fs-6">${escapeHtml(latestSoftware.version)}</span>` : ""}
                        <span class="badge bg-dark border border-secondary px-3 py-2">${formatBytes(latestSoftware.file_size)}</span>
                    </div>
                    <h2 class="fw-bold text-white mb-2">${escapeHtml(latestSoftware.title)}</h2>
                    <p class="text-light opacity-75 mb-3" style="font-size: 1.05rem;">
                        ${escapeHtml(latestSoftware.description || "Bộ cài đặt chính thức Tools Marketing & Auto Post tự động hóa Facebook, Threads.")}
                    </p>
                    <div class="text-secondary small">
                        📁 Tên tệp: <code class="text-info">${escapeHtml(latestSoftware.file_name)}</code>
                        &nbsp;|&nbsp; 📥 Lượt tải: <strong class="text-white">${latestSoftware.download_count || 0}</strong>
                        &nbsp;|&nbsp; 🕒 Cập nhật: ${escapeHtml((latestSoftware.created_at || "").slice(0, 16))}
                    </div>
                </div>
                <div class="col-lg-4 text-lg-end">
                    <a href="${getDownloadHref(latestSoftware)}" class="btn btn-download btn-lg w-100 py-3 fw-bold shadow-lg">
                        📥 TẢI XUỐNG NGAY
                    </a>
                    <div class="text-center text-secondary small mt-2">
                        💻 Chỉ cần máy tính / laptop • Windows 10/11 (64-bit), RAM tối thiểu 4GB
                    </div>
                </div>
            </div>
        </div>`;
    } else {
        heroHtml = `
        <div class="hero-card p-4 p-md-5 mb-5 text-center">
            <h3 class="text-white fw-bold mb-2">🚀 Kho Tải Phần Mềm & Tài Liệu Auto Post</h3>
            <p class="text-secondary mb-0">Admin hiện chưa upload bộ cài đặt nào. Vui lòng truy cập trang Quản trị để tải file lên!</p>
        </div>`;
    }

    const secondaryFiles = [...olderSoftwares, ...otherFiles];
    let filesGridHtml = "";
    if (secondaryFiles.length > 0) {
        filesGridHtml = `
        <section id="tai-lieu" class="mb-5">
            <h4 class="fw-bold text-white mb-3">📦 Các Phiên Bản & Tài Liệu Kèm Theo</h4>
            <div class="row g-3">
                ${secondaryFiles.map(f => `
                <div class="col-md-6">
                    <div class="card p-3 h-100 d-flex flex-column justify-content-between">
                        <div>
                            <div class="d-flex justify-content-between align-items-start mb-2">
                                ${categoryBadge(f.category)}
                                ${f.version ? `<span class="badge bg-secondary">${escapeHtml(f.version)}</span>` : ""}
                            </div>
                            <h5 class="fw-bold text-white mb-1">${escapeHtml(f.title)}</h5>
                            <p class="text-secondary small mb-2">${escapeHtml(f.description || f.file_name)}</p>
                        </div>
                        <div class="d-flex justify-content-between align-items-center pt-2 border-top border-secondary border-opacity-25 mt-2">
                            <div class="small text-secondary">
                                ${formatBytes(f.file_size)} • 📥 ${f.download_count || 0} lượt tải
                            </div>
                            <a href="${getDownloadHref(f)}" class="btn btn-sm btn-outline-info fw-semibold">
                                📥 Tải Về
                            </a>
                        </div>
                    </div>
                </div>`).join("")}
            </div>
        </section>`;
    }

    const formatGuideContent = (text) => {
        let safe = escapeHtml(text);
        safe = safe.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" class="text-info text-decoration-underline">$1</a>');
        return safe.replace(/\n/g, "<br>");
    };

    let guidesHtml = "";
    if (guides.length > 0) {
        guidesHtml = guides.map((g, idx) => {
            const embedUrl = extractYoutubeEmbedUrl(g.video_url);
            const isDirectMp4 = g.video_url && (/\.(mp4|webm|ogg)(\?.*)?$/i.test(g.video_url) || g.video_url.includes("/download/file/") || g.video_url.includes("/api/files/download/"));
            let videoBlock = "";
            if (embedUrl) {
                videoBlock = `
                <div class="ratio ratio-16x9 mt-3 rounded overflow-hidden border border-secondary border-opacity-25">
                    <iframe src="${embedUrl}" title="${escapeHtml(g.title)}" allowfullscreen></iframe>
                </div>`;
            } else if (isDirectMp4) {
                videoBlock = `
                <div class="mt-3 rounded overflow-hidden border border-secondary border-opacity-25 bg-black">
                    <video controls playsinline preload="metadata" style="width:100%;max-height:480px;display:block;">
                        <source src="${escapeHtml(g.video_url)}" type="video/mp4">
                        Trình duyệt của bạn không hỗ trợ phát video trực tiếp.
                    </video>
                </div>`;
            } else if (g.video_url) {
                videoBlock = `
                <div class="mt-3">
                    <a href="${escapeHtml(g.video_url)}" target="_blank" class="btn btn-sm btn-outline-danger">
                        ▶️ Xem Video Hướng Dẫn
                    </a>
                </div>`;
            }

            return `
            <div class="card p-4 mb-3 guide-card">
                <div class="d-flex align-items-center gap-3 mb-2">
                    <span class="step-badge">${idx + 1}</span>
                    <h5 class="fw-bold text-white mb-0">${escapeHtml(g.title)}</h5>
                </div>
                <div class="guide-body text-light opacity-90 ps-md-5">
                    ${formatGuideContent(g.content)}
                    ${videoBlock}
                </div>
            </div>`;
        }).join("");
    } else {
        guidesHtml = `<div class="card p-4 text-center text-secondary">Chưa có nội dung hướng dẫn.</div>`;
    }

    const html = `<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tải & Hướng Dẫn Sử Dụng - Tools Marketing / Auto Post</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {
            background: radial-gradient(circle at top right, #172554 0%, #0b0f19 45%, #070a12 100%);
            color: #e2e8f0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            min-height: 100vh;
        }
        .navbar-custom {
            background: rgba(17, 24, 39, 0.85);
            backdrop-filter: blur(10px);
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        }
        .hero-card {
            background: linear-gradient(135deg, rgba(30, 58, 138, 0.45) 0%, rgba(17, 24, 39, 0.95) 100%);
            border: 1px solid rgba(59, 130, 246, 0.4);
            border-radius: 16px;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
        }
        .card {
            background-color: #111827;
            border: 1px solid #1f2937;
            border-radius: 12px;
        }
        .guide-card {
            transition: border-color 0.2s ease;
        }
        .guide-card:hover {
            border-color: #3b82f6;
        }
        .btn-download {
            background: linear-gradient(90deg, #2563eb 0%, #06b6d4 100%);
            border: none;
            color: #ffffff;
            border-radius: 12px;
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }
        .btn-download:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 25px rgba(37, 99, 235, 0.5);
            color: #ffffff;
        }
        .step-badge {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 34px;
            height: 34px;
            border-radius: 50%;
            background: linear-gradient(135deg, #3b82f6, #2563eb);
            color: #fff;
            font-weight: 700;
            flex-shrink: 0;
        }
        .guide-body {
            line-height: 1.7;
            font-size: 0.98rem;
        }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark navbar-custom sticky-top py-3">
        <div class="container" style="max-width: 1100px;">
            <a class="navbar-brand fw-bold d-flex align-items-center gap-2" href="/tai-va-huong-dan">
                <span>⚡</span>
                <span>Tools Marketing & Auto Post</span>
            </a>
            <div class="d-flex align-items-center gap-2">
                <a href="#tai-phan-mem" class="btn btn-sm btn-outline-light">📥 Tải Về</a>
                <a href="#huong-dan" class="btn btn-sm btn-outline-info">📖 Hướng Dẫn</a>
            </div>
        </div>
    </nav>

    <main class="container py-5" style="max-width: 1100px;">
        <section id="tai-phan-mem">
            <div class="text-center mb-4">
                <div class="d-inline-flex align-items-center gap-2 px-4 py-2 rounded-pill mb-3 shadow-lg" style="background: linear-gradient(90deg, #16a34a 0%, #eab308 100%); color: #052e16; font-weight: 800; font-size: 1.15rem; letter-spacing: 0.4px; border: 2px solid #fde047;">
                    <span>🎁 DÙNG THỬ FREE 5 NGÀY</span>
                    <span style="opacity: 0.75;">•</span>
                    <span>TỰ ĐỘNG KÍCH HOẠT KHI CÀI ĐẶT</span>
                </div>
                <h1 class="fw-bold text-white display-6 mb-2">Tiết kiệm thời gian làm affiliate chỉ với <span style="color: #fde047;">149k/tháng</span></h1>
                <p class="text-info fw-semibold fs-5 mb-2">Tự động đăng bài Group Facebook, Threads • Nhận phát triển tools theo yêu cầu</p>
                <p class="text-light opacity-90 small mb-0">💻 <strong>Chỉ cần máy tính / laptop</strong> (Cấu hình tối thiểu: Windows 10/11 64-bit, RAM 4GB, CPU 2 nhân, ổ trống ~500MB)</p>
            </div>
            ${heroHtml}
        </section>

        <section id="lien-he-zalo" class="mb-5">
            <div class="card p-4" style="background: linear-gradient(135deg, rgba(6, 78, 59, 0.35) 0%, rgba(17, 24, 39, 0.96) 100%); border: 1px solid rgba(16, 185, 129, 0.45);">
                <div class="d-flex flex-wrap align-items-center justify-content-between gap-2 mb-3">
                    <div>
                        <div class="d-flex align-items-center gap-2 mb-1">
                            <span class="badge bg-success px-3 py-2">💬 HỖ TRỢ & CẤP KEY BẢN QUYỀN</span>
                            <span class="badge bg-dark border border-success text-success px-3 py-2">Chỉ 149k/tháng</span>
                        </div>
                        <h4 class="fw-bold text-white mb-0">Liên Hệ Zalo Quản Trị Viên</h4>
                    </div>
                    <div class="text-light opacity-75 small">
                        Quét mã QR hoặc bấm nút bên dưới để nhắn Zalo kích hoạt bản quyền / đặt làm tools theo yêu cầu.
                    </div>
                </div>
                <div class="row g-4">
                    <div class="col-md-6">
                        <div class="p-3 rounded-3 h-100 text-center" style="background: rgba(15, 23, 42, 0.72); border: 1px solid rgba(52, 211, 153, 0.3);">
                            <div class="badge bg-primary mb-2 px-3 py-1">Admin 1 • Hỗ Trợ Chính</div>
                            <h5 class="fw-bold text-info mb-3">Zalo: 0963913615</h5>
                            <div class="d-inline-block bg-white p-3 rounded-3 shadow mb-3">
                                <div id="zaloQrCode1" style="width:160px;height:160px;display:flex;align-items:center;justify-content:center;"></div>
                            </div>
                            <div class="d-flex justify-content-center flex-wrap gap-2">
                                <a href="https://zalo.me/0963913615" target="_blank" rel="noopener" class="btn btn-success btn-sm fw-bold px-3 py-2">
                                    💬 Nhắn Zalo (0963913615)
                                </a>
                                <button type="button" class="btn btn-outline-light btn-sm px-3 py-2" onclick="navigator.clipboard.writeText('0963913615').then(() => alert('Đã copy số Zalo: 0963913615'))">
                                    📋 Copy SĐT
                                </button>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="p-3 rounded-3 h-100 text-center" style="background: rgba(15, 23, 42, 0.72); border: 1px solid rgba(52, 211, 153, 0.3);">
                            <div class="badge bg-info text-dark mb-2 px-3 py-1">Admin 2 • Kỹ Thuật & Cấp Key</div>
                            <h5 class="fw-bold text-info mb-3">Zalo: 0373253745</h5>
                            <div class="d-inline-block bg-white p-3 rounded-3 shadow mb-3">
                                <div id="zaloQrCode2" style="width:160px;height:160px;display:flex;align-items:center;justify-content:center;"></div>
                            </div>
                            <div class="d-flex justify-content-center flex-wrap gap-2">
                                <a href="https://zalo.me/0373253745" target="_blank" rel="noopener" class="btn btn-success btn-sm fw-bold px-3 py-2">
                                    💬 Nhắn Zalo (0373253745)
                                </a>
                                <button type="button" class="btn btn-outline-light btn-sm px-3 py-2" onclick="navigator.clipboard.writeText('0373253745').then(() => alert('Đã copy số Zalo: 0373253745'))">
                                    📋 Copy SĐT
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </section>

        ${filesGridHtml}

        <section id="huong-dan" class="mb-5">
            <div class="d-flex align-items-center justify-content-between mb-3">
                <h4 class="fw-bold text-white mb-0">📖 Hướng Dẫn Cài Đặt & Sử Dụng Chi Tiết</h4>
                <span class="badge bg-dark border border-secondary text-info">${guides.length} bước hướng dẫn</span>
            </div>
            ${guidesHtml}
        </section>

        <footer class="text-center text-secondary small pt-4 border-top border-secondary border-opacity-25">
            © 2026 Tools Marketing Platform • Zalo Admin: 0963913615 &amp; 0373253745 • Hệ thống phân phối bản quyền & tài liệu chính thức
        </footer>
    </main>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>
    <script>
        (function() {
            const items = [
                { id: 'zaloQrCode1', phone: '0963913615', url: 'https://zalo.me/0963913615' },
                { id: 'zaloQrCode2', phone: '0373253745', url: 'https://zalo.me/0373253745' }
            ];
            items.forEach(function(item) {
                const box = document.getElementById(item.id);
                if (!box) return;
                if (typeof QRCode !== 'undefined') {
                    new QRCode(box, {
                        text: item.url,
                        width: 160,
                        height: 160,
                        colorDark: '#0f172a',
                        colorLight: '#ffffff',
                        correctLevel: QRCode.CorrectLevel.M
                    });
                } else {
                    box.innerHTML = '<img src="https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=' + encodeURIComponent(item.url) + '" alt="QR Zalo ' + item.phone + '" width="160" height="160" style="display:block;">';
                }
            });
        })();
    </script>
</body>
</html>`;

    return new Response(html, {
        headers: { "Content-Type": "text/html; charset=utf-8" }
    });
}

// =============================================================
// TRANG QUẢN TRỊ ADMIN (KEY + UPLOAD FILE + HƯỚNG DẪN)
// =============================================================
function renderAdminWebPage(env) {
    const html = `<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Quản Trị Hệ Thống - Tools Marketing (Cloudflare D1 & KV)</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #0b0f19; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        .card { background-color: #111827; border: 1px solid #1f2937; color: #e2e8f0; border-radius: 10px; }
        .table {
            --bs-table-bg: #0f172a;
            --bs-table-striped-bg: #162033;
            --bs-table-hover-bg: #1e293b;
            --bs-table-color: #f1f5f9;
            --bs-table-hover-color: #ffffff;
            --bs-table-border-color: #273449;
            color: #f1f5f9;
            border-color: #273449;
        }
        .table > :not(caption) > * > * {
            background-color: var(--bs-table-bg) !important;
            color: #f1f5f9 !important;
            border-bottom-color: #273449 !important;
        }
        .table-hover > tbody > tr:hover > * {
            background-color: #1e293b !important;
            color: #ffffff !important;
        }
        .table-dark th, .table thead th {
            background-color: #1e293b !important;
            color: #f8fafc !important;
            border-color: #334155 !important;
        }
        .badge-active { background-color: #059669; }
        .badge-blocked { background-color: #dc2626; }
        .badge-expired { background-color: #d97706; }
        .badge-pending { background-color: #eab308; color: #000000; }
        .btn-primary { background-color: #2563eb; border: none; }
        .form-control, .form-select { background-color: #1f2937; border-color: #374151; color: #f9fafb; }
        .form-control:focus, .form-select:focus { background-color: #1f2937; color: #ffffff; border-color: #3b82f6; }
        .nav-tabs { border-bottom-color: #1f2937; }
        .nav-tabs .nav-link { color: #94a3b8; border: none; padding: 10px 18px; font-weight: 600; border-radius: 8px 8px 0 0; }
        .nav-tabs .nav-link:hover { color: #f8fafc; background-color: rgba(255,255,255,0.05); }
        .nav-tabs .nav-link.active { color: #60a5fa; background-color: #111827; border-bottom: 2px solid #3b82f6; }
        .drop-zone {
            border: 2px dashed #374151;
            border-radius: 12px;
            padding: 28px;
            text-align: center;
            cursor: pointer;
            transition: border-color 0.2s, background-color 0.2s;
            background-color: #0f172a;
        }
        .drop-zone:hover, .drop-zone.dragover {
            border-color: #3b82f6;
            background-color: rgba(37, 99, 235, 0.08);
        }
    </style>
</head>
<body class="p-3 p-md-4">
    <div class="container-fluid" style="max-width: 1320px;">
        <!-- Header -->
        <div class="d-flex flex-wrap justify-content-between align-items-center gap-3 mb-4">
            <div>
                <h3 class="fw-bold text-white mb-1">⚡ Quản Trị Hệ Thống Tools Marketing</h3>
                <p class="text-secondary mb-0">Cloudflare D1 (Key & Hướng dẫn) + Cloudflare KV (Lưu trữ File tốc độ cao)</p>
            </div>
            <div class="d-flex flex-wrap align-items-center gap-2">
                <span id="statText" class="badge bg-dark border border-secondary p-2">Đang tải dữ liệu...</span>
                <a href="/tai-va-huong-dan" target="_blank" class="btn btn-outline-info">📖 Mở Trang Tải & Hướng Dẫn</a>
                <button class="btn btn-outline-secondary" onclick="copyGuideUrl()">🔗 Copy Link Trang Tải</button>
                <button class="btn btn-outline-light" onclick="reloadCurrentTab()">🔄 Làm Mới</button>
            </div>
        </div>

        <!-- Tabs Navigation -->
        <ul class="nav nav-tabs mb-3" id="adminTabs" role="tablist">
            <li class="nav-item">
                <button class="nav-link active" id="tab-keys-btn" data-bs-toggle="tab" data-bs-target="#tab-keys" type="button" onclick="loadData()">
                    🔑 Quản Lý Key Bản Quyền
                </button>
            </li>
            <li class="nav-item">
                <button class="nav-link" id="tab-files-btn" data-bs-toggle="tab" data-bs-target="#tab-files" type="button" onclick="loadFiles()">
                    📦 Upload File & Tài Liệu
                </button>
            </li>
            <li class="nav-item">
                <button class="nav-link" id="tab-guides-btn" data-bs-toggle="tab" data-bs-target="#tab-guides" type="button" onclick="loadGuides()">
                    📖 Nội Dung Hướng Dẫn
                </button>
            </li>
            <li class="nav-item">
                <button class="nav-link" id="tab-revenue-btn" data-bs-toggle="tab" data-bs-target="#tab-revenue" type="button" onclick="loadRevenueData()">
                    📊 Doanh Thu &amp; Giao Dịch
                </button>
            </li>
            <li class="nav-item">
                <button class="nav-link" id="tab-sepay-btn" data-bs-toggle="tab" data-bs-target="#tab-sepay" type="button" onclick="loadSepayData()">
                    💳 SePay, Email &amp; Sale/Voucher
                </button>
            </li>
        </ul>

        <!-- Tab Content -->
        <div class="tab-content">
            <!-- TAB 1: QUẢN LÝ KEY -->
            <div class="tab-pane fade show active" id="tab-keys">
                <div class="d-flex justify-content-end mb-3">
                    <button class="btn btn-primary" onclick="openModalCreate()">➕ Thêm Key Mới</button>
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

            <!-- TAB 2: UPLOAD FILE & QUẢN LÝ TÀI LIỆU -->
            <div class="tab-pane fade" id="tab-files">
                <div class="row g-4 mb-4">
                    <!-- Upload trực tiếp lên Cloudflare KV -->
                    <div class="col-lg-7">
                        <div class="card p-4 h-100">
                            <h5 class="fw-bold text-white mb-3">📤 Upload File Trực Tiếp (EXE, ZIP, XLSX, PDF...)</h5>
                            <div class="drop-zone mb-3" id="dropZone" onclick="document.getElementById('fileInput').click()">
                                <input type="file" id="fileInput" class="d-none" onchange="onFileSelected(this.files[0])">
                                <div class="fs-4 mb-1">📁</div>
                                <div class="fw-semibold text-white" id="selectedFileLabel">Kéo thả file vào đây hoặc Bấm để chọn File</div>
                                <small class="text-secondary">Hỗ trợ file lớn (tự động chia nhỏ 4MB/chunk lên Cloudflare KV - tốc độ cao)</small>
                            </div>
                            <div class="row g-2 mb-2">
                                <div class="col-md-6">
                                    <label class="form-label small mb-1">Tên hiển thị:</label>
                                    <input type="text" id="upTitle" class="form-control form-control-sm" placeholder="VD: Bộ cài Auto Post v1.0">
                                </div>
                                <div class="col-md-3">
                                    <label class="form-label small mb-1">Phiên bản:</label>
                                    <input type="text" id="upVersion" class="form-control form-control-sm" placeholder="VD: v1.0">
                                </div>
                                <div class="col-md-3">
                                    <label class="form-label small mb-1">Phân loại:</label>
                                    <select id="upCategory" class="form-select form-select-sm">
                                        <option value="software">Phần mềm / Bộ cài</option>
                                        <option value="template">File Excel mẫu</option>
                                        <option value="guide">Tài liệu PDF/Doc</option>
                                    </select>
                                </div>
                            </div>
                            <div class="mb-3">
                                <label class="form-label small mb-1">Mô tả ngắn:</label>
                                <input type="text" id="upDesc" class="form-control form-control-sm" placeholder="Mô tả thay đổi hoặc hướng dẫn ngắn...">
                            </div>
                            <div class="progress mb-2 d-none" id="uploadProgressWrap" style="height: 22px; background-color: #1f2937;">
                                <div class="progress-bar progress-bar-striped progress-bar-animated bg-success fw-bold" id="uploadProgressBar" style="width: 0%">0%</div>
                            </div>
                            <div id="uploadStatusText" class="small text-info mb-2"></div>
                            <button class="btn btn-primary w-100 fw-semibold" id="btnStartUpload" onclick="startChunkedUpload()">
                                🚀 Bắt Đầu Upload File
                            </button>
                        </div>
                    </div>

                    <!-- Thêm Link tải ngoài -->
                    <div class="col-lg-5">
                        <div class="card p-4 h-100">
                            <h5 class="fw-bold text-white mb-3">🔗 Hoặc Thêm Link Tải Ngoài (Drive / GitHub...)</h5>
                            <div class="mb-2">
                                <label class="form-label small mb-1">Tên hiển thị:</label>
                                <input type="text" id="extTitle" class="form-control form-control-sm" placeholder="VD: File cài đặt Google Drive">
                            </div>
                            <div class="row g-2 mb-2">
                                <div class="col-6">
                                    <label class="form-label small mb-1">Phiên bản:</label>
                                    <input type="text" id="extVersion" class="form-control form-control-sm" placeholder="v1.0">
                                </div>
                                <div class="col-6">
                                    <label class="form-label small mb-1">Phân loại:</label>
                                    <select id="extCategory" class="form-select form-select-sm">
                                        <option value="software">Phần mềm / Bộ cài</option>
                                        <option value="template">File Excel mẫu</option>
                                        <option value="guide">Tài liệu PDF/Doc</option>
                                    </select>
                                </div>
                            </div>
                            <div class="mb-2">
                                <label class="form-label small mb-1">URL tải xuống:</label>
                                <input type="url" id="extUrl" class="form-control form-control-sm" placeholder="https://drive.google.com/...">
                            </div>
                            <div class="mb-3">
                                <label class="form-label small mb-1">Mô tả ngắn:</label>
                                <input type="text" id="extDesc" class="form-control form-control-sm" placeholder="Link dự phòng tải nhanh...">
                            </div>
                            <button class="btn btn-outline-info w-100 mt-auto fw-semibold" onclick="saveExternalLink()">
                                💾 Lưu Link Tải Ngoài
                            </button>
                        </div>
                    </div>
                </div>

                <!-- Danh sách File đã tải lên -->
                <div class="card shadow-sm">
                    <div class="card-header border-secondary d-flex justify-content-between align-items-center">
                        <h6 class="mb-0 text-white fw-bold">📂 Danh Sách File Đã Upload & Tài Liệu</h6>
                        <span class="small text-secondary" id="filesCountBadge">0 file</span>
                    </div>
                    <div class="table-responsive">
                        <table class="table table-hover align-middle mb-0">
                            <thead class="table-dark">
                                <tr>
                                    <th>ID</th>
                                    <th>Tên Hiển Thị & Mô Tả</th>
                                    <th>Tên Tệp / Nguồn</th>
                                    <th>Phân Loại</th>
                                    <th>Phiên Bản</th>
                                    <th>Dung Lượng</th>
                                    <th>Lượt Tải</th>
                                    <th class="text-center">Thao Tác</th>
                                </tr>
                            </thead>
                            <tbody id="filesTableBody">
                                <tr><td colspan="8" class="text-center py-4">Bấm tab để tải danh sách file...</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- TAB 3: QUẢN LÝ NỘI DUNG HƯỚNG DẪN -->
            <div class="tab-pane fade" id="tab-guides">
                <div class="d-flex justify-content-between align-items-center mb-3">
                    <div class="text-secondary small">Các bước này sẽ tự động hiển thị trên trang công khai <a href="/tai-va-huong-dan" target="_blank" class="text-info">/tai-va-huong-dan</a></div>
                    <button class="btn btn-primary" onclick="openGuideModal()">➕ Thêm Mục Hướng Dẫn</button>
                </div>
                <div class="card shadow-sm">
                    <div class="table-responsive">
                        <table class="table table-hover align-middle mb-0">
                            <thead class="table-dark">
                                <tr>
                                    <th style="width: 70px;">Thứ Tự</th>
                                    <th>Tiêu Đề Bước Hướng Dẫn</th>
                                    <th>Nội Dung Chi Tiết</th>
                                    <th>Video Hướng Dẫn</th>
                                    <th class="text-center" style="width: 150px;">Thao Tác</th>
                                </tr>
                            </thead>
                            <tbody id="guidesTableBody">
                                <tr><td colspan="5" class="text-center py-4">Bấm tab để tải hướng dẫn...</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- TAB 4: DASHBOARD DOANH THU & LỊCH SỬ GIAO DỊCH -->
            <div class="tab-pane fade" id="tab-revenue">
                <div class="row g-3 mb-4">
                    <div class="col-md-3">
                        <div class="card p-3" style="border-left: 4px solid #10b981;">
                            <div class="small text-secondary">Doanh Thu Hôm Nay</div>
                            <h4 class="fw-bold text-success mb-0 mt-1" id="revToday">0đ</h4>
                            <small class="text-secondary" id="revTodayCount">0 đơn</small>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card p-3" style="border-left: 4px solid #3b82f6;">
                            <div class="small text-secondary">Doanh Thu Tháng Này</div>
                            <h4 class="fw-bold text-info mb-0 mt-1" id="revMonth">0đ</h4>
                            <small class="text-secondary" id="revMonthCount">0 đơn</small>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card p-3" style="border-left: 4px solid #f59e0b;">
                            <div class="small text-secondary">Tổng Doanh Thu</div>
                            <h4 class="fw-bold text-warning mb-0 mt-1" id="revTotal">0đ</h4>
                            <small class="text-secondary" id="revTotalCount">0 đơn thành công</small>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card p-3" style="border-left: 4px solid #a855f7;">
                            <div class="small text-secondary">Tổng Tiền Giảm (Sale/Voucher)</div>
                            <h4 class="fw-bold text-white mb-0 mt-1" id="revDiscount">0đ</h4>
                            <small class="text-secondary" id="revPendingCount">0 đơn đang chờ</small>
                        </div>
                    </div>
                </div>

                <div class="card shadow-sm">
                    <div class="card-header border-secondary d-flex flex-wrap justify-content-between align-items-center gap-2">
                        <h6 class="mb-0 text-white fw-bold">📜 Lịch Sử Giao Dịch Thanh Toán SePay</h6>
                        <div class="d-flex flex-wrap gap-2">
                            <select id="revStatusFilter" class="form-select form-select-sm" style="width:160px;" onchange="renderRevenueTable()">
                                <option value="ALL">Tất cả trạng thái</option>
                                <option value="PAID">Đã thanh toán (PAID)</option>
                                <option value="PENDING">Đang chờ (PENDING)</option>
                            </select>
                            <button class="btn btn-sm btn-outline-light" onclick="loadRevenueData()">🔄 Tải Lại</button>
                            <button class="btn btn-sm btn-outline-danger" onclick="resetRevenueData()">🗑️ Reset Doanh Thu về 0</button>
                        </div>
                    </div>
                    <div class="table-responsive">
                        <table class="table table-hover align-middle mb-0">
                            <thead class="table-dark">
                                <tr>
                                    <th>Mã Đơn</th>
                                    <th>Mã Máy</th>
                                    <th>Gói</th>
                                    <th>Giá Gốc</th>
                                    <th>Voucher / Giảm</th>
                                    <th>Thực Thu</th>
                                    <th>Trạng Thái</th>
                                    <th>Mã GD SePay</th>
                                    <th>Thời Gian</th>
                                </tr>
                            </thead>
                            <tbody id="revenueOrdersBody">
                                <tr><td colspan="9" class="text-center py-4">Bấm tab để tải lịch sử giao dịch...</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- TAB 5: CẤU HÌNH SEPAY, EMAIL, SALE & VOUCHER -->
            <div class="tab-pane fade" id="tab-sepay">
                <div class="row g-4 mb-4">
                    <div class="col-lg-6">
                        <div class="card p-4 h-100">
                            <h5 class="text-white fw-bold mb-3">🏦 Cấu Hình Tài Khoản Nhận Tiền &amp; Sale %</h5>
                            <div class="row g-3">
                                <div class="col-md-6">
                                    <label class="form-label small">Mã Ngân Hàng (VD: BIDV, MB, VCB):</label>
                                    <input type="text" id="spBankCode" class="form-control" placeholder="VD: BIDV">
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label small">Số Tài Khoản (hoặc số VA BIDV):</label>
                                    <input type="text" id="spBankAccount" class="form-control" placeholder="VD: 96247...">
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label small">Tên Chủ Tài Khoản:</label>
                                    <input type="text" id="spBankOwner" class="form-control" placeholder="VD: DANG VAN MANH">
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label small">SePay Webhook API Key (tùy chọn):</label>
                                    <input type="text" id="spApiKey" class="form-control" placeholder="Để trống nếu không dùng">
                                </div>
                                <div class="col-md-4">
                                    <label class="form-label small">Giá 1 Tháng (30 ngày):</label>
                                    <input type="number" id="spPrice1m" class="form-control" value="149000">
                                </div>
                                <div class="col-md-4">
                                    <label class="form-label small">Giá 3 Tháng (90 ngày):</label>
                                    <input type="number" id="spPrice3m" class="form-control" value="399000">
                                </div>
                                <div class="col-md-4">
                                    <label class="form-label small">Giá 1 Năm (365 ngày):</label>
                                    <input type="number" id="spPrice1y" class="form-control" value="1290000">
                                </div>
                                <div class="col-md-4">
                                    <label class="form-label small text-warning fw-bold">🔥 Sale % Toàn Hệ Thống (0-90):</label>
                                    <input type="number" id="spSalePercent" class="form-control" min="0" max="90" value="0">
                                </div>
                                <div class="col-md-8">
                                    <label class="form-label small text-warning fw-bold">Nhãn Sale hiển thị (VD: Flash Sale -20%):</label>
                                    <input type="text" id="spSaleLabel" class="form-control" placeholder="VD: Ưu đãi hôm nay">
                                </div>
                                <div class="col-12">
                                    <label class="form-label small">🔗 Webhook URL dán vào SePay:</label>
                                    <div class="input-group">
                                        <input type="text" id="spWebhookUrl" class="form-control font-monospace text-info" readonly>
                                        <button class="btn btn-outline-info" onclick="navigator.clipboard.writeText(document.getElementById('spWebhookUrl').value).then(() => alert('Đã copy Webhook URL!'))">📋 Copy</button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div class="col-lg-6">
                        <div class="card p-4 h-100">
                            <h5 class="text-white fw-bold mb-3">📧 Cấu Hình Email SMTP &amp; Người Nhận Thông Báo</h5>
                            <div class="row g-3">
                                <div class="col-md-6">
                                    <label class="form-label small">Gmail SMTP Gửi Đi:</label>
                                    <input type="email" id="spSmtpUser" class="form-control" value="dangxuanmanh3105@gmail.com">
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label small">App Password (16 ký tự):</label>
                                    <input type="text" id="spSmtpPass" class="form-control" value="senh eotx snse hquh">
                                </div>
                                <div class="col-12">
                                    <label class="form-label small">Danh sách Email nhận thông báo khi có thanh toán mới (<strong>mỗi email 1 dòng</strong>):</label>
                                    <textarea id="spNotifyEmails" class="form-control font-monospace" rows="4" placeholder="email1@gmail.com&#10;email2@gmail.com"></textarea>
                                </div>
                                <div class="col-md-7">
                                    <button class="btn btn-primary w-100 fw-bold" onclick="saveSepaySettings()">💾 Lưu Tất Cả Cấu Hình SePay &amp; Email</button>
                                </div>
                                <div class="col-md-5">
                                    <button class="btn btn-outline-success w-100 fw-bold" onclick="sendTestEmail()">✉️ Gửi Email Thử</button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- QUẢN LÝ VOUCHER -->
                <div class="card p-4 mb-4">
                    <h5 class="text-white fw-bold mb-3">🎟️ Quản Lý Mã Giảm Giá (Voucher)</h5>
                    <div class="row g-2 align-items-end mb-3">
                        <div class="col-md-3">
                            <label class="form-label small">Mã Voucher (VD: VIP20):</label>
                            <input type="text" id="vcCode" class="form-control text-uppercase" placeholder="VD: SALE20">
                        </div>
                        <div class="col-md-2">
                            <label class="form-label small">Loại giảm:</label>
                            <select id="vcType" class="form-select">
                                <option value="percent">Theo %</option>
                                <option value="fixed">Số tiền (VNĐ)</option>
                            </select>
                        </div>
                        <div class="col-md-2">
                            <label class="form-label small">Giá trị (% hoặc đ):</label>
                            <input type="number" id="vcValue" class="form-control" placeholder="20">
                        </div>
                        <div class="col-md-2">
                            <label class="form-label small">Giới hạn lượt (0=∞):</label>
                            <input type="number" id="vcMaxUses" class="form-control" value="0">
                        </div>
                        <div class="col-md-2">
                            <label class="form-label small">Hạn dùng (tùy chọn):</label>
                            <input type="date" id="vcExpires" class="form-control">
                        </div>
                        <div class="col-md-1">
                            <button class="btn btn-success w-100 fw-bold" onclick="saveVoucher()">➕ Tạo</button>
                        </div>
                    </div>
                    <div class="table-responsive">
                        <table class="table table-hover align-middle mb-0">
                            <thead class="table-dark">
                                <tr>
                                    <th>Mã Voucher</th>
                                    <th>Giảm Giá</th>
                                    <th>Đã Dùng / Tối Đa</th>
                                    <th>Hạn Sử Dụng</th>
                                    <th>Trạng Thái</th>
                                    <th class="text-center">Thao Tác</th>
                                </tr>
                            </thead>
                            <tbody id="vouchersTableBody">
                                <tr><td colspan="6" class="text-center py-3">Đang tải voucher...</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
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
                            <option value="PENDING">PENDING (Chờ kích hoạt)</option>
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

    <!-- Modal Sửa Thông Tin File -->
    <div class="modal fade" id="fileEditModal" tabindex="-1">
        <div class="modal-dialog">
            <div class="modal-content card">
                <div class="modal-header border-secondary">
                    <h5 class="modal-title text-white">Chỉnh Sửa Thông Tin File</h5>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
                    <input type="hidden" id="efId">
                    <input type="hidden" id="efStorageType">
                    <div class="mb-3">
                        <label class="form-label">Tên hiển thị:</label>
                        <input type="text" id="efTitle" class="form-control">
                    </div>
                    <div class="row g-2 mb-3">
                        <div class="col-6">
                            <label class="form-label">Phiên bản:</label>
                            <input type="text" id="efVersion" class="form-control">
                        </div>
                        <div class="col-6">
                            <label class="form-label">Phân loại:</label>
                            <select id="efCategory" class="form-select">
                                <option value="software">Phần mềm / Bộ cài</option>
                                <option value="template">File Excel mẫu</option>
                                <option value="guide">Tài liệu PDF/Doc</option>
                            </select>
                        </div>
                    </div>
                    <div class="mb-3" id="efExternalWrap">
                        <label class="form-label">Link tải ngoài:</label>
                        <input type="url" id="efExternalUrl" class="form-control">
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Thay thế tệp mới (tùy chọn - giữ nguyên lượt tải):</label>
                        <input type="file" id="efReplaceFile" class="form-control">
                        <div class="form-text text-secondary" id="efCurrentFileHint"></div>
                        <div id="efProgressWrap" class="mt-2" style="display:none;">
                            <div class="progress" style="height: 18px; background-color: #1f2937;">
                                <div id="efProgressBar" class="progress-bar progress-bar-striped progress-bar-animated bg-info" style="width:0%">0%</div>
                            </div>
                            <small id="efProgressText" class="text-info d-block mt-1"></small>
                        </div>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Mô tả:</label>
                        <textarea id="efDesc" class="form-control" rows="3"></textarea>
                    </div>
                </div>
                <div class="modal-footer border-secondary">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Hủy</button>
                    <button type="button" class="btn btn-primary" id="btnSubmitEditFile" onclick="submitEditFile()">💾 Lưu Thay Đổi</button>
                </div>
            </div>
        </div>
    </div>

    <!-- Modal Thêm/Sửa Hướng Dẫn -->
    <div class="modal fade" id="guideModal" tabindex="-1">
        <div class="modal-dialog modal-lg">
            <div class="modal-content card">
                <div class="modal-header border-secondary">
                    <h5 class="modal-title text-white" id="guideModalTitle">Thêm Mục Hướng Dẫn</h5>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
                    <input type="hidden" id="gId">
                    <div class="row g-2 mb-3">
                        <div class="col-md-9">
                            <label class="form-label">Tiêu đề bước hướng dẫn:</label>
                            <input type="text" id="gTitle" class="form-control" placeholder="VD: Bước 1: Tải và cài đặt Auto Post">
                        </div>
                        <div class="col-md-3">
                            <label class="form-label">Thứ tự hiển thị:</label>
                            <input type="number" id="gOrder" class="form-control" value="1">
                        </div>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Link Video Hướng Dẫn (YouTube / Google Drive hoặc link MP4):</label>
                        <input type="text" id="gVideo" class="form-control mb-2" placeholder="https://www.youtube.com/watch?v=... hoặc tự điền sau khi upload MP4">
                        <div class="d-flex flex-wrap align-items-center gap-2">
                            <input type="file" id="gVideoFile" class="form-control form-control-sm" accept="video/mp4,.mp4,video/webm" style="max-width: 360px;">
                            <button type="button" class="btn btn-sm btn-outline-info" id="gVideoUploadBtn" onclick="uploadGuideMp4()">⬆️ Upload Video MP4 lên Web</button>
                        </div>
                        <div id="gVideoProgressBox" class="mt-2 d-none">
                            <div class="progress" style="height: 8px;">
                                <div id="gVideoProgressBar" class="progress-bar bg-info progress-bar-striped progress-bar-animated" style="width: 0%;"></div>
                            </div>
                            <small id="gVideoProgressText" class="text-info d-block mt-1"></small>
                        </div>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Nội dung hướng dẫn chi tiết:</label>
                        <textarea id="gContent" class="form-control" rows="7" placeholder="Nhập các bước thao tác chi tiết..."></textarea>
                    </div>
                </div>
                <div class="modal-footer border-secondary">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Hủy</button>
                    <button type="button" class="btn btn-primary" onclick="saveGuide()">💾 Lưu Hướng Dẫn</button>
                </div>
            </div>
        </div>
    </div>

    <!-- Modal Đổi Máy (Bắt buộc nhập Mã Máy Mới) -->
    <div class="modal fade" id="changeMachineModal" tabindex="-1">
        <div class="modal-dialog">
            <div class="modal-content card">
                <div class="modal-header border-secondary">
                    <h5 class="modal-title text-white">🔄 Đổi Máy Cho Key Bản Quyền</h5>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
                    <input type="hidden" id="cmId">
                    <div class="mb-2">
                        <small class="text-secondary">Key bản quyền:</small>
                        <div id="cmKeyText" class="fw-bold text-info" style="font-family: monospace;"></div>
                    </div>
                    <div class="mb-3">
                        <small class="text-secondary">Mã máy hiện tại:</small>
                        <div id="cmOldMachine" class="text-warning" style="font-family: monospace;"></div>
                    </div>
                    <div class="mb-2">
                        <label class="form-label fw-bold text-white">Nhập Mã Máy Mới (Bắt buộc) <span class="text-danger">*</span></label>
                        <input type="text" id="cmNewMachine" class="form-control" placeholder="VD: CWAI-XXXX-XXXX-XXXX-XXXX" style="font-family: monospace; text-transform: uppercase;">
                        <small class="text-secondary">Phải nhập mã máy mới của khách hàng vào đây thì hệ thống mới cho phép đổi.</small>
                    </div>
                </div>
                <div class="modal-footer border-secondary">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Hủy</button>
                    <button type="button" class="btn btn-warning fw-bold" onclick="submitChangeMachine()">🔄 Xác Nhận Đổi Máy</button>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        let modalInstance = null;
        let fileEditModalInstance = null;
        let guideModalInstance = null;
        let changeMachineModalInstance = null;
        let selectedUploadFile = null;
        let cachedLicenses = [];
        let cachedFiles = [];
        let cachedGuides = [];

        function escHtml(s) {
            return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        }

        let adminKey = 'admin123';

        function reloadCurrentTab() {
            loadData();
            loadFiles();
            loadGuides();
        }

        function copyGuideUrl() {
            const url = window.location.origin + '/tai-va-huong-dan';
            navigator.clipboard.writeText(url).then(() => {
                alert('Đã copy link Trang Tải & Hướng Dẫn:\\n' + url);
            });
        }

        // ==================== LICENSE KEYS ====================
        async function loadData() {
            const tbody = document.getElementById('licenseTableBody');
            tbody.innerHTML = '<tr><td colspan="8" class="text-center py-4">Đang tải dữ liệu từ D1...</td></tr>';
            try {
                const res = await fetch('/api/admin/list', {
                    headers: { 'X-Admin-Key': adminKey }
                });
                if (res.status === 401) {
                    tbody.innerHTML = '<tr><td colspan="8" class="text-center text-danger py-4">❌ Mật khẩu Admin chưa đúng! Hãy nhập mật khẩu ở ô trên rồi bấm Xác Nhận.</td></tr>';
                    return;
                }
                const json = await res.json();
                const list = json.data || [];
                cachedLicenses = list;
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
                    else if (item.status === 'PENDING') badgeClass = 'badge-pending';

                    const boundMac = item.machine_id ? escHtml(item.machine_id) : '<span class="text-muted fst-italic">Chưa gắn máy</span>';
                    const isPendingRow = item.status === 'PENDING' || item.expiry_date === 'PENDING';
                    html += \`<tr>
                        <td>\${item.id}</td>
                        <td class="fw-bold text-info">\${escHtml(item.license_key)}</td>
                        <td>
                            <div class="fw-semibold text-white">\${escHtml(item.customer_name || 'Khách lẻ')}</div>
                            <small class="text-muted">\${escHtml(item.note || '')}</small>
                        </td>
                        <td><small style="font-family: monospace;">\${boundMac}</small></td>
                        <td><span class="badge bg-secondary">\${escHtml(item.expiry_date)}</span></td>
                        <td><span class="badge \${badgeClass}">\${escHtml(item.status)}</span></td>
                        <td><small class="text-muted">\${escHtml(item.last_verified_at || '--')}</small></td>
                        <td class="text-center">
                            \${isPendingRow ? \`<button class="btn btn-sm btn-success me-1" onclick="quickActivate(\${item.id}, 30)" title="Kích hoạt nhanh 30 ngày">⚡ 30N</button>\` : ''}
                            \${isPendingRow ? \`<button class="btn btn-sm btn-primary me-1" onclick="quickActivate(\${item.id}, 'LIFETIME')" title="Kích hoạt vĩnh viễn">⚡ VV</button>\` : ''}
                            <button class="btn btn-sm btn-outline-info me-1" onclick="editItemById(\${item.id})">Sửa</button>
                            <button class="btn btn-sm btn-outline-warning me-1" onclick="openChangeMachineModal(\${item.id})" title="Nhập mã máy mới để đổi máy">Đổi Máy</button>
                            <button class="btn btn-sm btn-outline-danger" onclick="deleteItem(\${item.id})">Xóa</button>
                        </td>
                    </tr>\`;
                }
                tbody.innerHTML = html;
            } catch (e) {
                tbody.innerHTML = '<tr><td colspan="8" class="text-center text-danger py-4">Lỗi kết nối: ' + e.message + '</td></tr>';
            }
        }

        async function quickActivate(id, days) {
            const item = cachedLicenses.find(x => x.id === id);
            if (!item) return;
            let expiry = 'LIFETIME';
            if (days !== 'LIFETIME') {
                const d = new Date();
                d.setDate(d.getDate() + parseInt(days));
                expiry = d.toISOString().slice(0, 10);
            }
            const res = await fetch('/api/admin/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey },
                body: JSON.stringify({
                    id: item.id,
                    license_key: item.license_key,
                    customer_name: item.customer_name || '',
                    expiry_date: expiry,
                    machine_id: item.machine_id || '',
                    status: 'ACTIVE',
                    note: item.note || ''
                })
            });
            const j = await res.json();
            if (j.success) loadData();
            else alert(j.error || 'Lỗi kích hoạt nhanh!');
        }

        function editItemById(id) {
            const item = cachedLicenses.find(x => x.id === id);
            if (item) editItem(item);
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

        function openChangeMachineModal(id) {
            const item = cachedLicenses.find(x => x.id === id);
            if (!item) return;
            document.getElementById('cmId').value = item.id;
            document.getElementById('cmKeyText').innerText = item.license_key || '';
            document.getElementById('cmOldMachine').innerText = item.machine_id || '(Chưa gắn máy)';
            document.getElementById('cmNewMachine').value = '';
            if (!changeMachineModalInstance) changeMachineModalInstance = new bootstrap.Modal(document.getElementById('changeMachineModal'));
            changeMachineModalInstance.show();
        }

        async function submitChangeMachine() {
            const id = document.getElementById('cmId').value;
            const newMachineId = document.getElementById('cmNewMachine').value.trim().toUpperCase();
            if (!newMachineId) {
                alert('Vui lòng nhập Mã Máy Mới thì mới cho phép đổi máy!');
                document.getElementById('cmNewMachine').focus();
                return;
            }
            const res = await fetch('/api/admin/reset-machine', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey },
                body: JSON.stringify({ id: Number(id), new_machine_id: newMachineId })
            });
            const j = await res.json();
            if (!res.ok || !j.success) {
                alert(j.error || 'Lỗi khi đổi máy!');
                return;
            }
            if (changeMachineModalInstance) changeMachineModalInstance.hide();
            loadData();
        }

        async function deleteItem(id) {
            if (!confirm('Bạn có chắc muốn xóa Key này không?')) return;
            await fetch('/api/admin/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey },
                body: JSON.stringify({ id })
            });
            loadData();
        }

        function generateRandomKey() {
            const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
            let p1 = '', p2 = '', p3 = '';
            for (let i = 0; i < 4; i++) p1 += chars.charAt(Math.floor(Math.random() * chars.length));
            for (let i = 0; i < 4; i++) p2 += chars.charAt(Math.floor(Math.random() * chars.length));
            for (let i = 0; i < 4; i++) p3 += chars.charAt(Math.floor(Math.random() * chars.length));
            document.getElementById('mKey').value = 'CWAI-' + p1 + '-' + p2 + '-' + p3;
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

        // ==================== FILE UPLOAD & RESOURCES ====================
        const dropZone = document.getElementById('dropZone');
        dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
        dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            if (e.dataTransfer.files && e.dataTransfer.files[0]) {
                onFileSelected(e.dataTransfer.files[0]);
            }
        });

        function formatFileSizeJS(bytes) {
            if (!bytes || bytes === 0) return 'Link Ngoài';
            const k = 1024, sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return (bytes / Math.pow(k, i)).toFixed(i === 0 ? 0 : 2) + ' ' + sizes[i];
        }

        function onFileSelected(file) {
            if (!file) return;
            selectedUploadFile = file;
            document.getElementById('selectedFileLabel').innerText = file.name + ' (' + formatFileSizeJS(file.size) + ')';
            if (!document.getElementById('upTitle').value.trim()) {
                document.getElementById('upTitle').value = file.name.replace(/\\.[^/.]+$/, '');
            }
        }

        async function startChunkedUpload() {
            if (!selectedUploadFile) {
                alert('Vui lòng chọn file cần upload!');
                return;
            }
            const title = document.getElementById('upTitle').value.trim() || selectedUploadFile.name;
            const version = document.getElementById('upVersion').value.trim();
            const category = document.getElementById('upCategory').value;
            const description = document.getElementById('upDesc').value.trim();

            const CHUNK_SIZE = 4 * 1024 * 1024; // 4MB mỗi chunk
            const totalChunks = Math.ceil(selectedUploadFile.size / CHUNK_SIZE);

            const btn = document.getElementById('btnStartUpload');
            const progWrap = document.getElementById('uploadProgressWrap');
            const progBar = document.getElementById('uploadProgressBar');
            const statusText = document.getElementById('uploadStatusText');

            btn.disabled = true;
            progWrap.classList.remove('d-none');
            progBar.style.width = '0%';
            progBar.innerText = '0%';
            statusText.innerText = 'Đang khởi tạo phiên upload trên Cloudflare...';

            try {
                // 1. Init
                const initRes = await fetch('/api/admin/files/init', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey },
                    body: JSON.stringify({
                        title,
                        file_name: selectedUploadFile.name,
                        file_size: selectedUploadFile.size,
                        version,
                        category,
                        description,
                        content_type: selectedUploadFile.type || 'application/octet-stream',
                        chunk_count: totalChunks
                    })
                });
                const initJson = await initRes.json();
                if (!initRes.ok || !initJson.success) {
                    throw new Error(initJson.error || 'Lỗi khởi tạo upload (kiểm tra mật khẩu Admin hoặc KV Binding)');
                }
                const fileId = initJson.file_id;

                // 2. Upload chunks
                for (let i = 0; i < totalChunks; i++) {
                    const start = i * CHUNK_SIZE;
                    const end = Math.min(selectedUploadFile.size, start + CHUNK_SIZE);
                    const blob = selectedUploadFile.slice(start, end);

                    statusText.innerText = \`Đang tải lên phần \${i + 1}/\${totalChunks} (\${formatFileSizeJS(end)} / \${formatFileSizeJS(selectedUploadFile.size)})...\`;
                    const chunkRes = await fetch(\`/api/admin/files/chunk?file_id=\${fileId}&chunk_index=\${i}\`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/octet-stream', 'X-Admin-Key': adminKey },
                        body: blob
                    });
                    if (!chunkRes.ok) {
                        const errJ = await chunkRes.json().catch(() => ({}));
                        throw new Error(errJ.error || 'Lỗi khi đẩy dữ liệu phần ' + (i + 1));
                    }

                    const pct = Math.round(((i + 1) / totalChunks) * 100);
                    progBar.style.width = pct + '%';
                    progBar.innerText = pct + '%';
                }

                // 3. Complete
                statusText.innerText = 'Đang hoàn tất lưu file...';
                await fetch('/api/admin/files/complete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey },
                    body: JSON.stringify({ file_id: fileId })
                });

                statusText.innerHTML = '<span class="text-success fw-bold">✅ Upload file thành công!</span>';
                selectedUploadFile = null;
                document.getElementById('fileInput').value = '';
                document.getElementById('selectedFileLabel').innerText = 'Kéo thả file vào đây hoặc Bấm để chọn File';
                document.getElementById('upTitle').value = '';
                document.getElementById('upDesc').value = '';
                loadFiles();
            } catch (err) {
                statusText.innerHTML = '<span class="text-danger fw-bold">❌ Thất bại: ' + err.message + '</span>';
            } finally {
                btn.disabled = false;
            }
        }

        async function saveExternalLink() {
            const data = {
                title: document.getElementById('extTitle').value.trim(),
                version: document.getElementById('extVersion').value.trim(),
                category: document.getElementById('extCategory').value,
                external_url: document.getElementById('extUrl').value.trim(),
                description: document.getElementById('extDesc').value.trim()
            };
            if (!data.title || !data.external_url) {
                alert('Vui lòng nhập Tên hiển thị và URL tải xuống!');
                return;
            }
            const res = await fetch('/api/admin/files/save-link', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey },
                body: JSON.stringify(data)
            });
            const j = await res.json();
            if (j.success) {
                document.getElementById('extTitle').value = '';
                document.getElementById('extUrl').value = '';
                document.getElementById('extDesc').value = '';
                loadFiles();
            } else {
                alert(j.error || 'Lỗi khi lưu link!');
            }
        }

        async function loadFiles() {
            const tbody = document.getElementById('filesTableBody');
            try {
                const res = await fetch('/api/admin/files/list', {
                    headers: { 'X-Admin-Key': adminKey }
                });
                if (res.status === 401) {
                    tbody.innerHTML = '<tr><td colspan="8" class="text-center text-danger py-4">❌ Sai mật khẩu Admin!</td></tr>';
                    return;
                }
                const j = await res.json();
                const list = j.data || [];
                cachedFiles = list;
                document.getElementById('filesCountBadge').innerText = list.length + ' file';
                if (list.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="8" class="text-center py-4 text-secondary">Chưa có file nào được upload.</td></tr>';
                    return;
                }
                const catMap = { software: 'Phần mềm', template: 'Excel Mẫu', guide: 'Tài liệu' };
                tbody.innerHTML = list.map(f => {
                    const dlUrl = window.location.origin + '/download/file/' + f.id;
                    const srcInfo = f.storage_type === 'external'
                        ? \`<small class="text-warning">🔗 Link ngoài</small><br><small class="text-muted text-truncate d-inline-block" style="max-width:180px;">\${escHtml(f.external_url)}</small>\`
                        : \`<span class="text-info">\${escHtml(f.file_name)}</span><br><small class="text-muted">☁️ Cloudflare KV (\${f.chunk_count} phần)</small>\`;
                    return \`<tr>
                        <td>\${f.id}</td>
                        <td>
                            <div class="fw-semibold text-white">\${escHtml(f.title)} \${f.is_active ? '' : '<span class="badge bg-warning text-dark">Đang upload</span>'}</div>
                            <small class="text-secondary">\${escHtml(f.description || '')}</small>
                        </td>
                        <td>\${srcInfo}</td>
                        <td><span class="badge bg-dark border border-secondary">\${catMap[f.category] || escHtml(f.category)}</span></td>
                        <td>\${f.version ? \`<span class="badge bg-primary">\${escHtml(f.version)}</span>\` : '--'}</td>
                        <td>\${formatFileSizeJS(f.file_size)}</td>
                        <td><span class="badge bg-secondary">\${f.download_count || 0}</span></td>
                        <td class="text-center">
                            <a href="/download/file/\${f.id}" class="btn btn-sm btn-outline-success me-1" target="_blank">Tải</a>
                            <button class="btn btn-sm btn-outline-secondary me-1" onclick="copyText('\${dlUrl}')">Copy</button>
                            <button class="btn btn-sm btn-outline-info me-1" onclick="openEditFileById(\${f.id})">Sửa</button>
                            <button class="btn btn-sm btn-outline-danger" onclick="deleteFile(\${f.id})">Xóa</button>
                        </td>
                    </tr>\`;
                }).join('');
            } catch (e) {
                tbody.innerHTML = '<tr><td colspan="8" class="text-center text-danger py-4">Lỗi: ' + e.message + '</td></tr>';
            }
        }

        function openEditFileById(id) {
            const f = cachedFiles.find(x => x.id === id);
            if (f) openEditFile(f);
        }

        function copyText(txt) {
            navigator.clipboard.writeText(txt).then(() => alert('Đã copy link tải trực tiếp:\\n' + txt));
        }

        function openEditFile(f) {
            document.getElementById('efId').value = f.id;
            document.getElementById('efStorageType').value = f.storage_type;
            document.getElementById('efTitle').value = f.title || '';
            document.getElementById('efVersion').value = f.version || '';
            document.getElementById('efCategory').value = f.category || 'software';
            document.getElementById('efExternalUrl').value = f.external_url || '';
            document.getElementById('efDesc').value = f.description || '';
            document.getElementById('efReplaceFile').value = '';
            document.getElementById('efCurrentFileHint').textContent = 'Tệp hiện tại: ' + (f.file_name || '--');
            document.getElementById('efProgressWrap').style.display = 'none';
            document.getElementById('efProgressBar').style.width = '0%';
            document.getElementById('efProgressBar').textContent = '0%';
            document.getElementById('efProgressText').textContent = '';
            document.getElementById('btnSubmitEditFile').disabled = false;
            document.getElementById('efExternalWrap').style.display = f.storage_type === 'external' ? 'block' : 'none';
            if (!fileEditModalInstance) fileEditModalInstance = new bootstrap.Modal(document.getElementById('fileEditModal'));
            fileEditModalInstance.show();
        }

        async function submitEditFile() {
            const id = parseInt(document.getElementById('efId').value);
            const title = document.getElementById('efTitle').value.trim();
            const version = document.getElementById('efVersion').value.trim();
            const category = document.getElementById('efCategory').value;
            const external_url = document.getElementById('efExternalUrl').value.trim();
            const description = document.getElementById('efDesc').value.trim();
            const replaceInput = document.getElementById('efReplaceFile');
            const newFile = replaceInput && replaceInput.files ? replaceInput.files[0] : null;
            const btn = document.getElementById('btnSubmitEditFile');

            if (!title) {
                alert('Vui lòng nhập Tên hiển thị!');
                return;
            }

            if (newFile) {
                const CHUNK_SIZE = 4 * 1024 * 1024;
                const totalChunks = Math.ceil(newFile.size / CHUNK_SIZE) || 1;
                const progWrap = document.getElementById('efProgressWrap');
                const progBar = document.getElementById('efProgressBar');
                const progText = document.getElementById('efProgressText');
                progWrap.style.display = 'block';
                btn.disabled = true;

                try {
                    progText.textContent = 'Đang khởi tạo thay thế file trên Cloudflare...';
                    const initRes = await fetch('/api/admin/files/init', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey },
                        body: JSON.stringify({
                            replace_id: id,
                            title: title,
                            file_name: newFile.name,
                            file_size: newFile.size,
                            version: version,
                            category: category,
                            description: description,
                            content_type: newFile.type || 'application/octet-stream',
                            chunk_count: totalChunks
                        })
                    });
                    const initJson = await initRes.json();
                    if (!initJson.success) throw new Error(initJson.error || 'Lỗi khởi tạo thay thế file');

                    for (let i = 0; i < totalChunks; i++) {
                        const start = i * CHUNK_SIZE;
                        const end = Math.min(start + CHUNK_SIZE, newFile.size);
                        const slice = newFile.slice(start, end);
                        progText.textContent = \`Đang tải lên phần \${i + 1}/\${totalChunks} (\${newFile.name})...\`;

                        const chunkRes = await fetch(\`/api/admin/files/chunk?file_id=\${id}&chunk_index=\${i}\`, {
                            method: 'POST',
                            headers: { 'X-Admin-Key': adminKey },
                            body: slice
                        });
                        const chunkJson = await chunkRes.json();
                        if (!chunkJson.success) throw new Error(chunkJson.error || \`Lỗi upload phần \${i + 1}\`);

                        const pct = Math.round(((i + 1) / totalChunks) * 100);
                        progBar.style.width = pct + '%';
                        progBar.textContent = pct + '%';
                    }

                    await fetch('/api/admin/files/complete', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey },
                        body: JSON.stringify({ file_id: id })
                    });

                    if (fileEditModalInstance) fileEditModalInstance.hide();
                    loadFiles();
                    alert('✅ Đã thay thế tệp mới và cập nhật phiên bản thành công!');
                } catch (e) {
                    alert('❌ Lỗi thay thế tệp: ' + e.message);
                } finally {
                    btn.disabled = false;
                }
                return;
            }

            const data = { id, title, version, category, external_url, description };
            const res = await fetch('/api/admin/files/save-link', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey },
                body: JSON.stringify(data)
            });
            const j = await res.json();
            if (j.success) {
                if (fileEditModalInstance) fileEditModalInstance.hide();
                loadFiles();
            } else {
                alert(j.error || 'Lỗi lưu thay đổi!');
            }
        }

        async function deleteFile(id) {
            if (!confirm('Xóa file này sẽ xóa vĩnh viễn dữ liệu trên Cloudflare KV. Bạn chắc chắn?')) return;
            await fetch('/api/admin/files/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey },
                body: JSON.stringify({ id })
            });
            loadFiles();
        }

        // ==================== GUIDES MANAGEMENT ====================
        async function loadGuides() {
            const tbody = document.getElementById('guidesTableBody');
            try {
                const res = await fetch('/api/admin/guides/list', {
                    headers: { 'X-Admin-Key': adminKey }
                });
                if (res.status === 401) {
                    tbody.innerHTML = '<tr><td colspan="5" class="text-center text-danger py-4">❌ Sai mật khẩu Admin!</td></tr>';
                    return;
                }
                const j = await res.json();
                const list = j.data || [];
                cachedGuides = list;
                if (list.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-secondary">Chưa có mục hướng dẫn nào.</td></tr>';
                    return;
                }
                tbody.innerHTML = list.map(g => \`<tr>
                    <td><span class="badge bg-primary">\${g.sort_order}</span></td>
                    <td class="fw-bold text-white">\${escHtml(g.title)}</td>
                    <td><small class="text-secondary">\${escHtml((g.content || '').slice(0, 120))}...</small></td>
                    <td>\${g.video_url ? \`<a href="\${escHtml(g.video_url)}" target="_blank" class="text-info small">▶️ Xem Video</a>\` : '<span class="text-muted">--</span>'}</td>
                    <td class="text-center">
                        <button class="btn btn-sm btn-outline-info me-1" onclick="openGuideModalById(\${g.id})">Sửa</button>
                        <button class="btn btn-sm btn-outline-danger" onclick="deleteGuide(\${g.id})">Xóa</button>
                    </td>
                </tr>\`).join('');
            } catch (e) {
                tbody.innerHTML = '<tr><td colspan="5" class="text-center text-danger py-4">Lỗi: ' + e.message + '</td></tr>';
            }
        }

        function openGuideModalById(id) {
            const g = cachedGuides.find(x => x.id === id);
            if (g) openGuideModal(g);
        }

        function openGuideModal(g = null) {
            document.getElementById('gId').value = g ? g.id : '';
            document.getElementById('guideModalTitle').innerText = g ? 'Sửa Mục Hướng Dẫn #' + g.id : 'Thêm Mục Hướng Dẫn Mới';
            document.getElementById('gTitle').value = g ? g.title : '';
            document.getElementById('gOrder').value = g ? g.sort_order : 1;
            document.getElementById('gVideo').value = g ? (g.video_url || '') : '';
            document.getElementById('gContent').value = g ? (g.content || '') : '';
            const vf = document.getElementById('gVideoFile');
            if (vf) vf.value = '';
            const pb = document.getElementById('gVideoProgressBox');
            if (pb) pb.classList.add('d-none');
            if (!guideModalInstance) guideModalInstance = new bootstrap.Modal(document.getElementById('guideModal'));
            guideModalInstance.show();
        }

        async function uploadGuideMp4() {
            const fileInput = document.getElementById('gVideoFile');
            const file = fileInput && fileInput.files && fileInput.files[0];
            if (!file) {
                alert('Vui lòng chọn file MP4 trước khi upload!');
                return null;
            }
            const btn = document.getElementById('gVideoUploadBtn');
            const pbBox = document.getElementById('gVideoProgressBox');
            const pbBar = document.getElementById('gVideoProgressBar');
            const pbText = document.getElementById('gVideoProgressText');

            btn.disabled = true;
            pbBox.classList.remove('d-none');
            pbBar.style.width = '0%';
            pbText.innerText = 'Đang khởi tạo upload video...';

            try {
                const CHUNK_SIZE = 4 * 1024 * 1024;
                const totalChunks = Math.ceil(file.size / CHUNK_SIZE) || 1;
                const initRes = await fetch('/api/admin/files/init', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey },
                    body: JSON.stringify({
                        title: document.getElementById('gTitle').value.trim() || file.name,
                        file_name: file.name,
                        file_size: file.size,
                        version: '',
                        category: 'guide_video',
                        description: 'Video hướng dẫn nhúng trực tiếp',
                        chunk_count: totalChunks,
                        content_type: file.type || 'video/mp4'
                    })
                });
                const initJson = await initRes.json();
                if (!initRes.ok || !initJson.file_id) {
                    throw new Error(initJson.error || 'Không thể khởi tạo upload video');
                }
                const fileId = initJson.file_id;
                for (let i = 0; i < totalChunks; i++) {
                    const start = i * CHUNK_SIZE;
                    const end = Math.min(start + CHUNK_SIZE, file.size);
                    const blob = file.slice(start, end);
                    const chunkRes = await fetch('/api/admin/files/chunk?file_id=' + fileId + '&chunk_index=' + i, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/octet-stream', 'X-Admin-Key': adminKey },
                        body: blob
                    });
                    if (!chunkRes.ok) throw new Error('Lỗi upload phần ' + (i + 1));
                    const pct = Math.round(((i + 1) / totalChunks) * 100);
                    pbBar.style.width = pct + '%';
                    pbText.innerText = 'Đang upload video: ' + pct + '% (' + (i + 1) + '/' + totalChunks + ')';
                }
                await fetch('/api/admin/files/complete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey },
                    body: JSON.stringify({ file_id: fileId })
                });
                const videoUrl = window.location.origin + '/download/file/' + fileId;
                document.getElementById('gVideo').value = videoUrl;
                fileInput.value = '';
                pbText.innerText = '✅ Upload MP4 hoàn tất! Link video đã được điền tự động.';
                return videoUrl;
            } catch (err) {
                pbText.innerText = '❌ Lỗi: ' + err.message;
                alert('Lỗi upload MP4: ' + err.message);
                return null;
            } finally {
                btn.disabled = false;
            }
        }

        async function saveGuide() {
            const fileInput = document.getElementById('gVideoFile');
            if (fileInput && fileInput.files && fileInput.files[0]) {
                const uploadedUrl = await uploadGuideMp4();
                if (!uploadedUrl) return;
            }
            const id = document.getElementById('gId').value;
            const data = {
                id: id ? parseInt(id) : null,
                title: document.getElementById('gTitle').value.trim(),
                sort_order: parseInt(document.getElementById('gOrder').value || '1'),
                video_url: document.getElementById('gVideo').value.trim(),
                content: document.getElementById('gContent').value.trim()
            };
            if (!data.title || !data.content) {
                alert('Vui lòng nhập đầy đủ tiêu đề và nội dung!');
                return;
            }
            const res = await fetch('/api/admin/guides/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey },
                body: JSON.stringify(data)
            });
            const j = await res.json();
            if (j.success) {
                if (guideModalInstance) guideModalInstance.hide();
                loadGuides();
            } else {
                alert(j.error || 'Lỗi khi lưu hướng dẫn!');
            }
        }

        async function deleteGuide(id) {
            if (!confirm('Bạn có chắc muốn xóa mục hướng dẫn này?')) return;
            await fetch('/api/admin/guides/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey },
                body: JSON.stringify({ id })
            });
            loadGuides();
        }

        // ==================== REVENUE, SEPAY, EMAIL, SALE & VOUCHER ====================
        let cachedOrders = [];

        async function loadRevenueData() {
            const tbody = document.getElementById('revenueOrdersBody');
            try {
                const res = await fetch('/api/admin/revenue/summary', { headers: { 'X-Admin-Key': adminKey } });
                if (res.status === 401) {
                    tbody.innerHTML = '<tr><td colspan="9" class="text-center text-danger py-4">❌ Sai mật khẩu Admin!</td></tr>';
                    return;
                }
                const j = await res.json();
                const st = j.stats || {};
                document.getElementById('revToday').innerText = Number(st.today_revenue || 0).toLocaleString('vi-VN') + 'đ';
                document.getElementById('revTodayCount').innerText = (st.today_count || 0) + ' đơn hôm nay';
                document.getElementById('revMonth').innerText = Number(st.month_revenue || 0).toLocaleString('vi-VN') + 'đ';
                document.getElementById('revMonthCount').innerText = (st.month_count || 0) + ' đơn tháng này';
                document.getElementById('revTotal').innerText = Number(st.total_revenue || 0).toLocaleString('vi-VN') + 'đ';
                document.getElementById('revTotalCount').innerText = (st.total_paid_count || 0) + ' đơn thành công';
                document.getElementById('revDiscount').innerText = Number(st.total_discount || 0).toLocaleString('vi-VN') + 'đ';
                document.getElementById('revPendingCount').innerText = (st.pending_count || 0) + ' đơn đang chờ';

                cachedOrders = j.orders || [];
                renderRevenueTable();
            } catch (e) {
                tbody.innerHTML = '<tr><td colspan="9" class="text-center text-danger py-4">Lỗi: ' + e.message + '</td></tr>';
            }
        }

        async function resetRevenueData() {
            if (!confirm('Bạn có chắc muốn RESET toàn bộ doanh thu và lịch sử giao dịch về 0 không? Hành động này không thể hoàn tác!')) return;
            try {
                const res = await fetch('/api/admin/revenue/reset', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey }
                });
                const j = await res.json();
                if (!res.ok || !j.success) {
                    alert(j.error || 'Lỗi khi reset doanh thu!');
                    return;
                }
                alert(j.message || 'Đã reset doanh thu về 0!');
                loadRevenueData();
            } catch (e) {
                alert('Lỗi kết nối: ' + e.message);
            }
        }

        function renderRevenueTable() {
            const tbody = document.getElementById('revenueOrdersBody');
            const filter = document.getElementById('revStatusFilter').value;
            const list = filter === 'ALL' ? cachedOrders : cachedOrders.filter(o => o.status === filter);
            if (list.length === 0) {
                tbody.innerHTML = '<tr><td colspan="9" class="text-center py-4 text-secondary">Chưa có giao dịch nào.</td></tr>';
                return;
            }
            tbody.innerHTML = list.map(o => {
                const orig = Number(o.original_amount || o.amount || 0);
                const disc = Number(o.discount_amount || 0);
                const vc = o.voucher_code ? \`<span class="badge bg-info text-dark">\${escHtml(o.voucher_code)}</span> \` : '';
                const statusBadge = o.status === 'PAID'
                    ? '<span class="badge bg-success">PAID</span>'
                    : '<span class="badge bg-warning text-dark">PENDING</span>';
                return \`<tr>
                    <td><code class="text-info fw-bold">\${escHtml(o.order_code)}</code></td>
                    <td><code class="text-light">\${escHtml(o.machine_id)}</code></td>
                    <td>+\${o.days_to_add} ngày</td>
                    <td class="text-secondary">\${orig.toLocaleString('vi-VN')}đ</td>
                    <td>\${vc}\${disc > 0 ? \`<span class="text-danger">-\${disc.toLocaleString('vi-VN')}đ</span>\` : '<span class="text-muted">--</span>'}</td>
                    <td class="fw-bold text-warning">\${Number(o.amount || 0).toLocaleString('vi-VN')}đ</td>
                    <td>\${statusBadge}</td>
                    <td class="small text-secondary">\${escHtml(o.sepay_tx_id || '--')}</td>
                    <td class="small">\${o.paid_at ? \`<span class="text-success">\${escHtml(o.paid_at)}</span>\` : \`<span class="text-secondary">\${escHtml(o.created_at || '')}</span>\`}</td>
                </tr>\`;
            }).join('');
        }

        async function loadSepayData() {
            const whEl = document.getElementById('spWebhookUrl');
            if (whEl) whEl.value = window.location.origin + '/api/sepay/webhook';
            try {
                const sRes = await fetch('/api/admin/sepay/settings', { headers: { 'X-Admin-Key': adminKey } });
                if (sRes.ok) {
                    const sj = await sRes.json();
                    const s = sj.data || {};
                    document.getElementById('spBankCode').value = s.bank_code || '';
                    document.getElementById('spBankAccount').value = s.bank_account || '';
                    document.getElementById('spBankOwner').value = s.bank_owner || '';
                    document.getElementById('spApiKey').value = s.sepay_api_key || '';
                    document.getElementById('spPrice1m').value = s.price_1m || '149000';
                    document.getElementById('spPrice3m').value = s.price_3m || '399000';
                    document.getElementById('spPrice1y').value = s.price_1y || '1290000';
                    document.getElementById('spSalePercent').value = s.sale_percent || '0';
                    document.getElementById('spSaleLabel').value = s.sale_label || '';
                    document.getElementById('spSmtpUser').value = s.smtp_user || 'dangxuanmanh3105@gmail.com';
                    document.getElementById('spSmtpPass').value = s.smtp_pass || 'senh eotx snse hquh';
                    document.getElementById('spNotifyEmails').value = s.notify_emails || 'dangxuanmanh3105@gmail.com';
                }
            } catch (e) {}
            loadVouchers();
        }

        async function saveSepaySettings() {
            const data = {
                bank_code: document.getElementById('spBankCode').value.trim().toUpperCase(),
                bank_account: document.getElementById('spBankAccount').value.trim(),
                bank_owner: document.getElementById('spBankOwner').value.trim().toUpperCase(),
                sepay_api_key: document.getElementById('spApiKey').value.trim(),
                price_1m: document.getElementById('spPrice1m').value.trim() || '149000',
                price_3m: document.getElementById('spPrice3m').value.trim() || '399000',
                price_1y: document.getElementById('spPrice1y').value.trim() || '1290000',
                sale_percent: document.getElementById('spSalePercent').value.trim() || '0',
                sale_label: document.getElementById('spSaleLabel').value.trim(),
                smtp_user: document.getElementById('spSmtpUser').value.trim(),
                smtp_pass: document.getElementById('spSmtpPass').value.trim(),
                notify_emails: document.getElementById('spNotifyEmails').value.trim()
            };
            const res = await fetch('/api/admin/sepay/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey },
                body: JSON.stringify(data)
            });
            const j = await res.json();
            if (j.success) {
                alert('✅ Đã lưu cấu hình SePay, Email & Sale thành công!');
            } else {
                alert('❌ ' + (j.error || 'Lỗi lưu cấu hình!'));
            }
        }

        async function sendTestEmail() {
            await saveSepaySettings();
            const res = await fetch('/api/admin/sepay/test-email', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey }
            });
            const j = await res.json();
            if (j.success) {
                alert('✅ ' + (j.message || 'Đã gửi email thử thành công!'));
            } else {
                alert('❌ Lỗi gửi email: ' + (j.error || 'Không rõ lỗi'));
            }
        }

        async function loadVouchers() {
            const tbody = document.getElementById('vouchersTableBody');
            try {
                const res = await fetch('/api/admin/vouchers/list', { headers: { 'X-Admin-Key': adminKey } });
                if (res.status === 401) {
                    tbody.innerHTML = '<tr><td colspan="6" class="text-center text-danger py-3">❌ Sai mật khẩu Admin!</td></tr>';
                    return;
                }
                const j = await res.json();
                const list = j.data || [];
                if (list.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="6" class="text-center py-3 text-secondary">Chưa có mã Voucher nào.</td></tr>';
                    return;
                }
                tbody.innerHTML = list.map(v => \`<tr>
                    <td><code class="text-warning fw-bold fs-6">\${escHtml(v.code)}</code></td>
                    <td>\${v.discount_type === 'percent' ? \`<span class="badge bg-info text-dark">-\${v.discount_value}%</span>\` : \`<span class="badge bg-primary">-\${Number(v.discount_value).toLocaleString('vi-VN')}đ</span>\`}</td>
                    <td>\${v.used_count || 0} / \${v.max_uses > 0 ? v.max_uses : '∞'}</td>
                    <td>\${v.expires_at ? escHtml(v.expires_at) : '<span class="text-secondary">Không giới hạn</span>'}</td>
                    <td>\${v.is_active ? '<span class="badge bg-success">Đang bật</span>' : '<span class="badge bg-secondary">Đã tắt</span>'}</td>
                    <td class="text-center">
                        <button class="btn btn-sm btn-outline-danger" onclick="deleteVoucher(\${v.id})">Xóa</button>
                    </td>
                </tr>\`).join('');
            } catch (e) {
                tbody.innerHTML = '<tr><td colspan="6" class="text-center text-danger py-3">Lỗi: ' + e.message + '</td></tr>';
            }
        }

        async function saveVoucher() {
            const code = document.getElementById('vcCode').value.trim().toUpperCase();
            const discount_type = document.getElementById('vcType').value;
            const discount_value = parseInt(document.getElementById('vcValue').value || '0');
            const max_uses = parseInt(document.getElementById('vcMaxUses').value || '0');
            const expires_at = document.getElementById('vcExpires').value.trim();
            if (!code || discount_value <= 0) {
                alert('Vui lòng nhập Mã Voucher và Giá trị giảm hợp lệ!');
                return;
            }
            const res = await fetch('/api/admin/vouchers/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey },
                body: JSON.stringify({ code, discount_type, discount_value, max_uses, expires_at })
            });
            const j = await res.json();
            if (j.success) {
                document.getElementById('vcCode').value = '';
                document.getElementById('vcValue').value = '';
                loadVouchers();
            } else {
                alert('❌ ' + (j.error || 'Lỗi tạo voucher!'));
            }
        }

        async function deleteVoucher(id) {
            if (!confirm('Xóa mã Voucher này?')) return;
            await fetch('/api/admin/vouchers/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey },
                body: JSON.stringify({ id })
            });
            loadVouchers();
        }

        loadData();
    </script>
</body>
</html>`;
    return new Response(html, {
        headers: { "Content-Type": "text/html; charset=utf-8" }
    });
}

// =============================================================
// RÚT GỌN LINK & CHUYỂN HƯỚNG (/api/shorten & /s/:code)
// =============================================================
async function handleShortenLink(request, env) {
    if (!env.DB) {
        return jsonResponse({ success: false, message: "Chưa cấu hình D1 Database (Binding DB)!" }, 500);
    }
    const body = await request.json().catch(() => ({}));
    let targetUrl = String(body.url || body.target_url || "").trim();
    if (!targetUrl) {
        return jsonResponse({ success: false, message: "Thiếu tham số url!" }, 400);
    }
    if (!targetUrl.startsWith("http://") && !targetUrl.startsWith("https://")) {
        targetUrl = "https://" + targetUrl;
    }

    try {
        await env.DB.prepare(`
            CREATE TABLE IF NOT EXISTS short_links (
                code TEXT PRIMARY KEY,
                target_url TEXT,
                created_at DATETIME,
                click_count INTEGER DEFAULT 0
            )
        `).run();
    } catch (e) {}

    try {
        const { results } = await env.DB.prepare(
            "SELECT code FROM short_links WHERE target_url = ? LIMIT 1"
        ).bind(targetUrl).all();

        if (results && results.length > 0 && results[0].code) {
            const existingCode = results[0].code;
            return jsonResponse({
                success: true,
                code: existingCode,
                short_url: `https://link.truyennha.id.vn/s/${existingCode}`,
                target_url: targetUrl
            });
        }
    } catch (e) {}

    const chars = "abcdefghjkmnpqrstuvwxyz23456789";
    let code = "";
    for (let attempt = 0; attempt < 5; attempt++) {
        let rand = "";
        for (let i = 0; i < 5; i++) {
            rand += chars.charAt(Math.floor(Math.random() * chars.length));
        }
        try {
            const check = await env.DB.prepare(
                "SELECT code FROM short_links WHERE code = ? LIMIT 1"
            ).bind(rand).all();
            if (!check.results || check.results.length === 0) {
                code = rand;
                break;
            }
        } catch (e) {
            code = rand;
            break;
        }
    }
    if (!code) {
        code = Math.random().toString(36).substring(2, 7);
    }

    await env.DB.prepare(
        "INSERT OR REPLACE INTO short_links (code, target_url, created_at, click_count) VALUES (?, ?, datetime('now', '+7 hours'), 0)"
    ).bind(code, targetUrl).run();

    const shortUrl = `https://link.truyennha.id.vn/s/${code}`;
    return jsonResponse({
        success: true,
        code: code,
        short_url: shortUrl,
        target_url: targetUrl
    });
}

async function handleRedirectShortLink(code, env, request) {
    if (!code || !env.DB) {
        return Response.redirect("https://shopee.vn", 302);
    }
    let targetUrl = "https://shopee.vn";
    try {
        const { results } = await env.DB.prepare(
            "SELECT target_url FROM short_links WHERE code = ? LIMIT 1"
        ).bind(code).all();

        if (results && results.length > 0 && results[0].target_url) {
            targetUrl = results[0].target_url;
            env.DB.prepare("UPDATE short_links SET click_count = click_count + 1 WHERE code = ?").bind(code).run().catch(() => {});
        }
    } catch (e) {}

    const userAgent = (request ? request.headers.get("user-agent") : "") || "";
    const isBot = /facebookexternalhit|Facebot|Twitterbot|TelegramBot|WhatsApp/i.test(userAgent);

    if (isBot) {
        const html = `<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="utf-8">
    <title>Sản phẩm chính hãng trên Shopee</title>
    <meta property="og:title" content="Xem chi tiết sản phẩm trên Shopee">
    <meta property="og:description" content="Nhấn vào để xem chi tiết sản phẩm và nhận ưu đãi chính hãng trên Shopee.">
    <meta property="og:type" content="website">
    <meta property="og:url" content="https://link.truyennha.id.vn/s/${code}">
    <meta property="og:site_name" content="Shopee">
    <meta name="robots" content="index, follow">
</head>
<body>
    <p>Đang chuyển hướng tới sản phẩm trên Shopee...</p>
</body>
</html>`;
        return new Response(html, {
            status: 200,
            headers: {
                "Content-Type": "text/html; charset=utf-8",
                "Cache-Control": "public, max-age=86400"
            }
        });
    }

    const redirectHtml = `<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Đang mở Shopee...</title>
    <meta http-equiv="refresh" content="0; url=${targetUrl}">
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; background: #fafafa; color: #333; }
        .box { text-align: center; padding: 20px; }
        .spinner { width: 40px; height: 40px; border: 4px solid #f3f3f3; border-top: 4px solid #ee4d2d; border-radius: 50%; animation: spin 0.8s linear infinite; margin: 0 auto 16px; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        a { color: #ee4d2d; font-weight: bold; text-decoration: none; font-size: 16px; }
    </style>
</head>
<body>
    <div class="box">
        <div class="spinner"></div>
        <p>Đang chuyển đến Shopee...</p>
        <p><a href="${targetUrl}">Bấm vào đây nếu không tự chuyển</a></p>
    </div>
    <script>
        window.location.replace("${targetUrl}");
    </script>
</body>
</html>`;

    return new Response(redirectHtml, {
        status: 200,
        headers: {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-cache, no-store, must-revalidate"
        }
    });
}

// =============================================================
// SEPAY AUTO-RENEWAL & PAYMENT HANDLERS
// =============================================================
async function getSepaySettingsMap(env) {
    await ensureExtraTables(env);
    const { results } = await env.DB.prepare("SELECT key, value FROM app_settings").all();
    const map = {
        bank_code: "",
        bank_account: "",
        bank_owner: "",
        sepay_api_key: "",
        price_1m: "149000",
        price_3m: "399000",
        price_1y: "1290000",
        sale_percent: "0",
        sale_label: "",
        smtp_user: "dangxuanmanh3105@gmail.com",
        smtp_pass: "senh eotx snse hquh",
        notify_emails: "dangxuanmanh3105@gmail.com"
    };
    for (const r of (results || [])) {
        if (r.key) map[r.key] = r.value || "";
    }
    return map;
}

function utf8ToBase64(str) {
    const bytes = new TextEncoder().encode(str);
    let bin = "";
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin);
}

async function sendGmailSmtp({ smtpUser, smtpPass, recipients, subject, htmlBody }) {
    const user = String(smtpUser || "").trim();
    const pass = String(smtpPass || "").replace(/\s+/g, "");
    const list = (recipients || []).map(e => String(e || "").trim()).filter(e => e.includes("@"));
    if (!user || !pass || list.length === 0) {
        return { sent: false, reason: "Thiếu thông tin SMTP hoặc danh sách email nhận!" };
    }

    const socket = connect({ hostname: "smtp.gmail.com", port: 465 }, { secureTransport: "on", allowHalfOpen: false });
    const reader = socket.readable.getReader();
    const writer = socket.writable.getWriter();
    const decoder = new TextDecoder();
    const encoder = new TextEncoder();

    let buf = "";
    const readResp = async () => {
        while (true) {
            const lines = buf.split("\r\n");
            if (lines.length > 1) {
                for (let i = 0; i < lines.length - 1; i++) {
                    if (/^\d{3} /.test(lines[i])) {
                        const full = lines.slice(0, i + 1).join("\r\n");
                        buf = lines.slice(i + 1).join("\r\n");
                        return full;
                    }
                }
            }
            const { value, done } = await reader.read();
            if (done) throw new Error("SMTP connection closed unexpectedly");
            buf += decoder.decode(value, { stream: true });
        }
    };

    const sendCmd = async (cmd, expectedPrefix) => {
        await writer.write(encoder.encode(cmd + "\r\n"));
        const resp = await readResp();
        if (expectedPrefix && !resp.startsWith(expectedPrefix)) {
            throw new Error(`SMTP error (${cmd.split(" ")[0]}): ${resp}`);
        }
        return resp;
    };

    try {
        const greet = await readResp();
        if (!greet.startsWith("220")) throw new Error("SMTP greeting error: " + greet);
        await sendCmd("EHLO link.truyennha.id.vn", "250");
        await sendCmd("AUTH LOGIN", "334");
        await sendCmd(btoa(user), "334");
        await sendCmd(btoa(pass), "235");
        await sendCmd(`MAIL FROM:<${user}>`, "250");
        for (const rcpt of list) {
            await sendCmd(`RCPT TO:<${rcpt}>`, "250");
        }
        await sendCmd("DATA", "354");

        const encodedSubj = `=?UTF-8?B?${utf8ToBase64(subject)}?=`;
        const b64Body = utf8ToBase64(htmlBody).replace(/(.{76})/g, "$1\r\n");
        const message = [
            `From: "Tools Marketing Auto Post" <${user}>`,
            `To: ${list.join(", ")}`,
            `Subject: ${encodedSubj}`,
            `MIME-Version: 1.0`,
            `Content-Type: text/html; charset=UTF-8`,
            `Content-Transfer-Encoding: base64`,
            ``,
            b64Body,
            `.`
        ].join("\r\n");

        await writer.write(encoder.encode(message + "\r\n"));
        const dataResp = await readResp();
        if (!dataResp.startsWith("250")) throw new Error("SMTP DATA error: " + dataResp);
        await sendCmd("QUIT", "221").catch(() => {});
        return { sent: true, count: list.length };
    } finally {
        try { reader.releaseLock(); } catch {}
        try { writer.releaseLock(); } catch {}
        try { await socket.close(); } catch {}
    }
}

async function handleAdminSepaySettings(request, env) {
    if (!checkAdminAuth(request, env)) return jsonResponse({ error: "Unauthorized" }, 401);
    if (request.method === "GET") {
        const data = await getSepaySettingsMap(env);
        return jsonResponse({ success: true, data });
    }
    if (request.method === "POST") {
        await ensureExtraTables(env);
        const body = await request.json().catch(() => ({}));
        const keys = [
            "bank_code", "bank_account", "bank_owner", "sepay_api_key",
            "price_1m", "price_3m", "price_1y",
            "sale_percent", "sale_label",
            "smtp_user", "smtp_pass", "notify_emails"
        ];
        for (const k of keys) {
            if (body[k] !== undefined) {
                await env.DB.prepare(
                    "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value"
                ).bind(k, String(body[k] || "").trim()).run();
            }
        }
        return jsonResponse({ success: true, message: "Đã lưu cấu hình SePay & Email!" });
    }
    return jsonResponse({ error: "Method not allowed" }, 405);
}

async function handleAdminTestEmail(request, env) {
    if (!checkAdminAuth(request, env)) return jsonResponse({ error: "Unauthorized" }, 401);
    const s = await getSepaySettingsMap(env);
    const recipients = String(s.notify_emails || "").split(/\r?\n/).map(x => x.trim()).filter(Boolean);
    try {
        const res = await sendGmailSmtp({
            smtpUser: s.smtp_user,
            smtpPass: s.smtp_pass,
            recipients,
            subject: "[Auto Post] Kiểm tra gửi Email thông báo thanh toán SePay",
            htmlBody: `<div style="font-family:Arial,sans-serif;padding:16px;background:#0f172a;color:#f8fafc;border-radius:8px;">
                <h2 style="color:#34d399;">✅ Kết nối Gmail SMTP thành công!</h2>
                <p>Hệ thống <strong>Tools Marketing &amp; Auto Post</strong> sẽ tự động gửi thông báo về các email này mỗi khi có giao dịch thanh toán SePay thành công.</p>
                <p style="color:#94a3b8;font-size:12px;">Thời gian kiểm tra: ${getVietnamDateString()}</p>
            </div>`
        });
        if (!res.sent) return jsonResponse({ success: false, error: res.reason }, 400);
        return jsonResponse({ success: true, message: `Đã gửi email thử tới ${res.count} địa chỉ!` });
    } catch (e) {
        return jsonResponse({ success: false, error: e.message }, 500);
    }
}

async function handleAdminRevenueReset(request, env) {
    if (!checkAdminAuth(request, env)) return jsonResponse({ error: "Unauthorized" }, 401);
    await ensureExtraTables(env);
    await env.DB.prepare("DELETE FROM payment_orders").run();
    return jsonResponse({ success: true, message: "Đã reset toàn bộ doanh thu và lịch sử giao dịch về 0!" });
}

async function handleAdminRevenueSummary(request, env) {
    if (!checkAdminAuth(request, env)) return jsonResponse({ error: "Unauthorized" }, 401);
    await ensureExtraTables(env);
    const todayIso = getVietnamDateString();
    const monthPrefix = todayIso.slice(0, 7);

    const { results } = await env.DB.prepare("SELECT * FROM payment_orders ORDER BY id DESC LIMIT 200").all();
    const orders = results || [];

    let todayRevenue = 0, todayCount = 0;
    let monthRevenue = 0, monthCount = 0;
    let totalRevenue = 0, totalPaidCount = 0;
    let totalDiscount = 0, pendingCount = 0;

    for (const o of orders) {
        if (o.status === "PAID") {
            const amt = Number(o.amount || 0);
            const disc = Number(o.discount_amount || 0);
            totalRevenue += amt;
            totalDiscount += disc;
            totalPaidCount += 1;
            const paidDate = String(o.paid_at || o.created_at || "").slice(0, 10);
            if (paidDate === todayIso) {
                todayRevenue += amt;
                todayCount += 1;
            }
            if (paidDate.startsWith(monthPrefix)) {
                monthRevenue += amt;
                monthCount += 1;
            }
        } else {
            pendingCount += 1;
        }
    }

    return jsonResponse({
        success: true,
        stats: {
            today_revenue: todayRevenue,
            today_count: todayCount,
            month_revenue: monthRevenue,
            month_count: monthCount,
            total_revenue: totalRevenue,
            total_paid_count: totalPaidCount,
            total_discount: totalDiscount,
            pending_count: pendingCount
        },
        orders
    });
}

async function handleAdminVouchersList(request, env) {
    if (!checkAdminAuth(request, env)) return jsonResponse({ error: "Unauthorized" }, 401);
    await ensureExtraTables(env);
    const { results } = await env.DB.prepare("SELECT * FROM vouchers ORDER BY id DESC").all();
    return jsonResponse({ success: true, data: results || [] });
}

async function handleAdminVouchersSave(request, env) {
    if (!checkAdminAuth(request, env)) return jsonResponse({ error: "Unauthorized" }, 401);
    await ensureExtraTables(env);
    const body = await request.json().catch(() => ({}));
    const code = String(body.code || "").trim().toUpperCase();
    const discountType = body.discount_type === "fixed" ? "fixed" : "percent";
    const discountValue = Number(body.discount_value || 0);
    const maxUses = Number(body.max_uses || 0);
    const expiresAt = String(body.expires_at || "").trim();

    if (!code || discountValue <= 0) {
        return jsonResponse({ success: false, error: "Mã voucher và giá trị giảm không hợp lệ!" }, 400);
    }

    await env.DB.prepare(`
        INSERT INTO vouchers (code, discount_type, discount_value, max_uses, expires_at, is_active)
        VALUES (?, ?, ?, ?, ?, 1)
        ON CONFLICT(code) DO UPDATE SET
            discount_type = excluded.discount_type,
            discount_value = excluded.discount_value,
            max_uses = excluded.max_uses,
            expires_at = excluded.expires_at,
            is_active = 1
    `).bind(code, discountType, discountValue, maxUses, expiresAt).run();

    return jsonResponse({ success: true, message: "Đã lưu mã Voucher!" });
}

async function handleAdminVouchersDelete(request, env) {
    if (!checkAdminAuth(request, env)) return jsonResponse({ error: "Unauthorized" }, 401);
    const body = await request.json().catch(() => ({}));
    if (!body.id) return jsonResponse({ error: "Thiếu id" }, 400);
    await env.DB.prepare("DELETE FROM vouchers WHERE id = ?").bind(body.id).run();
    return jsonResponse({ success: true });
}

async function validateAndComputeOrderPrice(env, s, packageId, voucherCodeRaw) {
    const pkgMap = {
        "1m": { label: "Gói 1 Tháng (30 ngày)", days: 30, base: Number(s.price_1m || 149000) },
        "3m": { label: "Gói 3 Tháng (90 ngày)", days: 90, base: Number(s.price_3m || 399000) },
        "1y": { label: "Gói 1 Năm (365 ngày)", days: 365, base: Number(s.price_1y || 1290000) }
    };
    const pkg = pkgMap[packageId] || pkgMap["1m"];
    const originalAmount = pkg.base;

    const salePercent = Math.min(90, Math.max(0, Number(s.sale_percent || 0)));
    const saleDiscount = Math.round(originalAmount * salePercent / 100);
    let afterSale = Math.max(2000, originalAmount - saleDiscount);

    let voucherDiscount = 0;
    let validVoucherCode = "";
    let voucherMsg = "";

    const vcCode = String(voucherCodeRaw || "").trim().toUpperCase();
    if (vcCode) {
        const vRes = await env.DB.prepare("SELECT * FROM vouchers WHERE code = ? AND is_active = 1 LIMIT 1").bind(vcCode).all();
        if (!vRes.results || vRes.results.length === 0) {
            return { ok: false, error: `Mã giảm giá '${vcCode}' không tồn tại hoặc đã bị tắt!` };
        }
        const v = vRes.results[0];
        const todayIso = getVietnamDateString();
        if (v.expires_at && v.expires_at < todayIso) {
            return { ok: false, error: `Mã giảm giá '${vcCode}' đã hết hạn (${v.expires_at})!` };
        }
        if (Number(v.max_uses || 0) > 0 && Number(v.used_count || 0) >= Number(v.max_uses)) {
            return { ok: false, error: `Mã giảm giá '${vcCode}' đã hết lượt sử dụng!` };
        }
        if (v.discount_type === "percent") {
            const pct = Math.min(90, Math.max(0, Number(v.discount_value || 0)));
            voucherDiscount = Math.round(afterSale * pct / 100);
            voucherMsg = `Áp dụng mã ${vcCode} (-${pct}%) thành công!`;
        } else {
            voucherDiscount = Math.min(afterSale - 2000, Math.max(0, Number(v.discount_value || 0)));
            voucherMsg = `Áp dụng mã ${vcCode} (-${voucherDiscount.toLocaleString("vi-VN")}đ) thành công!`;
        }
        validVoucherCode = vcCode;
    }

    const totalDiscount = saleDiscount + voucherDiscount;
    const finalAmount = Math.max(2000, originalAmount - totalDiscount);

    return {
        ok: true,
        pkg,
        original_amount: originalAmount,
        sale_percent: salePercent,
        sale_discount: saleDiscount,
        voucher_code: validVoucherCode,
        voucher_discount: voucherDiscount,
        total_discount: totalDiscount,
        final_amount: finalAmount,
        voucher_message: voucherMsg
    };
}

async function handleAdminSepayOrders(request, env) {
    if (!checkAdminAuth(request, env)) return jsonResponse({ error: "Unauthorized" }, 401);
    await ensureExtraTables(env);
    const { results } = await env.DB.prepare("SELECT * FROM payment_orders ORDER BY id DESC LIMIT 50").all();
    return jsonResponse({ success: true, data: results || [] });
}

async function handlePaymentPackages(env) {
    const s = await getSepaySettingsMap(env);
    const salePercent = Math.min(90, Math.max(0, Number(s.sale_percent || 0)));
    const calc = (base) => {
        const b = Number(base);
        return salePercent > 0 ? Math.max(2000, Math.round(b * (100 - salePercent) / 100)) : b;
    };
    return jsonResponse({
        success: true,
        configured: Boolean(s.bank_code && s.bank_account),
        sale_percent: salePercent,
        sale_label: s.sale_label || (salePercent > 0 ? `🔥 Đang giảm ${salePercent}%` : ""),
        packages: [
            { id: "1m", label: "Gói 1 Tháng (30 ngày)", days: 30, original_amount: Number(s.price_1m || 149000), amount: calc(s.price_1m || 149000) },
            { id: "3m", label: "Gói 3 Tháng (90 ngày)", days: 90, original_amount: Number(s.price_3m || 399000), amount: calc(s.price_3m || 399000) },
            { id: "1y", label: "Gói 1 Năm (365 ngày)", days: 365, original_amount: Number(s.price_1y || 1290000), amount: calc(s.price_1y || 1290000) }
        ]
    });
}

async function handlePaymentApplyVoucher(request, env) {
    const body = await request.json().catch(() => ({}));
    const packageId = String(body.package_id || "1m").trim();
    const voucherCode = String(body.voucher_code || "").trim().toUpperCase();
    const s = await getSepaySettingsMap(env);
    const calc = await validateAndComputeOrderPrice(env, s, packageId, voucherCode);
    if (!calc.ok) return jsonResponse({ success: false, error: calc.error }, 400);
    return jsonResponse({
        success: true,
        original_amount: calc.original_amount,
        sale_discount: calc.sale_discount,
        voucher_discount: calc.voucher_discount,
        total_discount: calc.total_discount,
        final_amount: calc.final_amount,
        voucher_code: calc.voucher_code,
        message: calc.voucher_message
    });
}

async function handlePaymentCreateOrder(request, env) {
    const body = await request.json().catch(() => ({}));
    const machineId = String(body.machine_id || "").trim();
    const packageId = String(body.package_id || "1m").trim();
    const voucherCode = String(body.voucher_code || "").trim().toUpperCase();
    if (!machineId) return jsonResponse({ success: false, error: "Thiếu machine_id!" }, 400);

    const s = await getSepaySettingsMap(env);
    if (!s.bank_code || !s.bank_account) {
        return jsonResponse({
            success: false,
            error: "Admin chưa cấu hình tài khoản ngân hàng SePay trên Web Admin. Vui lòng liên hệ Zalo Admin để kích hoạt!"
        }, 400);
    }

    const calc = await validateAndComputeOrderPrice(env, s, packageId, voucherCode);
    if (!calc.ok) return jsonResponse({ success: false, error: calc.error }, 400);

    const digits = "0123456789ABCDEFGHJKLMNPQRSTUVWXYZ";
    let randCode = "";
    for (let i = 0; i < 6; i++) randCode += digits.charAt(Math.floor(Math.random() * digits.length));
    const orderCode = `CWAI${randCode}`;

    const licRes = await env.DB.prepare("SELECT license_key FROM licenses WHERE machine_id = ? LIMIT 1").bind(machineId).all();
    const existingKey = (licRes.results && licRes.results[0]) ? licRes.results[0].license_key : "";

    await env.DB.prepare(`
        INSERT INTO payment_orders (order_code, machine_id, license_key, package_id, original_amount, discount_amount, voucher_code, amount, days_to_add, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', datetime('now', '+7 hours'))
    `).bind(orderCode, machineId, existingKey, packageId, calc.original_amount, calc.total_discount, calc.voucher_code, calc.final_amount, calc.pkg.days).run();

    const qrUrl = `https://qr.sepay.vn/img?acc=${encodeURIComponent(s.bank_account)}&bank=${encodeURIComponent(s.bank_code)}&amount=${calc.final_amount}&des=${encodeURIComponent(orderCode)}`;

    return jsonResponse({
        success: true,
        order_code: orderCode,
        original_amount: calc.original_amount,
        discount_amount: calc.total_discount,
        voucher_code: calc.voucher_code,
        amount: calc.final_amount,
        days_to_add: calc.pkg.days,
        package_label: calc.pkg.label,
        bank_code: s.bank_code,
        bank_account: s.bank_account,
        bank_owner: s.bank_owner,
        qr_url: qrUrl
    });
}

async function handlePaymentStatus(request, env) {
    await ensureExtraTables(env);
    const url = new URL(request.url);
    const orderCode = String(url.searchParams.get("order_code") || "").trim().toUpperCase();
    if (!orderCode) return jsonResponse({ success: false, error: "Thiếu order_code!" }, 400);

    const { results } = await env.DB.prepare("SELECT * FROM payment_orders WHERE order_code = ? LIMIT 1").bind(orderCode).all();
    if (!results || results.length === 0) {
        return jsonResponse({ success: false, error: "Không tìm thấy đơn hàng!" }, 404);
    }
    const order = results[0];
    let licenseInfo = null;
    if (order.status === "PAID") {
        const licRes = await env.DB.prepare("SELECT * FROM licenses WHERE machine_id = ? LIMIT 1").bind(order.machine_id).all();
        if (licRes.results && licRes.results[0]) {
            const row = licRes.results[0];
            licenseInfo = {
                valid: true,
                status: row.status,
                license_key: row.license_key,
                machine_id: row.machine_id,
                expiry_raw: row.expiry_date,
                expiry_display: formatDMY(row.expiry_date),
                customer_name: row.customer_name || ""
            };
        }
    }
    return jsonResponse({
        success: true,
        order_code: order.order_code,
        status: order.status,
        amount: order.amount,
        days_to_add: order.days_to_add,
        paid_at: order.paid_at,
        license: licenseInfo
    });
}

async function handleSepayWebhook(request, env) {
    const s = await getSepaySettingsMap(env);
    if (s.sepay_api_key) {
        const auth = request.headers.get("Authorization") || "";
        const token = auth.replace(/^(Apikey|Bearer)\s+/i, "").trim();
        if (token !== s.sepay_api_key) {
            return jsonResponse({ success: false, error: "Invalid SePay API Key" }, 401);
        }
    }

    const body = await request.json().catch(() => ({}));
    if (body.transferType && String(body.transferType).toLowerCase() !== "in") {
        return jsonResponse({ success: true, message: "Ignored outgoing transfer" });
    }

    const content = `${body.code || ""} ${body.content || ""} ${body.description || ""}`.toUpperCase();
    const amount = Number(body.transferAmount || 0);
    const txId = String(body.id || body.referenceCode || "");

    const { results } = await env.DB.prepare("SELECT * FROM payment_orders WHERE status = 'PENDING' ORDER BY id DESC LIMIT 100").all();
    const pendingOrders = results || [];
    const matched = pendingOrders.find(o => content.includes(String(o.order_code || "").toUpperCase()) && amount >= Number(o.amount || 0));

    if (!matched) {
        return jsonResponse({ success: true, message: "No matching pending order" });
    }

    await env.DB.prepare(
        "UPDATE payment_orders SET status = 'PAID', sepay_tx_id = ?, paid_at = datetime('now', '+7 hours') WHERE id = ?"
    ).bind(txId, matched.id).run();

    if (matched.voucher_code) {
        await env.DB.prepare("UPDATE vouchers SET used_count = used_count + 1 WHERE code = ?").bind(matched.voucher_code).run().catch(() => {});
    }

    // Gia hạn hoặc kích hoạt bản quyền cho machine_id
    const todayIso = getVietnamDateString();
    let newExpiryDisplay = "";
    const licRes = await env.DB.prepare("SELECT * FROM licenses WHERE machine_id = ? LIMIT 1").bind(matched.machine_id).all();
    if (licRes.results && licRes.results.length > 0) {
        const row = licRes.results[0];
        const curExp = String(row.expiry_date || "").trim().toUpperCase();
        if (curExp === "LIFETIME") {
            newExpiryDisplay = "Vĩnh viễn";
            await env.DB.prepare("UPDATE licenses SET status = 'ACTIVE', note = ? WHERE id = ?")
                .bind(`Gia hạn SePay ${matched.order_code}`, row.id).run();
        } else {
            const baseDateStr = (curExp >= todayIso && /^\d{4}-\d{2}-\d{2}$/.test(curExp)) ? curExp : todayIso;
            const baseMs = Date.parse(baseDateStr + "T00:00:00Z");
            const newExpiry = new Date(baseMs + Number(matched.days_to_add) * 86400 * 1000).toISOString().slice(0, 10);
            newExpiryDisplay = formatDMY(newExpiry);
            await env.DB.prepare(
                "UPDATE licenses SET expiry_date = ?, status = 'ACTIVE', last_verified_at = datetime('now', '+7 hours'), note = ? WHERE id = ?"
            ).bind(newExpiry, `Gia hạn SePay ${matched.order_code} (+${matched.days_to_add} ngày)`, row.id).run();
        }
    } else {
        const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
        const randPart = () => {
            let str = "";
            for (let i = 0; i < 4; i++) str += chars.charAt(Math.floor(Math.random() * chars.length));
            return str;
        };
        const newKey = `CWAI-${randPart()}-${randPart()}-${randPart()}`;
        const baseMs = Date.parse(todayIso + "T00:00:00Z");
        const newExpiry = new Date(baseMs + Number(matched.days_to_add) * 86400 * 1000).toISOString().slice(0, 10);
        newExpiryDisplay = formatDMY(newExpiry);
        await env.DB.prepare(`
            INSERT INTO licenses (license_key, machine_id, customer_name, expiry_date, status, last_verified_at, note)
            VALUES (?, ?, 'Khách nạp SePay', ?, 'ACTIVE', datetime('now', '+7 hours'), ?)
        `).bind(newKey, matched.machine_id, newExpiry, `Nạp SePay ${matched.order_code} (+${matched.days_to_add} ngày)`).run();
    }

    // Gửi Email thông báo thanh toán mới tới danh sách email cấu hình
    try {
        const recipients = String(s.notify_emails || "").split(/\r?\n/).map(x => x.trim()).filter(Boolean);
        if (recipients.length > 0 && s.smtp_user && s.smtp_pass) {
            const amtFmt = Number(matched.amount || 0).toLocaleString("vi-VN") + "đ";
            await sendGmailSmtp({
                smtpUser: s.smtp_user,
                smtpPass: s.smtp_pass,
                recipients,
                subject: `[Auto Post] Thanh toán mới +${amtFmt} (${matched.order_code})`,
                htmlBody: `<div style="font-family:Arial,sans-serif;padding:18px;background:#0f172a;color:#f8fafc;border-radius:10px;max-width:560px;">
                    <h2 style="color:#34d399;margin-top:0;">💰 Thanh Toán SePay Thành Công!</h2>
                    <table style="width:100%;border-collapse:collapse;color:#e2e8f0;">
                        <tr><td style="padding:6px 0;color:#94a3b8;">Mã đơn:</td><td><strong>${matched.order_code}</strong></td></tr>
                        <tr><td style="padding:6px 0;color:#94a3b8;">Mã máy:</td><td><code>${matched.machine_id}</code></td></tr>
                        <tr><td style="padding:6px 0;color:#94a3b8;">Số tiền thực nhận:</td><td style="color:#fde047;font-weight:bold;">${amtFmt}</td></tr>
                        <tr><td style="padding:6px 0;color:#94a3b8;">Voucher áp dụng:</td><td>${matched.voucher_code || "Không có"}</td></tr>
                        <tr><td style="padding:6px 0;color:#94a3b8;">Cộng thêm:</td><td>+${matched.days_to_add} ngày (Hạn mới: <strong>${newExpiryDisplay}</strong>)</td></tr>
                        <tr><td style="padding:6px 0;color:#94a3b8;">Mã GD SePay:</td><td>${txId || "--"}</td></tr>
                    </table>
                </div>`
            });
        }
    } catch (emailErr) {
        // Không làm lỗi webhook nếu gửi email thất bại
    }

    return jsonResponse({ success: true, message: `Đã gia hạn tự động cho đơn ${matched.order_code}` });
}
