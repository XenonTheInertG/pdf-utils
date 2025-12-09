#!/usr/bin/env python3
"""
Telegram PDF Utility Bot - v20+ (async)
- Queue system
- Progress bar
- Page count
- Compress, split, merge, rotate, extract
- Remove watermark using keywords from .env or GitHub Secrets
"""

import os
import time
import fitz  # PyMuPDF
from queue import Queue
from threading import Thread
from functools import wraps
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
)
from PyPDF2 import PdfReader, PdfWriter

# ----------------------------
# Load environment variables
# ----------------------------
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
WATERMARK_KEYWORDS = [k.strip().upper() for k in os.getenv("WATERMARK_KEYWORDS", "").split(",") if k.strip()]

# ----------------------------
# Global vars
# ----------------------------
WORK = "pdf_files"
MERGE_QUEUE = []
os.makedirs(WORK, exist_ok=True)
job_queue = Queue()

# ----------------------------
# Helpers
# ----------------------------
def human_readable_size(num_bytes):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if num_bytes < 1024.0:
            return f"{num_bytes:3.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"

def get_page_count(pdf_path):
    try:
        reader = PdfReader(pdf_path)
        return len(reader.pages)
    except:
        return None

def progress_bar(message, total_steps=30, action="Processing", speed=0.08):
    bar_length = 20
    for step in range(1, total_steps + 1):
        filled = int(bar_length * step / total_steps)
        bar = "█" * filled + "-" * (bar_length - filled)
        percent = int((step / total_steps) * 100)
        text = f"{action}: [{bar}] {percent}%"
        try:
            message.edit_text(text)
        except:
            pass
        time.sleep(speed)

# ----------------------------
# PDF operations
# ----------------------------
def remove_watermark(input_pdf, output_pdf, keywords=None):
    if keywords is None:
        keywords = WATERMARK_KEYWORDS
    doc = fitz.open(input_pdf)
    for page in doc:
        try:
            blocks = page.get_text("dict")["blocks"]
            for block in blocks:
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "").upper()
                        if any(k in text for k in keywords):
                            bbox = span.get("bbox")
                            if bbox:
                                page.add_redact_annot(bbox, fill=(1,1,1))
        except:
            pass
        try:
            images = page.get_images(full=True)
            for img in images:
                try:
                    page.delete_image(img[0])
                except:
                    pass
        except:
            pass
        try:
            page.apply_redactions()
        except:
            pass
    doc.save(output_pdf)
    doc.close()

def compress_pdf(input_pdf, output_pdf):
    doc = fitz.open(input_pdf)
    try:
        doc.save(output_pdf, garbage=4, deflate=True, clean=True)
    except:
        reader = PdfReader(input_pdf)
        writer = PdfWriter()
        for p in reader.pages:
            writer.add_page(p)
        with open(output_pdf, "wb") as f:
            writer.write(f)
    finally:
        doc.close()

def split_pdf(input_pdf, out_folder):
    reader = PdfReader(input_pdf)
    out_paths = []
    for i, page in enumerate(reader.pages, start=1):
        writer = PdfWriter()
        writer.add_page(page)
        out_path = os.path.join(out_folder, f"page_{i}.pdf")
        with open(out_path, "wb") as f:
            writer.write(f)
        out_paths.append(out_path)
    return out_paths

def merge_pdfs(file_list, output_path):
    writer = PdfWriter()
    for file in file_list:
        reader = PdfReader(file)
        for p in reader.pages:
            writer.add_page(p)
    with open(output_path, "wb") as f:
        writer.write(f)

def rotate_pdf(input_pdf, output_pdf, angle=90):
    reader = PdfReader(input_pdf)
    writer = PdfWriter()
    for page in reader.pages:
        page.rotate(angle)
        writer.add_page(page)
    with open(output_pdf, "wb") as f:
        writer.write(f)

def extract_images(input_pdf, out_folder, dpi=150):
    doc = fitz.open(input_pdf)
    out_files = []
    for i, page in enumerate(doc, start=1):
        pix = page.get_pixmap(dpi=dpi)
        img_path = os.path.join(out_folder, f"page_{i}.png")
        pix.save(img_path)
        out_files.append(img_path)
    doc.close()
    return out_files

# ----------------------------
# Queue system
# ----------------------------
def worker():
    while True:
        task = job_queue.get()
        try:
            task()
        except Exception as e:
            print("Error in job:", e)
        job_queue.task_done()

Thread(target=worker, daemon=True).start()

def enqueue(task_callable):
    job_queue.put(task_callable)

# ----------------------------
# Telegram bot decorators
# ----------------------------
def require_pdf(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        pdf = context.user_data.get("last_pdf")
        if not pdf or not os.path.exists(pdf):
            await update.message.reply_text("Please upload a PDF first.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# ----------------------------
# Handlers
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi dost! PDF Utility Bot ready.\nCommands:\n"
        "/clean – Remove watermark\n/compress – Compress PDF\n/split – Split PDF\n/merge – Add PDF to merge queue\n"
        "/done – Merge PDFs\n/rotate – Rotate pages\n/extract – Extract images\n/status – Last PDF info\n/watermarks – Show keywords"
    )

async def handle_pdf_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc or not doc.file_name.lower().endswith(".pdf"):
        await update.message.reply_text("Please upload a PDF file.")
        return
    safe_name = f"{update.message.from_user.id}_{int(time.time())}_{doc.file_name}"
    local_path = os.path.join(WORK, safe_name)
    await update.message.reply_text("Downloading your PDF...")
    file = await doc.get_file()
    await file.download_to_drive(local_path)
    context.user_data["last_pdf"] = local_path
    pages = get_page_count(local_path)
    size = os.path.getsize(local_path)
    await update.message.reply_text(
        f"📄 PDF received!\n📝 Pages: {pages}\n💾 Size: {human_readable_size(size)}\nSaved as: `{os.path.basename(local_path)}`"
    )

# ----------------------------
# Commands like /clean, /compress etc. remain async
# Example /clean:
# ----------------------------
@require_pdf
async def cmd_clean(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pdf = context.user_data["last_pdf"]
    out = pdf.replace(".pdf", "_clean.pdf")
    async def task():
        msg = await update.message.reply_text("Cleaning PDF...")
        progress_bar(msg, total_steps=8, action="Cleaning", speed=0.08)
        remove_watermark(pdf, out)
        await msg.edit_text("✔ Cleaned! Sending file...")
        await update.message.reply_document(open(out, "rb"))
    enqueue(lambda: asyncio.run(task()))

# ----------------------------
# Main function
# ----------------------------
import asyncio

def main():
    if not TOKEN:
        print("ERROR: BOT_TOKEN not set")
        return
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf_upload))
    app.add_handler(CommandHandler("clean", cmd_clean))
    # Add other commands similarly: compress, split, merge, done, rotate, extract, status, watermarks

    print("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
