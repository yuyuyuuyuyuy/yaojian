# -*- coding: utf-8 -*-
"""
作品集提交文件生成器
====================
产出（输出目录：D:\\wibecoding\\作品集提交文件\\）：
  1. 作品集-张思晖.pdf          —— 三页网站打印排版合并（投递必交物）
  2. 作品集-张思晖-网页版.zip    —— 完整网站打包（微信/网盘备选）

用法：双击「作品集提交文件/生成作品集.bat」或直接运行本脚本。
依赖：本机 Edge 浏览器（无头打印）+ pypdf（pip install pypdf）。
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

import pypdf

PORTFOLIO_DIR = r"D:\wibecoding\app_public\docs\portfolio"
OUT_DIR = r"D:\wibecoding\作品集提交文件"
NAME = "作品集-张思晖"

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

PAGES = [
    ("index.html", "01_总站"),
    ("yaojian.html", "02_药鉴"),
    ("haigou.html", "03_海淘管家"),
]

ZIP_EXCLUDE = {"个人简历.pdf"}  # 简历仅随投递提交，不打入网页包


def find_browser():
    for p in EDGE_CANDIDATES:
        if os.path.exists(p):
            return p
    print("[错误] 未找到 Edge/Chrome，无法生成 PDF。")
    sys.exit(1)


def print_to_pdf(browser, html_name, out_pdf, profile_dir):
    url = "file:///" + os.path.join(PORTFOLIO_DIR, html_name).replace("\\", "/")
    cmd = [
        browser,
        "--headless", "--disable-gpu", "--no-sandbox",
        "--no-first-run", "--no-default-browser-check",
        "--user-data-dir=" + profile_dir,
        "--no-pdf-header-footer",
        "--print-to-pdf=" + out_pdf,
        url,
    ]
    subprocess.run(cmd, capture_output=True, timeout=180)
    # Edge 启动器进程可能先于 PDF 写入退出，轮询等待文件落盘（最多 30 秒）
    for _ in range(60):
        if os.path.exists(out_pdf) and os.path.getsize(out_pdf) >= 1000:
            return
        time.sleep(0.5)
    print(f"[错误] {html_name} 打印失败（30 秒内未生成 PDF）")
    sys.exit(1)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    browser = find_browser()
    workdir = tempfile.mkdtemp(prefix="pf-build-")
    profile = os.path.join(workdir, "edge-profile")
    try:
        # 1) 三页分别打印
        pdf_parts = []
        print("生成 PDF 分页……")
        for html_name, label in PAGES:
            out = os.path.join(workdir, label + ".pdf")
            print_to_pdf(browser, html_name, out, profile)
            pdf_parts.append((label, out))
            print(f"  ✓ {html_name} -> {label}.pdf ({os.path.getsize(out)/1024:.0f}KB)")

        # 2) 合并
        merged = os.path.join(OUT_DIR, NAME + ".pdf")
        writer = pypdf.PdfWriter()
        for label, path in pdf_parts:
            writer.append(path)
        with open(merged, "wb") as f:
            writer.write(f)
        print(f"  ✓ 合并完成：{merged}（{os.path.getsize(merged)/1024/1024:.1f}MB，{len(writer.pages)} 页）")

        # 3) 网页版 ZIP
        zip_path = os.path.join(OUT_DIR, NAME + "-网页版.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for root, _, files in os.walk(PORTFOLIO_DIR):
                for fn in sorted(files):
                    if fn in ZIP_EXCLUDE:
                        continue
                    full = os.path.join(root, fn)
                    rel = os.path.join("portfolio", os.path.relpath(full, PORTFOLIO_DIR))
                    z.write(full, rel)
        print(f"  ✓ 网页包完成：{zip_path}（{os.path.getsize(zip_path)/1024/1024:.1f}MB）")
        print("\n全部完成。提交时上传 PDF；微信/网盘场景可用 ZIP。")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
