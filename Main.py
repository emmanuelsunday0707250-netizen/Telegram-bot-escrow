import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
import uvicorn
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from supabase import create_client, Client

# --- CONFIGURATION FROM ENVIRONMENT VARIABLES ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

# Admin Info
ADMIN_USERNAME = "Databotsupport"
ADMIN_TELEGRAM_ID = 8750800302

# Telegram Application Setup
tg_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build() if TELEGRAM_BOT_TOKEN else None

# --- ADMIN COMMANDS ---
async def promote_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: /promote <listing_id>"""
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        await update.message.reply_text("⛔ Unauthorized command.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /promote <listing_id>")
        return

    listing_id = context.args[0]
    if supabase:
        supabase.table("listings").update({"is_promoted": True}).eq("id", listing_id).execute()
    await update.message.reply_text(f"✅ Listing #{listing_id} has been PINNED to the top!")

async def unpromote_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: /unpromote <listing_id>"""
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        return

    if not context.args:
        await update.message.reply_text("Usage: /unpromote <listing_id>")
        return

    listing_id = context.args[0]
    if supabase:
        supabase.table("listings").update({"is_promoted": False}).eq("id", listing_id).execute()
    await update.message.reply_text(f"🔴 Listing #{listing_id} has been unpinned.")

if tg_app:
    tg_app.add_handler(CommandHandler("promote", promote_command))
    tg_app.add_handler(CommandHandler("unpromote", unpromote_command))


# --- FASTAPI LIFECYCLE MANAGEMENT ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    if tg_app and RENDER_EXTERNAL_URL:
        webhook_url = f"{RENDER_EXTERNAL_URL.rstrip('/')}/webhook/telegram"
        await tg_app.bot.set_webhook(url=webhook_url)
        await tg_app.initialize()
        await tg_app.start()
    yield
    if tg_app:
        await tg_app.stop()
        await tg_app.shutdown()

app = FastAPI(lifespan=lifespan)


# --- WEBHOOK ENDPOINTS ---
@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """Receives incoming updates from Telegram instantly."""
    if tg_app:
        data = await request.json()
        update = Update.de_json(data, tg_app.bot)
        await tg_app.process_update(update)
    return Response(status_code=200)

@app.post("/webhook/paystack")
async def paystack_webhook(request: Request):
    """Fast Paystack webhook endpoint preventing timeout errors."""
    payload = await request.json()
    if payload.get("event") == "charge.success":
        data = payload.get("data")
        asyncio.create_task(process_payment_background(data))
    return Response(status_code=200)

async def process_payment_background(data):
    """Updates Supabase safely in the background after returning 200 OK to Paystack."""
    try:
        reference = data.get("reference")
        if supabase:
            supabase.table("listings").update({"status": "paid"}).eq("payment_reference", reference).execute()
            print(f"✅ Payment reference {reference} updated to paid in background!")
    except Exception as e:
        print(f"❌ Background payment error: {e}")

@app.get("/")
async def health_check():
    return {"status": "ok", "service": "Telegram Bot & Webhook active"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
