# -*- coding: utf-8 -*-
"""
Script tạo file Excel kịch bản marketing thu hút người dùng cho ứng dụng Tools Marketing (99k/tháng)
kèm 5 ảnh chụp thực tế của phần mềm chèn trực tiếp vào worksheet.
"""

import os
import shutil
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.drawing.image import Image

def build_excel_marketing_kit():
    base_dir = r"D:\ToolsHN"
    screenshots_dir = os.path.join(base_dir, "screenshots")
    output_xlsx_path = os.path.join(base_dir, "Kich_Ban_Marketing_Tools_Marketing_99k.xlsx")
    desktop_dir = os.path.join(os.environ.get("USERPROFILE", r"C:\Users\haina"), "Desktop")
    desktop_xlsx_path = os.path.join(desktop_dir, "Kich_Ban_Marketing_Tools_Marketing_99k.xlsx")
    desktop_img_dir = os.path.join(desktop_dir, "5_Anh_Giao_Dien_Tools_Marketing")

    # 1. Đảm bảo copy 5 ảnh chụp app ra Desktop cho người dùng tiện đăng bài quảng cáo
    os.makedirs(desktop_img_dir, exist_ok=True)
    screenshot_files = [
        "01_trang_chu_dashboard.png",
        "02_auto_comment_facebook.png",
        "03_dang_bai_nhom_facebook.png",
        "04_dang_bai_threads_marketing.png",
        "05_quan_ly_tai_khoan_facebook.png"
    ]
    for sf in screenshot_files:
        src = os.path.join(screenshots_dir, sf)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(desktop_img_dir, sf))

    wb = openpyxl.Workbook()
    # Xóa sheet mặc định
    wb.remove(wb.active)

    # Định nghĩa Palette Màu Sắc Hiện Đại & Chuyên Nghiệp
    COLOR_PRIMARY = "1E293B"      # Dark Slate Navy
    COLOR_SECONDARY = "4F46E5"    # Indigo Accent
    COLOR_EMERALD = "059669"      # Emerald Green
    COLOR_AMBER = "D97706"        # Amber
    COLOR_BG_LIGHT = "F8FAFC"     # Light Slate Tint
    COLOR_BORDER = "CBD5E1"       # Light Slate Border
    COLOR_HIGHLIGHT = "FEF3C7"    # Warm Yellow Accent

    font_title = Font(name="Segoe UI", size=14, bold=True, color="FFFFFF")
    font_section = Font(name="Segoe UI", size=12, bold=True, color="FFFFFF")
    font_header = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    font_sub_header = Font(name="Segoe UI", size=11, bold=True, color=COLOR_PRIMARY)
    font_bold = Font(name="Segoe UI", size=10, bold=True, color="0F172A")
    font_normal = Font(name="Segoe UI", size=10, color="1E293B")
    font_italic = Font(name="Segoe UI", size=9, italic=True, color="64748B")
    font_accent = Font(name="Segoe UI", size=10, bold=True, color=COLOR_SECONDARY)

    fill_primary = PatternFill(start_color=COLOR_PRIMARY, end_color=COLOR_PRIMARY, fill_type="solid")
    fill_indigo = PatternFill(start_color=COLOR_SECONDARY, end_color=COLOR_SECONDARY, fill_type="solid")
    fill_emerald = PatternFill(start_color=COLOR_EMERALD, end_color=COLOR_EMERALD, fill_type="solid")
    fill_light = PatternFill(start_color=COLOR_BG_LIGHT, end_color=COLOR_BG_LIGHT, fill_type="solid")
    fill_highlight = PatternFill(start_color=COLOR_HIGHLIGHT, end_color=COLOR_HIGHLIGHT, fill_type="solid")
    fill_white = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")

    thin_border = Border(
        left=Side(style='thin', color=COLOR_BORDER),
        right=Side(style='thin', color=COLOR_BORDER),
        top=Side(style='thin', color=COLOR_BORDER),
        bottom=Side(style='thin', color=COLOR_BORDER)
    )

    def style_header_row(ws, row_idx, num_cols, fill=fill_primary, font=font_header):
        for col in range(1, num_cols + 1):
            cell = ws.cell(row=row_idx, column=col)
            cell.fill = fill
            cell.font = font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = thin_border
        ws.row_dimensions[row_idx].height = 28

    # =========================================================================
    # SHEET 1: KỊCH BẢN VIDEO QUẢNG CÁO (TIKTOK / REELS / YOUTUBE SHORTS)
    # =========================================================================
    ws1 = wb.create_sheet(title="Kich_Ban_Video_Trieu_View")
    ws1.views.sheetView[0].showGridLines = True

    # Title Banner
    ws1.merge_cells("A1:F1")
    title_cell = ws1["A1"]
    title_cell.value = "🚀 BỘ KỊCH BẢN VIDEO QUẢNG CÁO NGẮN (TIKTOK / REELS / SHORTS) - GÓI TOOLS MARKETING 99K/THÁNG"
    title_cell.fill = fill_primary
    title_cell.font = font_title
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws1.row_dimensions[1].height = 38

    ws1.merge_cells("A2:F2")
    sub_cell = ws1["A2"]
    sub_cell.value = "🎯 Chiến lược: Đánh trúng nỗi đau bán hàng cày cuốc bằng tay - Trình diễn công nghệ song song Facebook & Threads - Chốt giá sốc 99.000đ/tháng"
    sub_cell.fill = fill_indigo
    sub_cell.font = Font(name="Segoe UI", size=10, italic=True, color="FFFFFF")
    sub_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws1.row_dimensions[2].height = 24

    headers1 = [
        "Phân Cảnh",
        "Thời Lượng",
        "Hình Ảnh & Hành Động (Visual)",
        "Lời Thoại / Voiceover (Audio)",
        "Chữ Hiển Thị (Text On Screen)",
        "Mục Tiêu Tâm Lý & CTA"
    ]

    row_cursor = 4

    videos_data = [
        {
            "name": "🎬 KỊCH BẢN 1: BÍ QUYẾT ĐỘT PHÁ ĐƠN HÀNG - CÀY TAY VS CỖ MÁY TỰ ĐỘNG 99K",
            "desc": "Dành cho đối tượng: Người bán hàng online, Affiliate Shopee/TikTok, chủ shop đang cày cuốc đăng bài thủ công mệt mỏi.",
            "scenes": [
                (
                    "Cảnh 1 (Hook)",
                    "00:00 - 00:05",
                    "Quay cận cảnh một người ngồi ôm máy tính lúc đêm muộn, gõ phím mỏi nhừ tay, thở dài chán nản vì đăng bài vào từng nhóm Facebook không có ai tương tác.",
                    "Đừng có dại mà ngồi copy paste đăng bài bằng tay vào từng hội nhóm nữa các bác ơi! 2026 rồi, người ta dùng cỗ máy tự động kiếm tiền trăm triệu mỗi tháng hết rồi!",
                    "❌ ĐỪNG ĐĂNG BÀI BẰNG TAY NỮA!\n⏰ 12H ĐÊM VẪN PHẢI CÀY TAY?",
                    "Kích thích nỗi đau, tạo sự tò mò và dừng ngón tay lướt video ngay trong 3 giây đầu."
                ),
                (
                    "Cảnh 2 (Vấn đề)",
                    "00:05 - 00:15",
                    "Cảnh mở màn hình máy tính với hàng chục tab trình duyệt mở lộn xộn, tài khoản bị Facebook báo 'Bạn tạm thời bị chặn tính năng' (Checkpoint).",
                    "Cứ cặm cụi cả ngày đăng được chục nhóm thì bị Facebook nó quét khóa nick. Mua tool ngoài thị trường thì toàn 1 đến 2 triệu một tháng, vừa đắt vừa khó dùng!",
                    "⚠️ BỊ CHẶN ĐĂNG BÀI?\n💸 TOOL NGOÀI THỊ TRƯỜNG: 1-2 TRIỆU/THÁNG QUÁ ĐẮT!",
                    "Khắc họa sự bất lực khi gặp checkpoint và gánh nặng chi phí phần mềm."
                ),
                (
                    "Cảnh 3 (Giải pháp 1)",
                    "00:15 - 00:28",
                    "Show giao diện thực tế của phần mềm Tools Marketing (Mở tab Đăng bài Facebook & Auto Comment). Bấm nút 'Bắt đầu', phần mềm tự động chạy mượt mà.",
                    "Nhìn đây này! Đây là phần mềm Tools Marketing bản nâng cấp mới nhất. 1 cú click chuột, nó tự động đăng bài vào 100 nhóm Facebook, tự đổi nội dung Spintax chống spam, tự hẹn giờ thông minh!",
                    "✅ TOOLS MARKETING 2026\n⚡ 1 CLICK ĐI 100 NHÓM TỰ ĐỘNG\n🛡️ CÔNG NGHỆ CHỐNG KHÓA NICK",
                    "Chứng minh công cụ có thật, giao diện tiếng Việt đẹp mắt, giải quyết triệt để khâu cày tay."
                ),
                (
                    "Cảnh 4 (Giải pháp 2)",
                    "00:28 - 00:42",
                    "Cực kỳ ấn tượng: Màn hình chia đôi, bên trái Google Chrome đang tự động Auto Comment kéo khách Facebook, bên phải Microsoft Edge đang quét và đăng bài Threads ào ào!",
                    "Đặc biệt chưa từng có: Chạy song song cả Facebook lẫn Threads cùng lúc trên 2 trình duyệt Chrome và Edge mà không hề xung đột! Vừa phủ sóng group Facebook, vừa gom traffic triệu view từ Threads!",
                    "🔥 ĐỘT PHÁ: CHẠY SONG SONG 2 TRÌNH DUYỆT\n📘 FACEBOOK (CHROME) + 📷 THREADS (EDGE)\n🚀 NHÂN ĐÔI TRAFFIC CÙNG LÚC!",
                    "Tạo cảm giác công nghệ vượt trội (USP), khách hàng thấy giá trị nhận được quá lớn."
                ),
                (
                    "Cảnh 5 (Báo giá sốc)",
                    "00:42 - 00:52",
                    "Người nói cầm điện thoại hoặc nhìn thẳng camera với nụ cười tự tin, tay cầm 2 ly trà sữa hoặc hiển thị icon 99.000đ.",
                    "Một cỗ máy làm việc 24/7 như thế này, các bác nghĩ bao nhiêu tiền? Không phải 1 triệu, cũng chẳng phải 500k... Mà chỉ đúng 99.000 VNĐ cho cả một tháng sử dụng! Đúng bằng 2 cốc trà sữa!",
                    "💥 GIÁ SỐC: CHỈ 99K / 1 THÁNG!\n☕ RẺ HƠN 3.000Đ MỖI NGÀY\n🎁 BẰNG ĐÚNG 2 LY TRÀ SỮA",
                    "Phá vỡ rào cản tài chính của khách hàng. Giá 99k quá rẻ khiến khách không cần đắn đo."
                ),
                (
                    "Cảnh 6 (Kêu gọi CTA)",
                    "00:52 - 01:00",
                    "Màn hình hiện thông tin liên hệ, nút tải nhanh trên Desktop, cam kết hỗ trợ cài đặt Ultraview trong 5 phút.",
                    "Bác nào muốn rảnh tay đi chơi mà đơn hàng vẫn nổ ầm ầm thì bình luận ngay dưới video hoặc nhắn tin cho em, em hỗ trợ cài đặt tận nơi dùng thử ngay hôm nay nhé!",
                    "👉 INBOX HOẶC CMT NGAY ĐỂ NHẬN TOOL!\n⚡ HỖ TRỢ CÀI ĐẶT TẬN NƠI 5 PHÚT\n🔒 CAM KẾT BẢO HÀNH 1 ĐỔI 1",
                    "Thúc đẩy hành động tức thì, giảm rủi ro bằng cam kết hỗ trợ kỹ thuật tận tình."
                )
            ]
        },
        {
            "name": "🎬 KỊCH BẢN 2: BÍ MẬT 50 ĐƠN/NGÀY TỪ THREADS MASS POST & EXCEL TỰ ĐỘNG",
            "desc": "Dành cho đối tượng: Dân làm Affiliate Marketing, Shopee, TikTok Shop, người săn traffic organic trên mạng xã hội Threads.",
            "scenes": [
                (
                    "Cảnh 1 (Hook)",
                    "00:00 - 00:05",
                    "Cầm điện thoại mở app ngân hàng hoặc màn hình Shopee Affiliate với thông báo hoa hồng nổ liên tục 'Ting ting'.",
                    "Nhiều bác hỏi em tại sao không chạy quảng cáo mà mỗi ngày vẫn nổ 40 - 50 đơn Affiliate? Bí mật nằm ở con bot tự động này này!",
                    "💰 0 ĐỒNG QUẢNG CÁO\n🚀 50 ĐƠN AFFILIATE MỖI NGÀY NHỜ ĐÂU?",
                    "Khoe kết quả thực chiến, tạo động lực kiếm tiền cho người xem."
                ),
                (
                    "Cảnh 2 (Bí mật Threads)",
                    "00:05 - 00:18",
                    "Lướt feed Threads với hàng loạt bài viết reach tự nhiên cả chục ngàn view mà không mất 1 xu quảng cáo.",
                    "Threads đang là mỏ vàng thuật toán phân phối cực mạnh của Meta. Ai biết chiếm lĩnh vị trí trước người đó hốt bạc!",
                    "📈 MỎ VÀNG THREADS META 2026\n🔥 REACH TỰ NHIÊN HÀNG CHỤC NGHÌN VIEW",
                    "Chỉ ra xu hướng thị trường nóng hổi mà người xem chưa biết tận dụng."
                ),
                (
                    "Cảnh 3 (Thao tác phần mềm)",
                    "00:18 - 00:35",
                    "Mở file Excel Post.xlsx chứa ảnh và bài viết, sau đó mở Tools Marketing bấm 'Bắt đầu đăng'. Bot tự mở Edge, tự gõ bài, tự đính kèm ảnh cực nét.",
                    "Chỉ cần chuẩn bị 1 file Excel nội dung, Tools Marketing sẽ tự động quét ảnh, tự động đăng bài hẹn giờ cả ngày lẫn đêm. Thậm chí tự động comment dẫn link mua hàng ở top đầu!",
                    "📊 TẢI TỰ ĐỘNG TỪ FILE EXCEL POST.XLSX\n🤖 TỰ ĐĂNG BÀI + TỰ GHIM COMMENT LINK\n⚙️ HOÀN TOÀN TỰ ĐỘNG 24/7",
                    "Cho thấy sự tiện lợi tối đa: chỉ cần chuẩn bị file 1 lần là xong."
                ),
                (
                    "Cảnh 4 (Đề nghị giá & CTA)",
                    "00:35 - 00:50",
                    "Hiển thị bảng giá 99k/tháng và cảnh báo chương trình ưu đãi số lượng có hạn cho 50 người đăng ký đầu tiên.",
                    "Chi phí duy trì server chỉ vỏn vẹn 99k một tháng. Đừng để đối thủ của bạn cướp mất khách hàng trên Threads. Nhấp vào link bio hoặc nhắn tin cho em ngay!",
                    "🏷️ CHỈ 99K/THÁNG - RẺ VÔ ĐỊCH\n⏳ GIỚI HẠN 50 SUẤT ƯU ĐÃI THÁNG NÀY\n👉 BẤM VÀO BIO / INBOX NGAY!",
                    "Tạo cảm giác khan hiếm và thôi thúc chốt đơn ngay lập tức."
                )
            ]
        },
        {
            "name": "🎬 KỊCH BẢN 3: TỰ ĐỘNG COMMENT FACEBOOK - CHIÊU KÉO KHÁCH MIỄN PHÍ TỪ ĐỐI THỦ",
            "desc": "Dành cho đối tượng: Bất động sản, tuyển dụng, bảo hiểm, dịch vụ spa, kho hàng sỉ lẻ.",
            "scenes": [
                (
                    "Cảnh 1 (Hook)",
                    "00:00 - 00:05",
                    "Quay màn hình một bài viết đông nghịt bình luận hỏi mua hàng của đối thủ hoặc một hội nhóm đông thành viên.",
                    "Muốn hút sạch khách hàng từ bài viết của đối thủ hoặc các hội nhóm nghìn thành viên mà không tốn tiền chạy ads?",
                    "🎯 HÚT KHÁCH TỰ ĐỘNG TỪ ĐỐI THỦ\n💸 0 ĐỒNG CHI PHÍ QUẢNG CÁO!",
                    "Gợi mở chiến thuật marketing 'du kích' thông minh, đánh trúng tâm lý thích tiết kiệm."
                ),
                (
                    "Cảnh 2 (Trình diễn Auto Comment)",
                    "00:05 - 00:25",
                    "Mở tab 'Auto Comment FB' trên Tools Marketing. Dán link bài viết hoặc nhập từ khóa 'cần mua', 'tìm nguồn sỉ'. Bấm Chạy, bot lập tức vào cmt chuyên nghiệp.",
                    "Đây, tính năng Auto Comment FB mới toanh! Bạn chỉ cần dán link bài viết hoặc quét theo từ khóa, tool sẽ tự động vào tương tác, giới thiệu sản phẩm của bạn với nội dung Spintax cực kỳ tự nhiên!",
                    "💬 TỰ ĐỘNG COMMENT THEO BÀI VIẾT / TỪ KHÓA\n🔄 NỘI DUNG SPINTAX THÔNG MINH\n👤 TƯƠNG TÁC NHƯ NGƯỜI THẬT",
                    "Thị phạm tính năng mới trực tiếp giúp người xem hiểu ngay cách ứng dụng vào ngành hàng của mình."
                ),
                (
                    "Cảnh 3 (An toàn tuyệt đối & Giá 99k)",
                    "00:25 - 00:45",
                    "Show tính năng chọn trình duyệt Google Chrome, chỉnh thời gian delay ngẫu nhiên chống checkpoint.",
                    "Chạy trực tiếp trên Google Chrome thật, có giãn cách delay ngẫu nhiên nên cực kỳ an toàn cho tài khoản. Trọn bộ công cụ đỉnh cao này chỉ 99k/tháng. Bác nào cần thì nhắn tin em ngay nhé!",
                    "🛡️ CHẠY TRÌNH DUYỆT THẬT - CỰC KỲ AN TOÀN\n💲 GIÁ TRỌN GÓI: 99.000Đ / THÁNG\n📩 NHẮN TIN ĐỂ NHẬN PHẦN MỀM!",
                    "Xóa bỏ nỗi sợ bị khóa nick và chốt hạ bằng mức giá không đối thủ."
                )
            ]
        }
    ]

    for v_idx, vid in enumerate(videos_data):
        # Section header
        ws1.merge_cells(start_row=row_cursor, start_column=1, end_row=row_cursor, end_column=6)
        sec_cell = ws1.cell(row=row_cursor, column=1)
        sec_cell.value = vid["name"]
        sec_cell.fill = fill_emerald if v_idx == 0 else (fill_indigo if v_idx == 1 else fill_primary)
        sec_cell.font = font_section
        sec_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        ws1.row_dimensions[row_cursor].height = 30
        row_cursor += 1

        # Description row
        ws1.merge_cells(start_row=row_cursor, start_column=1, end_row=row_cursor, end_column=6)
        desc_cell = ws1.cell(row=row_cursor, column=1)
        desc_cell.value = f"📌 {vid['desc']}"
        desc_cell.fill = fill_light
        desc_cell.font = font_italic
        desc_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        ws1.row_dimensions[row_cursor].height = 22
        row_cursor += 1

        # Table headers
        for col_idx, h_text in enumerate(headers1, 1):
            cell = ws1.cell(row=row_cursor, column=col_idx)
            cell.value = h_text
            cell.fill = fill_primary
            cell.font = font_header
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = thin_border
        ws1.row_dimensions[row_cursor].height = 26
        row_cursor += 1

        # Rows
        for s_idx, scene in enumerate(vid["scenes"]):
            row_fill = fill_white if s_idx % 2 == 0 else fill_light
            for col_idx, val in enumerate(scene, 1):
                cell = ws1.cell(row=row_cursor, column=col_idx)
                cell.value = val
                cell.fill = row_fill
                cell.font = font_bold if col_idx in (1, 2) else font_normal
                cell.alignment = Alignment(
                    horizontal="center" if col_idx in (1, 2) else "left",
                    vertical="center",
                    wrap_text=True
                )
                cell.border = thin_border
            ws1.row_dimensions[row_cursor].height = 68
            row_cursor += 1

        row_cursor += 2  # Khoảng cách giữa các kịch bản

    # Set column widths ws1
    col_widths1 = [16, 16, 38, 48, 30, 30]
    for i, w in enumerate(col_widths1, 1):
        ws1.column_dimensions[get_column_letter(i)].width = w


    # =========================================================================
    # SHEET 2: KỊCH BẢN BÁN HÀNG & CHỐT SALE (ZALO / FANPAGE / TELEGRAM)
    # =========================================================================
    ws2 = wb.create_sheet(title="Kich_Ban_Tu_Van_Chot_Sale")
    ws2.views.sheetView[0].showGridLines = True

    ws2.merge_cells("A1:E1")
    ws2["A1"].value = "💬 KỊCH BẢN CHĂM SÓC KHÁCH HÀNG & CHỐT SALE BÁC SĨ (TƯ VẤN QUA ZALO / FANPAGE)"
    ws2["A1"].fill = fill_primary
    ws2["A1"].font = font_title
    ws2["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws2.row_dimensions[1].height = 36

    ws2.merge_cells("A2:E2")
    ws2["A2"].value = "🎯 Quy trình 6 bước tâm lý: Chào hỏi thiện cảm ➔ Khơi gợi nỗi đau ➔ Thị phạm giải pháp ➔ Báo giá sốc 99k ➔ Xử lý từ chối ➔ Chốt đơn & Kích hoạt bản quyền"
    ws2["A2"].fill = fill_indigo
    ws2["A2"].font = Font(name="Segoe UI", size=10, italic=True, color="FFFFFF")
    ws2["A2"].alignment = Alignment(horizontal="center", vertical="center")
    ws2.row_dimensions[2].height = 24

    headers2 = [
        "Bước Triển Khai",
        "Mục Tiêu Tâm Lý",
        "Mẫu Tin Nhắn Chi Tiết (Copy & Gửi)",
        "Tài Liệu / Hình Ảnh Đi Kèm",
        "Lưu Ý Thực Chiến"
    ]

    style_header_row(ws2, 4, len(headers2), fill=fill_primary)

    sales_steps = [
        (
            "Bước 1: Chào hỏi & Xác nhận nhu cầu",
            "Tạo sự thân thiện, chuyên nghiệp, bắt đúng kênh bán hàng của khách.",
            "Dạ em chào anh/chị ạ! Em thấy anh/chị có quan tâm đến phần mềm tự động hóa Tools Marketing (đăng bài & comment tự động trên Facebook và Threads).\n\nKhông biết hiện tại mình đang kinh doanh sản phẩm/dịch vụ gì để em tư vấn cấu hình phù hợp nhất cho anh/chị ạ?",
            "Ảnh 01_trang_chu_dashboard.png (Giao diện tổng quan sang trọng)",
            "Không vồ vập bán hàng ngay. Phải biết khách bán gì để lấy ví dụ minh họa đúng ngành của họ."
        ),
        (
            "Bước 2: Khơi gợi nỗi đau & Bắt bệnh",
            "Để khách hàng tự thừa nhận sự vất vả và lãng phí thời gian khi làm thủ công.",
            "Dạ vâng ạ! Ngành này hiện nay đăng bài thủ công thì vất vả lắm anh/chị ạ. Mỗi ngày ngồi copy dán từng nhóm Facebook mất 3-4 tiếng đồng hồ mà hay bị Facebook bóp tương tác hoặc chặn tính năng.\n\nChưa kể nền tảng Threads của Meta hiện đang rất hot, nếu mình không phủ sóng tự động thì đối thủ họ gom hết khách ạ. Hiện tại mỗi ngày anh/chị đang dành bao nhiêu thời gian để đi đăng bài ạ?",
            "Ảnh minh họa cảnh checkpoint tài khoản hoặc biểu đồ traffic Threads",
            "Lắng nghe khách than phiền. Càng để khách nói ra nỗi đau thì bước chốt sale càng dễ dàng."
        ),
        (
            "Bước 3: Trình diễn giải pháp thực tế",
            "Tạo niềm tin vững chắc bằng tính năng vượt trội và giao diện trực quan dễ dùng.",
            "Dạ bên em vừa ra mắt phiên bản Tools Marketing 2026 cực kỳ tiện lợi cho anh/chị:\n\n1️⃣ Tự động đăng bài hàng loạt vào các nhóm Facebook kèm cơ chế Spintax chống khóa nick 100%.\n2️⃣ Tự động Comment Facebook theo link bài viết hoặc quét theo từ khóa khách hàng tìm kiếm để kéo khách về trang cá nhân.\n3️⃣ Tự động đăng bài Threads từ file Excel Post.xlsx có sẵn.\n4️⃣ ĐỘT PHÁ ĐỘC QUYỀN: Chạy song song 2 trình duyệt Chrome (Facebook) và Edge (Threads) cùng lúc trên 1 máy tính, hiệu suất x2 mà không sợ giật lag hay xung đột!\n\nGiao diện hoàn toàn bằng tiếng Việt, rất dễ dùng kể cả anh/chị không rành công nghệ ạ!",
            "Gửi 4 ảnh giao diện:\n• 02_auto_comment_facebook.png\n• 03_dang_bai_nhom_facebook.png\n• 04_dang_bai_threads_marketing.png",
            "Nhấn mạnh vào tính năng 'Chạy song song 2 trình duyệt' và 'Auto Comment' vì đây là 2 vũ khí độc quyền mà các tool khác không có."
        ),
        (
            "Bước 4: Báo giá gây bất ngờ & Khẳng định giá trị",
            "Phá vỡ suy nghĩ 'tool tiền triệu', khiến khách cảm thấy quá hời và muốn mua ngay.",
            "Các phần mềm marketing trên thị trường hiện nay thường thu phí từ 500.000đ đến 1.500.000đ/tháng hoặc bắt mua theo năm cả chục triệu.\n\nNhưng bên em đang trợ giá đặc biệt cho cộng đồng kinh doanh online:\n👉 Giá chỉ đúng: 99.000 VNĐ / 1 THÁNG (Tính ra mỗi ngày chỉ 3.300đ, chưa bằng cốc trà đá!).\n\n🎁 ĐẶC BIỆT: Nếu anh/chị đăng ký gói 6 tháng chỉ còn 499.000đ (Tặng thêm 1 tháng sử dụng miễn phí = Tổng 7 tháng) + Hỗ trợ kỹ thuật Ultraview 1 kèm 1 trọn đời!",
            "Ảnh bảng so sánh chi phí (Sheet 3)",
            "Luôn neo giá cao của thị trường trước (500k - 1tr), sau đó mới đưa ra giá 99k để tạo hiệu ứng tâm lý 'rẻ không tưởng'."
        ),
        (
            "Bước 5: Xử lý các lời từ chối thường gặp",
            "Giải tỏa 100% nghi ngại về kỹ thuật, độ an toàn và uy tín.",
            "XỬ LÝ 4 CÂU HỎI KINH ĐIỂN CỦA KHÁCH:\n\n❓ Câu 1: 'Chị không rành máy tính có dùng được không em?'\n➔ Trả lời: 'Chị hoàn toàn yên tâm ạ! Bên em sẽ Ultraview hoặc Anydesk cài đặt sẵn lên máy cho chị, tạo sẵn lối tắt ngoài màn hình. Em hướng dẫn trực tiếp 5 phút là chị tự bấm chạy được luôn ạ!'\n\n❓ Câu 2: 'Dùng tool có sợ bị khóa nick Facebook không em?'\n➔ Trả lời: 'Dạ phần mềm bên em chạy trực tiếp trên trình duyệt Google Chrome chính chủ, có tính năng hẹn giờ delay ngẫu nhiên và spin nội dung mô phỏng hành vi bấm chuột như người thật nên cực kỳ an toàn, không lo bị quét như các tool gửi request API cũ ạ!'\n\n❓ Câu 3: 'Có được dùng thử trước không?'\n➔ Trả lời: 'Dạ bên em cam kết bảo hành 1 đổi 1 suốt thời gian sử dụng. Mức giá 99k bên em đã hỗ trợ tối đa, nếu cài lên máy mà không chạy đúng như cam kết bên em hoàn tiền 100% ngay lập tức ạ!'\n\n❓ Câu 4: 'Tool rẻ thế có lừa đảo không?'\n➔ Trả lời: 'Dạ bên em cài đặt xong xuôi lên máy của anh/chị, anh/chị kiểm tra phần mềm hoạt động trơn tru rồi mới cần thanh toán qua ngân hàng ạ!'",
            "Ảnh chụp màn hình các khách hàng đã cài đặt thành công và phản hồi tốt",
            "Thái độ luôn tự tin, cam kết bảo hành rõ ràng, sẵn sàng cài đặt cho khách xem trước khi thu tiền để tạo niềm tin tuyệt đối."
        ),
        (
            "Bước 6: Chốt đơn & Kích hoạt bản quyền",
            "Thu tiền nhanh gọn, bàn giao công cụ và hướng dẫn trong 30 giây.",
            "Dạ anh/chị gửi em ID và Mật khẩu Ultraview (hoặc Anydesk) để kỹ thuật viên bên em kết nối cài đặt hoàn chỉnh và kích hoạt bản quyền cho anh/chị ngay nhé ạ!\n\n💳 THÔNG TIN THANH TOÁN (99.000đ / tháng hoặc 499.000đ / 7 tháng):\n• Ngân hàng: [Tên Ngân Hàng]\n• Số tài khoản: [Số Tài Khoản Của Bạn]\n• Chủ tài khoản: [Tên Chủ Tài Khoản]\n• Nội dung CK: [Số điện thoại của khách] - Tools Marketing\n\nAnh/chị chuyển khoản xong chụp màn hình giúp em, em kích hoạt key bản quyền dùng ngay trong 30 giây ạ!",
            "Mã QR chuyển khoản ngân hàng tạo sẵn (kèm số tiền 99.000đ)",
            "Gửi kèm mã QR để khách quét trong 3 giây trên app ngân hàng, không để khách phải gõ số tài khoản thủ công."
        )
    ]

    r_cur = 5
    for s in sales_steps:
        row_fill = fill_white if (r_cur % 2 == 1) else fill_light
        for c_idx, val in enumerate(s, 1):
            cell = ws2.cell(row=r_cur, column=c_idx)
            cell.value = val
            cell.fill = row_fill
            cell.font = font_bold if c_idx == 1 else font_normal
            cell.alignment = Alignment(
                horizontal="center" if c_idx in (1, 2) else "left",
                vertical="top",
                wrap_text=True
            )
            cell.border = thin_border
        ws2.row_dimensions[r_cur].height = 110
        r_cur += 1

    col_widths2 = [22, 24, 55, 32, 28]
    for i, w in enumerate(col_widths2, 1):
        ws2.column_dimensions[get_column_letter(i)].width = w


    # =========================================================================
    # SHEET 3: BẢNG SO SÁNH GIÁ TRỊ VÀ TỈ SUẤT ROI 99K
    # =========================================================================
    ws3 = wb.create_sheet(title="Bang_So_Sanh_Gia_Tri_ROI")
    ws3.views.sheetView[0].showGridLines = True

    ws3.merge_cells("A1:E1")
    ws3["A1"].value = "📊 BẢNG SO SÁNH HIỆU QUẢ KINH TẾ & TỈ SUẤT LỢI NHUẬN (ROI) KHI ĐẦU TƯ 99K/THÁNG"
    ws3["A1"].fill = fill_primary
    ws3["A1"].font = font_title
    ws3["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws3.row_dimensions[1].height = 36

    ws3.merge_cells("A2:E2")
    ws3["A2"].value = "💡 Minh chứng thuyết phục khách hàng: Tại sao bỏ ra 99k/tháng là khoản đầu tư thông minh nhất cho mọi người kinh doanh online"
    ws3["A2"].fill = fill_emerald
    ws3["A2"].font = Font(name="Segoe UI", size=10, italic=True, color="FFFFFF")
    ws3["A2"].alignment = Alignment(horizontal="center", vertical="center")
    ws3.row_dimensions[2].height = 24

    headers3 = [
        "Tiêu Chí So Sánh",
        "Phương Án 1: Làm Bằng Tay (Thủ Công)",
        "Phương Án 2: Thuê Nhân Viên / CTV",
        "Phương Án 3: Tool Thị Trường Khác",
        "Phương Án 4: TOOLS MARKETING 2026 (99k)"
    ]

    style_header_row(ws3, 4, len(headers3), fill=fill_primary)

    compare_rows = [
        (
            "1. Chi phí đầu tư mỗi tháng",
            "0 VNĐ (nhưng mất thời gian vô ích)",
            "3.000.000 - 6.000.000 VNĐ / tháng",
            "500.000 - 1.500.000 VNĐ / tháng (hoặc gói năm 5-10 triệu)",
            "⭐ CHỈ 99.000 VNĐ / THÁNG (Rẻ hơn 90% so với thị trường)"
        ),
        (
            "2. Chi phí bình quân mỗi ngày",
            "0 VNĐ",
            "100.000 - 200.000 VNĐ / ngày",
            "20.000 - 50.000 VNĐ / ngày",
            "⭐ 3.300 VNĐ / NGÀY (Rẻ hơn 1 ly trà đá vỉa hè)"
        ),
        (
            "3. Thời gian công sức bỏ ra mỗi ngày",
            "3 - 5 tiếng / ngày (Ngồi dán từng bài, mỏi mắt, stress)",
            "1 - 2 tiếng quản lý & giao việc cho CTV",
            "1 - 2 tiếng cấu hình phức tạp, dễ lỗi",
            "⭐ 5 PHÚT / NGÀY (Bấm 'Bắt đầu' rồi đi làm việc khác hoặc đi chơi)"
        ),
        (
            "4. Năng suất tiếp cận (Đăng bài & Comment)",
            "Tối đa 15 - 30 nhóm/ngày (Quá sức người)",
            "50 - 100 bài/ngày (Tùy tính tự giác của nhân viên)",
            "100 - 200 bài/ngày (Chỉ hỗ trợ 1 nền tảng đơn lẻ)",
            "⭐ 200 - 500 BÀI & COMMENT / NGÀY (Phủ sóng cả Facebook + Threads)"
        ),
        (
            "5. Khả năng chạy song song đa nền tảng",
            "❌ Không thể (chỉ làm được từng việc một)",
            "❌ Tốn thêm chi phí nếu muốn làm thêm kênh",
            "❌ Bị giới hạn hoặc phải mua 2 phần mềm khác nhau",
            "⭐ CÔNG NGHỆ SONG SONG ĐỘC QUYỀN (Chrome làm FB, Edge làm Threads)"
        ),
        (
            "6. Tính năng Auto Comment kéo khách",
            "❌ Gõ tay từng bình luận rất chậm",
            "❌ Nhân viên hay ngại đi comment dạo",
            "❌ Thường không có hoặc tính thêm tiền bản quyền riêng",
            "⭐ TÍCH HỢP SẴN MIỄN PHÍ (Comment theo link, theo nhóm, từ khóa)"
        ),
        (
            "7. Độ an toàn chống checkpoint khóa nick",
            "⚠️ Rất dễ bị khóa do hành vi lặp đi lặp lại",
            "⚠️ Phụ thuộc kinh nghiệm của nhân viên",
            "⚠️ Dễ bị quét do dùng token / cookie không có browser thật",
            "⭐ SIÊU AN TOÀN (Chạy trình duyệt Chrome/Edge thật, Spintax + Delay)"
        ),
        (
            "8. Tỉ suất sinh lời (ROI) ước tính",
            "Thấp, dễ bỏ cuộc sau 1-2 tuần cày cuốc",
            "Âm vốn nếu nhân viên làm việc không hiệu quả",
            "Cần bán nhiều đơn hàng mới bù được tiền mua tool",
            "⭐ ROI 3000% - 5000% (Chỉ cần 1 đơn hàng là hoàn vốn cho cả tháng!)"
        ),
        (
            "9. Đánh giá tổng quan",
            "Lạc hậu, tốn sức, hiệu quả kém",
            "Chi phí cao, khó quản lý con người",
            "Đắt đỏ, rủi ro tài chính cao cho người mới",
            "🏆 LỰA CHỌN TỐI ƯU NHẤT CHO DÂN BÁN HÀNG & MMO 2026"
        )
    ]

    r_c = 5
    for row in compare_rows:
        row_fill = fill_white if (r_c % 2 == 1) else fill_light
        for c_idx, val in enumerate(row, 1):
            cell = ws3.cell(row=r_c, column=c_idx)
            cell.value = val
            cell.fill = fill_highlight if c_idx == 5 else row_fill
            cell.font = font_bold if (c_idx == 1 or c_idx == 5) else font_normal
            cell.alignment = Alignment(
                horizontal="left",
                vertical="center",
                wrap_text=True
            )
            cell.border = thin_border
        ws3.row_dimensions[r_c].height = 42
        r_c += 1

    # Bảng phân tích bài toán kiếm tiền thực tế
    r_c += 2
    ws3.merge_cells(start_row=r_c, start_column=1, end_row=r_c, end_column=5)
    ws3.cell(row=r_c, column=1).value = "💰 BÀI TOÁN KINH TẾ THỰC CHIẾN: ĐẦU TƯ 99K ĐỔI LẠI GÌ?"
    ws3.cell(row=r_c, column=1).fill = fill_emerald
    ws3.cell(row=r_c, column=1).font = font_section
    ws3.cell(row=r_c, column=1).alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws3.row_dimensions[r_c].height = 30
    r_c += 1

    roi_cases = [
        ("Giả định tối thiểu", "Chỉ cần tool tiếp cận được 300 người tiềm năng/ngày trên Facebook & Threads"),
        ("Tỉ lệ chuyển đổi 1%", "Có 3 khách hàng quan tâm mua sản phẩm hoặc nhấp link Affiliate mỗi ngày"),
        ("Lợi nhuận mỗi ngày", "3 đơn hàng x Lãi 50.000đ/đơn = 150.000 VNĐ / ngày"),
        ("Lợi nhuận 1 tháng", "150.000đ x 30 ngày = 4.500.000 VNĐ / tháng"),
        ("Chi phí phần mềm", "Chỉ đúng 99.000 VNĐ / tháng"),
        ("Lợi nhuận ròng mang lại", "4.500.000đ - 99.000đ = 4.401.000 VNĐ (Gấp 45 LẦN số vốn bỏ ra!)")
    ]

    for title, desc in roi_cases:
        ws3.merge_cells(start_row=r_c, start_column=1, end_row=r_c, end_column=2)
        c1 = ws3.cell(row=r_c, column=1)
        c1.value = f"• {title}"
        c1.fill = fill_light
        c1.font = font_bold
        c1.border = thin_border

        ws3.merge_cells(start_row=r_c, start_column=3, end_row=r_c, end_column=5)
        c2 = ws3.cell(row=r_c, column=3)
        c2.value = desc
        c2.fill = fill_white
        c2.font = font_accent if "Lợi nhuận ròng" in title else font_normal
        c2.border = thin_border

        ws3.row_dimensions[r_c].height = 28
        r_c += 1

    col_widths3 = [25, 30, 32, 34, 40]
    for i, w in enumerate(col_widths3, 1):
        ws3.column_dimensions[get_column_letter(i)].width = w


    # =========================================================================
    # SHEET 4: 5 TÍNH NĂNG ĐỘT PHÁ & ĐÍNH KÈM HÌNH ẢNH APP
    # =========================================================================
    ws4 = wb.create_sheet(title="5_Tinh_Nang_Kem_Anh_Chup_App")
    ws4.views.sheetView[0].showGridLines = True

    ws4.merge_cells("A1:E1")
    ws4["A1"].value = "📸 5 TÍNH NĂNG CỐT LÕI & ẢNH CHỤP GIAO DIỆN THỰC TẾ ỨNG DỤNG TOOLS MARKETING"
    ws4["A1"].fill = fill_primary
    ws4["A1"].font = font_title
    ws4["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws4.row_dimensions[1].height = 36

    ws4.merge_cells("A2:E2")
    ws4["A2"].value = "💡 Hình ảnh chụp trực tiếp từ ứng dụng thực tế - Đính kèm ảnh chất lượng cao để tiện làm tài liệu marketing & quảng cáo"
    ws4["A2"].fill = fill_indigo
    ws4["A2"].font = Font(name="Segoe UI", size=10, italic=True, color="FFFFFF")
    ws4["A2"].alignment = Alignment(horizontal="center", vertical="center")
    ws4.row_dimensions[2].height = 24

    headers4 = [
        "STT & Tính Năng",
        "Lợi Ích Vượt Trội Cho Người Dùng",
        "Hướng Dẫn 3 Bước Thao Tác",
        "Thông Số Kỹ Thuật",
        "Ảnh Chụp Màn Hình Ứng Dụng (1600x1000 HD)"
    ]

    style_header_row(ws4, 4, len(headers4), fill=fill_primary)

    features_info = [
        {
            "stt": "TÍNH NĂNG 1:\n🏠 Trang Chủ Dashboard Thông Minh",
            "benefit": "• Bảng điều khiển trung tâm hiển thị trực quan toàn bộ trạng thái tài khoản, số bài đã đăng, nhật ký hoạt động.\n• Phím tắt truy cập nhanh từng module.\n• Theo dõi sức khỏe hệ thống và thời hạn bản quyền tức thì.",
            "guide": "1. Mở app, hệ thống tự động tải thống kê tài khoản.\n2. Bấm vào các thẻ tác vụ nhanh để chuyển thẳng đến module cần dùng.\n3. Xem thông báo hệ thống và mẹo tối ưu tương tác ở góc phải.",
            "tech": "• Database SQLite WAL Mode chống khóa đa luồng.\n• Tự động làm mới số liệu theo thời gian thực.\n• Giao diện Dark Theme hiện đại, dịu mắt.",
            "img_file": "01_trang_chu_dashboard.png"
        },
        {
            "stt": "TÍNH NĂNG 2:\n💬 Auto Comment Facebook Đột Phá",
            "benefit": "• Tự động bình luận vào các bài viết chỉ định theo Link hoặc UID.\n• Quét bài viết mới nhất trong nhóm mục tiêu để tự động cmt đầu mối.\n• Quét theo từ khóa khách hàng tìm kiếm để cmt kéo traffic về inbox/bài viết cá nhân.\n• Tiết kiệm 100% chi phí chạy quảng cáo Facebook Ads.",
            "guide": "1. Chọn tài khoản Facebook và nhập danh sách Link bài viết / Từ khóa.\n2. Soạn nội dung comment kèm cú pháp Spintax {Chào bạn|Xin chào} và chọn ảnh đính kèm.\n3. Chọn trình duyệt Google Chrome và bấm 'Bắt Đầu Bình Luận'.",
            "tech": "• Hỗ trợ Spin text đa tầng.\n• Hẹn giờ delay ngẫu nhiên chống checkpoint.\n• Chạy trên Google Chrome thật (v156+).\n• Đính kèm ảnh và avatar chuyên nghiệp.",
            "img_file": "02_auto_comment_facebook.png"
        },
        {
            "stt": "TÍNH NĂNG 3:\n🚀 Đăng Bài Hàng Loạt Lên Nhóm Facebook",
            "benefit": "• Phủ sóng bài viết đến hàng trăm hội nhóm bán hàng tiềm năng mỗi ngày.\n• Tự động đăng kèm nhiều ảnh sản phẩm chất lượng cao.\n• Không lo bị trùng nội dung nhờ bộ máy Spintax độc quyền.\n• Tự động lưu lịch sử và báo cáo nhóm đăng thành công / phê duyệt.",
            "guide": "1. Chọn danh sách nhóm cần đăng trong kho nhóm đã tham gia.\n2. Chọn nội dung bài viết và đính kèm danh sách ảnh sản phẩm.\n3. Cài đặt thời gian giãn cách (delay 30-60s) và bấm 'Bắt Đầu Đăng'.",
            "tech": "• Tự động chuyển đổi định dạng ảnh .webp sang .jpg tương thích 100%.\n• Hỗ trợ đăng nhóm công khai và nhóm riêng tư.\n• Chống checkpoint bằng thuật toán cuộn trang ngẫu nhiên.",
            "img_file": "03_dang_bai_nhom_facebook.png"
        },
        {
            "stt": "TÍNH NĂNG 4:\n📷 Đăng Bài & Tương Tác Threads Tự Động",
            "benefit": "• Đón đầu mỏ vàng lưu lượng miễn phí khổng lồ từ mạng xã hội Threads.\n• Tự động đọc và đăng hàng loạt bài viết từ file Excel Post.xlsx có sẵn.\n• Tự động đính kèm ảnh, video và tự bình luận ghim link mua hàng (Affiliate Link) ngay dưới bài viết.\n• Tự động nuôi tương tác cho kênh Threads phát triển bền vững.",
            "guide": "1. Chuẩn bị file nội dung E:\\Affiliate\\Post.xlsx (hoặc chọn file bất kỳ).\n2. Chọn tài khoản Threads muốn chạy.\n3. Tích chọn 'Chạy trên Microsoft Edge' và bấm 'Bắt Đầu Đăng Hàng Loạt'.",
            "tech": "• Chạy trực tiếp trên Microsoft Edge (v157+).\n• Tự động nhận diện thư mục ảnh tương ứng theo từng dòng Excel.\n• Cơ chế ghim comment affiliate đầu tiên độc quyền.",
            "img_file": "04_dang_bai_threads_marketing.png"
        },
        {
            "stt": "TÍNH NĂNG 5:\n👥 Quản Lý Tài Khoản & Song Song Chrome - Edge",
            "benefit": "• Quản lý không giới hạn tài khoản Facebook và Threads.\n• Lưu phiên đăng nhập vĩnh viễn tại %APPDATA%, không bao giờ bị mất tài khoản khi cập nhật phần mềm.\n• ĐẶC BIỆT: Chạy song song 2 trình duyệt độc lập (Facebook trên Chrome nửa trái màn hình, Threads trên Edge nửa phải màn hình) không hề xung đột cổng hay tài nguyên!",
            "guide": "1. Bấm 'Thêm Tài Khoản' và đăng nhập trực tiếp trên trình duyệt sạch.\n2. Kiểm tra trạng thái Live/Cookie của tài khoản bằng 1 click.\n3. Khởi động cùng lúc cả FB và Threads để nhân đôi hiệu suất làm việc.",
            "tech": "• Tham số Playwright --remote-debugging-port=0 độc lập.\n• Cửa sổ tự động chia 2 nửa màn hình (960x1030 px) trực quan.\n• Hỗ trợ 3 loại trình duyệt: Chrome, Edge, Chromium.",
            "img_file": "05_quan_ly_tai_khoan_facebook.png"
        }
    ]

    r_f = 5
    for idx, feat in enumerate(features_info):
        # Header tính năng
        ws4.cell(row=r_f, column=1, value=feat["stt"]).fill = fill_indigo
        ws4.cell(row=r_f, column=1).font = font_section
        ws4.cell(row=r_f, column=1).alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws4.cell(row=r_f, column=1).border = thin_border

        ws4.cell(row=r_f, column=2, value=feat["benefit"]).fill = fill_white
        ws4.cell(row=r_f, column=2).font = font_normal
        ws4.cell(row=r_f, column=2).alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws4.cell(row=r_f, column=2).border = thin_border

        ws4.cell(row=r_f, column=3, value=feat["guide"]).fill = fill_light
        ws4.cell(row=r_f, column=3).font = font_normal
        ws4.cell(row=r_f, column=3).alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws4.cell(row=r_f, column=3).border = thin_border

        ws4.cell(row=r_f, column=4, value=feat["tech"]).fill = fill_white
        ws4.cell(row=r_f, column=4).font = font_normal
        ws4.cell(row=r_f, column=4).alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws4.cell(row=r_f, column=4).border = thin_border

        # Cột 5 để chèn ảnh
        c5 = ws4.cell(row=r_f, column=5)
        c5.value = ""
        c5.fill = fill_light
        c5.border = thin_border

        # Đặt chiều cao hàng đủ rộng để chứa ảnh đẹp mắt
        ws4.row_dimensions[r_f].height = 220

        # Chèn ảnh chụp ứng dụng
        img_path = os.path.join(screenshots_dir, feat["img_file"])
        if os.path.exists(img_path):
            img = Image(img_path)
            # Kích thước ảnh chuẩn tỉ lệ 16:10 hiển thị cực đẹp trong cell
            img.width = 460
            img.height = 280
            cell_coord = f"E{r_f}"
            ws4.add_image(img, cell_coord)

        r_f += 1

    col_widths4 = [22, 38, 36, 32, 65]
    for i, w in enumerate(col_widths4, 1):
        ws4.column_dimensions[get_column_letter(i)].width = w

    # Lưu file Excel ra D:\ToolsHN và Desktop
    wb.save(output_xlsx_path)
    wb.save(desktop_xlsx_path)
    print(f"Excel created successfully:\n- {output_xlsx_path}\n- {desktop_xlsx_path}")

if __name__ == "__main__":
    build_excel_marketing_kit()
