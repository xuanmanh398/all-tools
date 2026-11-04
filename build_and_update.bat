@echo off
chcp 65001 >nul
set NODE_OPTIONS=
title Đang Đóng Gói Và Cập Nhật Auto Post v1.0

echo ========================================================
echo       ĐÓNG GÓI VÀ CẬP NHẬT AUTO POST - PHIÊN BẢN MỚI
echo ========================================================
echo.

echo [1/4] Đang đóng các tiến trình cũ để tránh bị khóa file...
taskkill /F /IM "Auto Post.exe" /T >nul 2>&1
taskkill /F /IM "node.exe" /T >nul 2>&1

echo [2/4] Đang biên dịch mã nguồn với PyInstaller...
call .venv\Scripts\activate.bat 2>nul
pyinstaller AutoPost.spec --noconfirm
if errorlevel 1 (
    echo [LỖI] Không thể đóng gói với PyInstaller. Vui lòng kiểm tra Python/PyInstaller!
    pause
    exit /b 1
)

echo.
echo [3/4] Đang tạo bộ cài đặt Inno Setup Installer...
set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"

if exist %ISCC% (
    %ISCC% AutoPost_Setup.iss
    echo [THÀNH CÔNG] Đã tạo file cài đặt: installer_output\AutoPost_Setup_v1.0.exe
) else (
    echo [CẢNH BÁO] Không tìm thấy Inno Setup Compiler. Bỏ qua bước tạo Setup.exe.
)

echo.
echo [4/4] Đang đồng bộ phiên bản mới vào C:\Program Files\Auto Post...
if exist "C:\Program Files\Auto Post" (
    xcopy /E /I /Y "dist\Auto Post\*" "C:\Program Files\Auto Post\" >nul 2>&1
    if errorlevel 1 (
        echo [LƯU Ý] Không thể ghi đè trực tiếp vào C:\Program Files do cần quyền Admin.
        echo Bạn chỉ cần chạy file cài đặt mới: installer_output\AutoPost_Setup_v1.0.exe
    ) else (
        echo [HOÀN TẤT] Đã cập nhật thành công C:\Program Files\Auto Post!
    )
)

echo.
echo ========================================================
echo              CẬP NHẬT HOÀN TẤT THÀNH CÔNG!
echo ========================================================
echo Bạn có thể mở ứng dụng ngay bằng cách:
echo 1. Chạy file installer_output\AutoPost_Setup_v1.0.exe (Khuyên dùng)
echo 2. Hoặc mở trực tiếp từ menu Start / Desktop!
echo.
pause
