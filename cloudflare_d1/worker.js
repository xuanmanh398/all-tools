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

            // 6. API CÔNG KHAI & TẢI FILE STREAMING
            if (path === "/api/public/resources") {
                return await handlePublicResources(env);
            }
            if (path.startsWith("/download/file/") || path.startsWith("/api/files/download/")) {
                const parts = path.split("/").filter(Boolean);
                const fileId = parts[parts.length - 1];
                return await handleDownloadFile(fileId, env);
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
    const url = new URL(request.url);
    const authHeader = request.headers.get("X-Admin-Key") || url.searchParams.get("key");
    const configuredSecret = env.ADMIN_PASSWORD || ADMIN_PASSWORD;
    return authHeader === configuredSecret;
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

    // Máy mới cài đặt chưa có trên hệ thống -> Tự động sinh Key và lưu lên Web Admin (chờ Admin cấp hạn)
    const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
    const randPart = () => {
        let s = "";
        for (let i = 0; i < 4; i++) s += chars.charAt(Math.floor(Math.random() * chars.length));
        return s;
    };
    const newKey = `CWAI-${randPart()}-${randPart()}-${randPart()}`;
    const defaultCustomer = computerName ? `Máy mới: ${computerName}` : "Khách hàng mới";

    await env.DB.prepare(`
        INSERT INTO licenses (license_key, machine_id, customer_name, expiry_date, status, last_verified_at, note)
        VALUES (?, ?, ?, 'PENDING', 'PENDING', datetime('now', '+7 hours'), 'Tự động tạo khi cài máy mới')
    `).bind(newKey, machineId, defaultCustomer).run();

    return jsonResponse({
        valid: false,
        status: "PENDING",
        license_key: newKey,
        machine_id: machineId,
        expiry_raw: "PENDING",
        expiry_display: "Chờ Admin kích hoạt",
        customer_name: defaultCustomer,
        message: "Thiết bị và Key mới đã được tự động tạo trên hệ thống. Vui lòng chờ Admin cấp thời hạn!"
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
    const body = await request.json();
    const id = body.id;
    if (!id) return jsonResponse({ error: "Thiếu ID" }, 400);
    await env.DB.prepare("UPDATE licenses SET machine_id = '' WHERE id = ?").bind(id).run();
    return jsonResponse({ success: true, message: "Đã reset mã máy, khách có thể kích hoạt trên máy mới!" });
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

async function handleDownloadFile(fileId, env) {
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
    env.DB.prepare("UPDATE app_files SET download_count = download_count + 1 WHERE id = ?").bind(file.id).run().catch(() => {});

    if (file.storage_type === "external" && file.external_url) {
        return Response.redirect(file.external_url, 302);
    }

    if (!env.FILES_KV) {
        return new Response("Chưa cấu hình Cloudflare KV (FILES_KV) trên Worker!", { status: 500 });
    }

    const totalChunks = Number(file.chunk_count || 0);
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

    const rawName = (file.file_name || "download.bin").replace(/"/g, "");
    const safeFilename = encodeURIComponent(rawName).replace(/'/g, "%27");
    const headers = {
        "Content-Type": file.content_type || "application/octet-stream",
        "Content-Disposition": `attachment; filename="${rawName}"; filename*=UTF-8''${safeFilename}`,
        "Cache-Control": "public, max-age=3600",
        ...CORS_HEADERS
    };
    if (file.file_size && Number(file.file_size) > 0) {
        headers["Content-Length"] = String(file.file_size);
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
    const otherFiles = files.filter(f => (f.category || "software") !== "software");

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
                        Hỗ trợ Windows 10 / Windows 11 (64-bit)
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
            let videoBlock = "";
            if (embedUrl) {
                videoBlock = `
                <div class="ratio ratio-16x9 mt-3 rounded overflow-hidden border border-secondary border-opacity-25">
                    <iframe src="${embedUrl}" title="${escapeHtml(g.title)}" allowfullscreen></iframe>
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
                <h1 class="fw-bold text-white display-6 mb-2">Tải Phần Mềm & Hướng Dẫn Sử Dụng</h1>
                <p class="text-secondary">Cài đặt nhanh chóng - Kích hoạt tự động - Hỗ trợ đa luồng Facebook & Threads</p>
            </div>
            ${heroHtml}
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
            © 2026 Tools Marketing Platform • Hệ thống phân phối bản quyền & tài liệu chính thức
        </footer>
    </main>
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
        body { background-color: #0b0f19; color: #cbd5e1; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        .card { background-color: #111827; border: 1px solid #1f2937; color: #cbd5e1; border-radius: 10px; }
        .table { color: #cbd5e1; border-color: #1f2937; }
        .table-dark { background-color: #111827; }
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
            <div class="d-flex flex-wrap gap-2">
                <a href="/tai-va-huong-dan" target="_blank" class="btn btn-outline-info">📖 Mở Trang Tải & Hướng Dẫn</a>
                <button class="btn btn-outline-secondary" onclick="copyGuideUrl()">🔗 Copy Link Trang Tải</button>
                <button class="btn btn-outline-light" onclick="reloadCurrentTab()">🔄 Làm Mới</button>
            </div>
        </div>

        <!-- Auth Box -->
        <div class="card p-3 mb-4 shadow-sm">
            <div class="row g-2 align-items-center">
                <div class="col-md-3">
                    <input type="password" id="adminKeyInput" class="form-control" placeholder="Nhập Mật Khẩu Admin..." value="admin123">
                </div>
                <div class="col-md-3">
                    <button class="btn btn-secondary w-100" onclick="saveAdminKey()">🔐 Xác Nhận Mật Khẩu</button>
                </div>
                <div class="col-md-6 text-md-end">
                    <span id="statText" class="badge bg-dark border border-secondary p-2">Đang tải dữ liệu...</span>
                </div>
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
                        <label class="form-label">Mô tả:</label>
                        <textarea id="efDesc" class="form-control" rows="3"></textarea>
                    </div>
                </div>
                <div class="modal-footer border-secondary">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Hủy</button>
                    <button type="button" class="btn btn-primary" onclick="submitEditFile()">💾 Lưu Thay Đổi</button>
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
                        <label class="form-label">Link Video Hướng Dẫn (YouTube / Google Drive - để trống nếu không có):</label>
                        <input type="url" id="gVideo" class="form-control" placeholder="https://www.youtube.com/watch?v=...">
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

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        let modalInstance = null;
        let fileEditModalInstance = null;
        let guideModalInstance = null;
        let selectedUploadFile = null;
        let cachedLicenses = [];
        let cachedFiles = [];
        let cachedGuides = [];

        function escHtml(s) {
            return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        }

        let adminKey = localStorage.getItem('cf_admin_key') || 'admin123';
        document.getElementById('adminKeyInput').value = adminKey;

        function saveAdminKey() {
            adminKey = document.getElementById('adminKeyInput').value.trim();
            localStorage.setItem('cf_admin_key', adminKey);
            reloadCurrentTab();
        }

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

        async function resetMachine(id) {
            if (!confirm('Khách hàng sẽ có thể kích hoạt key này trên một máy tính mới. Tiếp tục?')) return;
            await fetch('/api/admin/reset-machine', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey },
                body: JSON.stringify({ id })
            });
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
            document.getElementById('efExternalWrap').style.display = f.storage_type === 'external' ? 'block' : 'none';
            if (!fileEditModalInstance) fileEditModalInstance = new bootstrap.Modal(document.getElementById('fileEditModal'));
            fileEditModalInstance.show();
        }

        async function submitEditFile() {
            const data = {
                id: parseInt(document.getElementById('efId').value),
                title: document.getElementById('efTitle').value.trim(),
                version: document.getElementById('efVersion').value.trim(),
                category: document.getElementById('efCategory').value,
                external_url: document.getElementById('efExternalUrl').value.trim(),
                description: document.getElementById('efDesc').value.trim()
            };
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
            if (!guideModalInstance) guideModalInstance = new bootstrap.Modal(document.getElementById('guideModal'));
            guideModalInstance.show();
        }

        async function saveGuide() {
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
