import os
import shutil
import zipfile

def package():
    dist_dir = os.path.join("dist", "FB_Group_AutoPoster")
    if not os.path.exists(dist_dir):
        print(f"[ERROR] Directory {dist_dir} does not exist. Build PyInstaller first!")
        return

    # 1. Copy ONLY chromium-XXXX from ms-playwright to save space
    user_profile = os.environ.get("USERPROFILE", "")
    src_playwright = os.path.join(user_profile, "AppData", "Local", "ms-playwright")
    dest_playwright = os.path.join(dist_dir, "ms-playwright")

    if os.path.exists(src_playwright):
        print(f"[INFO] Optimizing & copying Playwright Chromium browsers from {src_playwright} to {dest_playwright}...")
        if os.path.exists(dest_playwright):
            shutil.rmtree(dest_playwright)
        os.makedirs(dest_playwright, exist_ok=True)
        
        for item in os.listdir(src_playwright):
            src_item = os.path.join(src_playwright, item)
            # Copy both chromium-XXXX and chromium_headless_shell-XXXX folders
            if os.path.isdir(src_item) and (item.startswith("chromium-") or item.startswith("chromium_headless_shell-")):
                dest_item = os.path.join(dest_playwright, item)
                print(f"[INFO] Copying {item}...")
                shutil.copytree(src_item, dest_item)

        print("[SUCCESS] Playwright Chromium optimized and bundled!")

    # 2. Ensure sessions folder exists
    os.makedirs(os.path.join(dist_dir, "sessions"), exist_ok=True)

    # 3. Create Offline Compact Zip package (~180MB)
    zip_offline = "FB_Group_AutoPoster_Offline_Compact.zip"
    print(f"[INFO] Creating zip archive {zip_offline}...")
    with zipfile.ZipFile(zip_offline, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zipf:
        for root, dirs, files in os.walk(dist_dir):
            for file in files:
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, start=dist_dir)
                zipf.write(abs_path, arcname=os.path.join("FB_Group_AutoPoster", rel_path))

    print(f"[COMPLETED] Offline Compact Zip created: {os.path.abspath(zip_offline)}")

    # 4. Create Ultra-Lightweight Zip package (Without ms-playwright, ~70MB)
    zip_light = "FB_Group_AutoPoster_UltraLight.zip"
    print(f"[INFO] Creating ultra-lightweight zip archive {zip_light} (Chromium auto-downloads on 1st run)...")
    with zipfile.ZipFile(zip_light, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zipf:
        for root, dirs, files in os.walk(dist_dir):
            # Skip ms-playwright directory for light version
            if "ms-playwright" in root:
                continue
            for file in files:
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, start=dist_dir)
                zipf.write(abs_path, arcname=os.path.join("FB_Group_AutoPoster", rel_path))

    print(f"[COMPLETED] Ultra-Lightweight Zip created: {os.path.abspath(zip_light)}")

if __name__ == "__main__":
    package()
