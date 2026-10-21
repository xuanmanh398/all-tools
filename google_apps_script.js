/**
 * =========================================================================
 * GOOGLE APPS SCRIPT - HỆ THỐNG TỰ ĐỘNG ĐĂNG KÝ VÀ CẤP KEY PHẦN MỀM
 * =========================================================================
 * 
 * TỰ ĐỘNG HOÀN TOÀN:
 * 1. Khách mở phần mềm -> Phần mềm tự động gửi Mã Máy lên Google Sheet.
 * 2. Sheet tự động sinh Key mới cho máy đó và lưu lại.
 * 3. Admin chỉ cần sửa cột Expiry_Date (Thời hạn) hoặc bấm nút duyệt nhanh!
 */

var SHEET_NAME = "Sheet1";

/**
 * Menu quản trị nhanh trên Google Sheet
 */
function onOpen() {
  var ui = SpreadsheetApp.getUi();
  ui.createMenu("🛡️ Quản Lý Bản Quyền")
    .addItem("📋 1. Khởi Tạo Tiêu Đề Cột (Nếu Bảng Rỗng)", "menuSetupHeaders")
    .addSeparator()
    .addItem("⚡ Duyệt 30 Ngày Cho Dòng Đang Chọn", "menuApprove30Days")
    .addItem("⚡ Duyệt 90 Ngày Cho Dòng Đang Chọn", "menuApprove90Days")
    .addItem("👑 Duyệt VĨNH VIỄN Cho Dòng Đang Chọn", "menuApproveLifetime")
    .addSeparator()
    .addItem("🔒 Khóa Key (Dòng Đang Chọn)", "menuLockSelectedKey")
    .addItem("🔓 Mở Khóa Key (Dòng Đang Chọn)", "menuUnlockSelectedKey")
    .addToUi();
}

/**
 * Khởi tạo tiêu đề cột chuẩn đẹp mắt
 */
function menuSetupHeaders() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(SHEET_NAME) || ss.getActiveSheet();
  
  var headers = ["Machine_ID", "License_Key", "Expiry_Date", "Status", "Note"];
  sheet.getRange(1, 1, 1, 5).setValues([headers]);
  
  var headerRange = sheet.getRange(1, 1, 1, 5);
  headerRange.setBackground("#1e293b");
  headerRange.setFontColor("#38bdf8");
  headerRange.setFontWeight("bold");
  headerRange.setFontSize(11);
  headerRange.setHorizontalAlignment("center");
  
  sheet.setColumnWidth(1, 260); // Machine_ID
  sheet.setColumnWidth(2, 200); // License_Key
  sheet.setColumnWidth(3, 140); // Expiry_Date
  sheet.setColumnWidth(4, 110); // Status
  sheet.setColumnWidth(5, 260); // Note
  
  SpreadsheetApp.getUi().alert("✅ Đã khởi tạo tiêu đề bảng thành công!");
}

/**
 * Sinh Key ngẫu nhiên chuẩn: CW-XXXX-XXXX-XXXX
 */
function generateRandomKey() {
  var chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  function segment(len) {
    var res = "";
    for (var i = 0; i < len; i++) {
      res += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return res;
  }
  return "CW-" + segment(4) + "-" + segment(4) + "-" + segment(4);
}

/**
 * API NHẬN YÊU CẦU TỪ PHẦN MỀM (HTTP GET)
 * Hỗ trợ 2 hành động:
 * 1. action=auto_register: Tự động đẩy mã máy lên và nhận Key về.
 * 2. action=check: Kiểm tra tính hợp lệ của Key và thời hạn.
 */
function doGet(e) {
  var params = e ? e.parameter : {};
  var action = (params.action || "auto_register").trim().toLowerCase();
  var machineId = (params.machine_id || "").trim().toUpperCase();
  var licenseKey = (params.key || "").trim().toUpperCase();
  var computerName = (params.computer_name || "").trim();

  if (!machineId) {
    return createJsonResponse({
      success: false,
      message: "Thiếu tham số machine_id."
    });
  }

  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(SHEET_NAME) || ss.getActiveSheet();

  // Tự tạo tiêu đề nếu bảng còn rỗng
  if (sheet.getLastRow() === 0) {
    var headers = ["Machine_ID", "License_Key", "Expiry_Date", "Status", "Note"];
    sheet.getRange(1, 1, 1, 5).setValues([headers]);
  }

  var data = sheet.getDataRange().getValues();
  var rowIndex = -1;
  var existingRow = null;

  // Tìm kiếm Machine_ID đã có trên bảng chưa
  for (var r = 1; r < data.length; r++) {
    var mid = data[r][0].toString().trim().toUpperCase();
    if (mid === machineId) {
      rowIndex = r + 1; // 1-indexed trong Google Sheet
      existingRow = data[r];
      break;
    }
  }

  var now = new Date();
  var timeStr = Utilities.formatDate(now, "GMT+7", "dd/MM/yyyy HH:mm");

  // NẾU CHƯA CÓ TRÊN SHEET -> TỰ ĐỘNG ĐẨY MÃ MÁY LÊN VÀ TỰ SINH KEY
  if (!existingRow) {
    var newKey = generateRandomKey();
    // Mặc định cho phép dùng thử 1 ngày hoặc ghi "CHỜ DUYỆT" để Admin vào chỉnh thời hạn
    var defaultExpiry = "CHỜ DUYỆT";
    var noteStr = "Tự động đăng ký lúc " + timeStr + (computerName ? " (" + computerName + ")" : "");
    
    sheet.appendRow([machineId, newKey, defaultExpiry, "ACTIVE", noteStr]);
    var newRow = sheet.getLastRow();
    sheet.getRange(newRow, 1, 1, 4).setHorizontalAlignment("center");

    return createJsonResponse({
      success: true,
      action: "registered_new",
      machine_id: machineId,
      license_key: newKey,
      expiry_raw: defaultExpiry,
      expiry_display: "Chờ Admin duyệt thời hạn trên Google Sheet",
      status: "ACTIVE",
      is_valid: false,
      message: "Đã tự động gửi Mã Máy lên Google Sheet và tạo Key thành công! Vui lòng nhờ Admin cài thời hạn."
    });
  }

  // NẾU ĐÃ CÓ TRÊN SHEET -> Lấy Key và kiểm tra thời hạn
  var curKey = existingRow[1].toString().trim().toUpperCase();
  var curExp = existingRow[2].toString().trim();
  var curStatus = existingRow[3].toString().trim().toUpperCase();
  var curNote = existingRow[4].toString().trim();

  // Nếu người dùng gửi yêu cầu check key cụ thể mà không khớp
  if (action === "check" && licenseKey && licenseKey !== curKey) {
    return createJsonResponse({
      success: false,
      valid: false,
      message: "Mã Key không chính xác với máy này."
    });
  }

  // Kiểm tra trạng thái khóa
  if (curStatus !== "ACTIVE" && curStatus !== "HOẠT ĐỘNG" && curStatus !== "OK") {
    return createJsonResponse({
      success: true,
      valid: false,
      status: curStatus,
      license_key: curKey,
      expiry_raw: curExp,
      expiry_display: "Bị khóa [" + curStatus + "]",
      message: "Bản quyền máy này đang bị khóa bởi Quản trị viên."
    });
  }

  // Kiểm tra thời hạn
  var expCheck = checkExpiry(curExp);
  return createJsonResponse({
    success: true,
    valid: expCheck.isValid,
    action: "found_existing",
    machine_id: machineId,
    license_key: curKey,
    expiry_raw: curExp,
    expiry_display: expCheck.display,
    status: curStatus,
    note: curNote,
    message: expCheck.isValid 
      ? "Bản quyền hợp lệ! Hạn dùng: " + expCheck.display 
      : (curExp.toUpperCase() === "CHỜ DUYỆT" ? "Key đã tạo. Đang chờ Admin thiết lập thời hạn." : "Bản quyền đã hết hạn (" + expCheck.display + ")")
  });
}

function doPost(e) {
  return doGet(e);
}

/**
 * Kiểm tra hạn dùng
 */
function checkExpiry(rawExp) {
  if (!rawExp || rawExp.toString().trim() === "" || rawExp.toString().toUpperCase() === "CHỜ DUYỆT") {
    return { isValid: false, display: "Chưa cấp thời hạn (Chờ Admin)" };
  }
  var up = rawExp.toString().trim().toUpperCase();
  if (up === "LIFETIME" || up === "VINH VIEN" || up === "VĨNH VIỄN") {
    return { isValid: true, display: "Vĩnh viễn (Không giới hạn)" };
  }

  var expDate = new Date(rawExp);
  if (isNaN(expDate.getTime())) {
    // Thử phân tích định dạng DD/MM/YYYY
    var parts = rawExp.toString().split("/");
    if (parts.length === 3) {
      expDate = new Date(parseInt(parts[2], 10), parseInt(parts[1], 10) - 1, parseInt(parts[0], 10));
    }
  }

  if (isNaN(expDate.getTime())) {
    return { isValid: false, display: "Định dạng ngày không hợp lệ (" + rawExp + ")" };
  }

  expDate.setHours(23, 59, 59);
  var now = new Date();
  if (expDate < now) {
    return { isValid: false, display: "Đã hết hạn vào " + Utilities.formatDate(expDate, "GMT+7", "dd/MM/yyyy") };
  }

  var diffDays = Math.ceil((expDate - now) / (1000 * 60 * 60 * 24));
  return {
    isValid: true,
    display: "Còn " + diffDays + " ngày (Hạn: " + Utilities.formatDate(expDate, "GMT+7", "dd/MM/yyyy") + ")"
  };
}

function createJsonResponse(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * Menu: Duyệt 30 ngày cho dòng đang chọn
 */
function menuApprove30Days() {
  setDurationForSelectedRow(30);
}

/**
 * Menu: Duyệt 90 ngày cho dòng đang chọn
 */
function menuApprove90Days() {
  setDurationForSelectedRow(90);
}

/**
 * Menu: Duyệt Vĩnh viễn cho dòng đang chọn
 */
function menuApproveLifetime() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var row = sheet.getActiveCell().getRow();
  if (row <= 1) {
    SpreadsheetApp.getUi().alert("Vui lòng chọn dòng khách hàng cần duyệt!");
    return;
  }
  sheet.getRange(row, 3).setValue("LIFETIME");
  sheet.getRange(row, 4).setValue("ACTIVE");
  SpreadsheetApp.getUi().alert("🎉 Đã duyệt bản quyền VĨNH VIỄN cho dòng " + row + "!");
}

function setDurationForSelectedRow(days) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var row = sheet.getActiveCell().getRow();
  if (row <= 1) {
    SpreadsheetApp.getUi().alert("Vui lòng chọn dòng khách hàng cần duyệt!");
    return;
  }
  var expDate = new Date();
  expDate.setDate(expDate.getDate() + days);
  var expStr = Utilities.formatDate(expDate, "GMT+7", "yyyy-MM-dd");
  sheet.getRange(row, 3).setValue(expStr);
  sheet.getRange(row, 4).setValue("ACTIVE");
  SpreadsheetApp.getUi().alert("✅ Đã duyệt thời hạn " + days + " ngày cho dòng " + row + "!\nHạn dùng: " + expStr);
}

function menuLockSelectedKey() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var row = sheet.getActiveCell().getRow();
  if (row <= 1) return;
  sheet.getRange(row, 4).setValue("BLOCKED");
  SpreadsheetApp.getUi().alert("🔒 Đã khóa dòng " + row + " (BLOCKED)!");
}

function menuUnlockSelectedKey() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var row = sheet.getActiveCell().getRow();
  if (row <= 1) return;
  sheet.getRange(row, 4).setValue("ACTIVE");
  SpreadsheetApp.getUi().alert("🔓 Đã mở khóa dòng " + row + " (ACTIVE)!");
}
