import os
import json
import base64
import logging
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
GEMINI_KEY = os.environ.get("GEMINI_KEY", "")
GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-1.5-flash-latest",
    "gemini-1.5-flash",
]

# ── User session state ──
user_state = {}

INSTRUMENTS = [
    "Volatility 10 Index", "Volatility 25 Index", "Volatility 50 Index",
    "Volatility 75 Index", "Volatility 100 Index",
    "Boom 500 Index", "Boom 1000 Index",
    "Crash 500 Index", "Crash 1000 Index",
    "Step Index", "Range Break 100 Index",
]
TIMEFRAMES = ["M1", "M5", "M15", "H1", "H4", "D1", "W1", "Multi TF (Top-Down)"]
MODES = [
    "Full Trade Plan", "Entry Signal", "Liquidity Sweep Detection",
    "RSI Divergence", "S/R Mapping", "BOS Analysis",
]


def get_state(uid):
    if uid not in user_state:
        user_state[uid] = {
            "instrument": "Volatility 50 Index",
            "timeframe": "M5",
            "mode": "Full Trade Plan",
            "images": [],
            "step": "idle",
        }
    return user_state[uid]


# ── /start ──
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = get_state(uid)
    state["step"] = "idle"
    state["images"] = []

    text = (
        "📊 *NEXUS AI — Chart Analyzer*\n"
        "_Powered by Gemini AI · Built for Synthetic Indices_\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Send me your *MT5 chart screenshot* and I will give you:\n\n"
        "✅ Bias direction (Bull/Bear)\n"
        "✅ RSI analysis with MA crossover\n"
        "✅ Key levels — Entry, SL, TP1, TP2\n"
        "✅ Liquidity sweep detection\n"
        "✅ Full ICT-based trade plan\n"
        "✅ Risk/Reward ratio\n"
        "✅ Execution checklist\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Use the buttons below to configure, then send your chart!\n\n"
        "📌 *Current settings:*\n"
        f"  Instrument: `{state['instrument']}`\n"
        f"  Timeframe: `{state['timeframe']}`\n"
        f"  Mode: `{state['mode']}`"
    )

    kb = [
        [InlineKeyboardButton("🎯 Set Instrument", callback_data="set_instrument"),
         InlineKeyboardButton("⏱ Set Timeframe", callback_data="set_timeframe")],
        [InlineKeyboardButton("🔬 Set Mode", callback_data="set_mode")],
        [InlineKeyboardButton("📸 How to use", callback_data="howto")],
    ]
    await update.message.reply_text(text, parse_mode="Markdown",
                                     reply_markup=InlineKeyboardMarkup(kb))


# ── Callbacks ──
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    state = get_state(uid)
    data = query.data

    if data == "set_instrument":
        kb = [[InlineKeyboardButton(i, callback_data=f"inst_{i}")] for i in INSTRUMENTS]
        kb.append([InlineKeyboardButton("◀ Back", callback_data="back_main")])
        await query.edit_message_text("🎯 *Select Instrument:*", parse_mode="Markdown",
                                       reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("inst_"):
        state["instrument"] = data[5:]
        await show_main(query, state)

    elif data == "set_timeframe":
        kb = [[InlineKeyboardButton(t, callback_data=f"tf_{t}")] for t in TIMEFRAMES]
        kb.append([InlineKeyboardButton("◀ Back", callback_data="back_main")])
        await query.edit_message_text("⏱ *Select Timeframe:*", parse_mode="Markdown",
                                       reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("tf_"):
        state["timeframe"] = data[3:]
        await show_main(query, state)

    elif data == "set_mode":
        kb = [[InlineKeyboardButton(m, callback_data=f"mode_{m}")] for m in MODES]
        kb.append([InlineKeyboardButton("◀ Back", callback_data="back_main")])
        await query.edit_message_text("🔬 *Select Analysis Mode:*", parse_mode="Markdown",
                                       reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("mode_"):
        state["mode"] = data[5:]
        await show_main(query, state)

    elif data == "back_main":
        await show_main(query, state)

    elif data == "howto":
        text = (
            "📸 *How to use NEXUS:*\n\n"
            "1️⃣ Configure your *Instrument* and *Timeframe*\n"
            "2️⃣ Open your MT5 chart\n"
            "3️⃣ Take a *screenshot* of the chart\n"
            "4️⃣ Send the screenshot directly to this bot\n"
            "5️⃣ NEXUS reads the chart and gives you the full analysis\n\n"
            "💡 *Tips:*\n"
            "• For top-down analysis, send *multiple screenshots* one by one\n"
            "  then send the command /analyze\n"
            "• Make sure RSI indicator is visible on chart\n"
            "• Clear screenshots give better results\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "_Supports all Deriv synthetic indices_"
        )
        kb = [[InlineKeyboardButton("◀ Back", callback_data="back_main")]]
        await query.edit_message_text(text, parse_mode="Markdown",
                                       reply_markup=InlineKeyboardMarkup(kb))

    elif data == "analyze_now":
        await query.edit_message_text("⏳ Running analysis... please wait.")
        await run_analysis(query.message, state, uid, ctx)


async def show_main(query, state):
    text = (
        "📊 *NEXUS AI — Ready*\n\n"
        "📌 *Current settings:*\n"
        f"  Instrument: `{state['instrument']}`\n"
        f"  Timeframe: `{state['timeframe']}`\n"
        f"  Mode: `{state['mode']}`\n\n"
        f"  Charts queued: `{len(state['images'])}`\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Send your chart screenshot now, or configure below:"
    )
    kb = [
        [InlineKeyboardButton("🎯 Instrument", callback_data="set_instrument"),
         InlineKeyboardButton("⏱ Timeframe", callback_data="set_timeframe")],
        [InlineKeyboardButton("🔬 Mode", callback_data="set_mode"),
         InlineKeyboardButton("📸 How to", callback_data="howto")],
    ]
    if state["images"]:
        kb.insert(0, [InlineKeyboardButton(
            f"▶ ANALYZE NOW ({len(state['images'])} chart{'s' if len(state['images'])>1 else ''})",
            callback_data="analyze_now"
        )])
    await query.edit_message_text(text, parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup(kb))


# ── Photo handler ──
async def photo_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = get_state(uid)

    # Download the photo
    photo = update.message.photo[-1]
    file = await ctx.bot.get_file(photo.file_id)
    
    async with httpx.AsyncClient() as client:
        resp = await client.get(file.file_path)
        img_bytes = resp.content

    b64 = base64.b64encode(img_bytes).decode()
    state["images"].append(b64)

    n = len(state["images"])
    text = (
        f"✅ *Chart {n} received!*\n\n"
        f"  Instrument: `{state['instrument']}`\n"
        f"  Timeframe: `{state['timeframe']}`\n"
        f"  Mode: `{state['mode']}`\n\n"
    )

    if n == 1:
        text += "Send more charts for top-down analysis, or tap *Analyze* now:"
    else:
        text += f"You have {n} charts queued. Send more or tap *Analyze*:"

    kb = [
        [InlineKeyboardButton(f"▶ ANALYZE NOW ({n} chart{'s' if n>1 else ''})",
                               callback_data="analyze_now")],
        [InlineKeyboardButton("🔄 Reset Charts", callback_data="reset_charts"),
         InlineKeyboardButton("⚙️ Settings", callback_data="back_main")],
    ]
    await update.message.reply_text(text, parse_mode="Markdown",
                                     reply_markup=InlineKeyboardMarkup(kb))


# ── /analyze command ──
async def analyze_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = get_state(uid)
    if not state["images"]:
        await update.message.reply_text("❌ No charts queued. Please send a screenshot first.")
        return
    msg = await update.message.reply_text("⏳ Analyzing your chart(s)...")
    await run_analysis(msg, state, uid, ctx)


# ── Core analysis ──
async def run_analysis(msg, state, uid, ctx):
    images = state["images"]
    instrument = state["instrument"]
    timeframe = state["timeframe"]
    mode = state["mode"]

    prompt = f"""You are an expert technical analyst specializing in ICT concepts, synthetic indices, liquidity sweeps, RSI divergence, and MetaTrader 5 price action trading.

Analyze the provided MT5 chart screenshot(s):
- Instrument: {instrument}
- Timeframe: {timeframe}
- Analysis Mode: {mode}
- Trading Style: Intraday / Scalping

Apply ICT methodology: identify liquidity sweeps, stop hunts, break of structure (BOS), displacement, premium/discount zones, buyside/sellside liquidity, orderblocks where visible.

Return ONLY valid JSON, no markdown, no backticks:

{{"instrument":"{instrument}","timeframe":"{timeframe}","currentPrice":"string","bias":"BULLISH or BEARISH or NEUTRAL","biasStrength":"STRONG or MODERATE or WEAK","patternDetected":"string","summary":"2-3 sentence summary","rsi":{{"value":0,"ma9":0,"ma21":0,"condition":"OVERSOLD or OVERBOUGHT or NEUTRAL or RECOVERING or DECLINING"}},"timeframes":[{{"tf":"W1","bias":"BULL or BEAR or NEUT","rsi":0,"note":"string"}},{{"tf":"D1","bias":"BULL","rsi":0,"note":"string"}},{{"tf":"H4","bias":"BULL","rsi":0,"note":"string"}},{{"tf":"H1","bias":"BULL","rsi":0,"note":"string"}},{{"tf":"M5","bias":"BULL","rsi":0,"note":"string"}}],"keyLevels":{{"entry":"string","stopLoss":"string","tp1":"string","tp2":"string","resistance":"string","support":"string"}},"riskReward":{{"riskPoints":"string","rewardTp1":"string","ratio":"string"}},"confluence":[{{"factor":"string","aligned":true}}],"executionSteps":[{{"title":"string","detail":"string","action":"BUY or SELL or WAIT or MANAGE"}}],"invalidation":"string","fullAnalysis":"5-7 sentence detailed analysis using ICT terminology"}}"""

    # Try Gemini models
    parts = [{"inline_data": {"mime_type": "image/jpeg", "data": b}} for b in images]
    parts.append({"text": prompt})

    result = None
    error_msg = ""

    async with httpx.AsyncClient(timeout=60) as client:
        for model in GEMINI_MODELS:
            try:
                resp = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_KEY}",
                    json={"contents": [{"parts": parts}],
                          "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048}}
                )
                data = resp.json()
                if "error" in data:
                    error_msg = data["error"].get("message", "Unknown error")
                    continue
                raw = data["candidates"][0]["content"]["parts"][0]["text"]
                raw = raw.replace("```json", "").replace("```", "").strip()
                result = json.loads(raw)
                break
            except Exception as e:
                error_msg = str(e)
                continue

    if not result:
        await ctx.bot.send_message(
            chat_id=msg.chat_id,
            text=f"❌ Analysis failed: {error_msg}\n\nCheck your GEMINI_KEY in environment variables."
        )
        state["images"] = []
        return

    # Format and send result
    output = format_result(result)
    
    # Send in chunks if too long
    chunks = split_message(output)
    for i, chunk in enumerate(chunks):
        await ctx.bot.send_message(
            chat_id=msg.chat_id,
            text=chunk,
            parse_mode="Markdown"
        )

    # Reset images after analysis
    state["images"] = []

    # Send action buttons
    kb = [
        [InlineKeyboardButton("📊 Analyze Another Chart", callback_data="back_main")],
        [InlineKeyboardButton("⚙️ Change Settings", callback_data="set_instrument")],
    ]
    await ctx.bot.send_message(
        chat_id=msg.chat_id,
        text="✅ *Analysis complete!* Send another chart anytime.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )


def format_result(r):
    bias = r.get("bias", "NEUTRAL")
    bias_icon = "🟢" if bias == "BULLISH" else "🔴" if bias == "BEARISH" else "🟡"
    strength = r.get("biasStrength", "")
    pattern = r.get("patternDetected", "")
    price = r.get("currentPrice", "—")
    
    rsi = r.get("rsi", {})
    rsi_val = rsi.get("value", "—")
    rsi_ma9 = rsi.get("ma9", "—")
    rsi_ma21 = rsi.get("ma21", "—")
    rsi_cond = rsi.get("condition", "—")

    kl = r.get("keyLevels", {})
    rr = r.get("riskReward", {})

    tfs = r.get("timeframes", [])
    tf_lines = ""
    for t in tfs:
        b = t.get("bias", "NEUT")
        icon = "🟢" if b == "BULL" else "🔴" if b == "BEAR" else "🟡"
        tf_lines += f"  {icon} `{t.get('tf','?')}` — RSI {t.get('rsi','?')} · {t.get('note','')}\n"

    conf = r.get("confluence", [])
    conf_lines = ""
    for c in conf:
        icon = "✅" if c.get("aligned") else "❌"
        conf_lines += f"  {icon} {c.get('factor','')}\n"

    steps = r.get("executionSteps", [])
    step_lines = ""
    action_icons = {"BUY": "🟢", "SELL": "🔴", "WAIT": "⏳", "MANAGE": "⚙️"}
    for i, s in enumerate(steps, 1):
        icon = action_icons.get(s.get("action", "WAIT"), "▶")
        step_lines += f"  {i}. {icon} *{s.get('title','')}*\n     {s.get('detail','')}\n"

    output = f"""
{bias_icon} *NEXUS AI — CHART ANALYSIS*
━━━━━━━━━━━━━━━━━━━━

📌 *{r.get('instrument','?')} · {r.get('timeframe','?')}*
💰 Price: `{price}`
📊 Bias: *{bias}* ({strength})
🔍 Pattern: _{pattern}_

━━━━━━━━━━━━━━━━━━━━
📈 *TIMEFRAME BREAKDOWN*
{tf_lines}
━━━━━━━━━━━━━━━━━━━━
📉 *RSI MOMENTUM*
  Value: `{rsi_val}` — {rsi_cond}
  MA(9): `{rsi_ma9}` | MA(21): `{rsi_ma21}`

━━━━━━━━━━━━━━━━━━━━
🎯 *KEY LEVELS*
  Entry:      `{kl.get('entry','—')}`
  Stop Loss:  `{kl.get('stopLoss','—')}`
  TP1 (50%):  `{kl.get('tp1','—')}`
  TP2 (50%):  `{kl.get('tp2','—')}`
  Resistance: `{kl.get('resistance','—')}`
  Support:    `{kl.get('support','—')}`

━━━━━━━━━━━━━━━━━━━━
⚖️ *RISK / REWARD*
  Risk:    `{rr.get('riskPoints','—')} pts`
  Reward:  `{rr.get('rewardTp1','—')} pts`
  Ratio:   *{rr.get('ratio','—')}*

━━━━━━━━━━━━━━━━━━━━
🔗 *CONFLUENCE*
{conf_lines}
━━━━━━━━━━━━━━━━━━━━
📋 *EXECUTION STEPS*
{step_lines}
━━━━━━━━━━━━━━━━━━━━
⚠️ *INVALIDATION*
  _{r.get('invalidation','—')}_

━━━━━━━━━━━━━━━━━━━━
📝 *FULL ANALYSIS*
{r.get('summary','')}

{r.get('fullAnalysis','')}

━━━━━━━━━━━━━━━━━━━━
_⚠ Educational purposes only · Not financial advice_
"""
    return output.strip()


def split_message(text, limit=4000):
    if len(text) <= limit:
        return [text]
    parts = []
    while len(text) > limit:
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        parts.append(text[:split_at])
        text = text[split_at:].lstrip()
    if text:
        parts.append(text)
    return parts


# ── Reset callback ──
async def reset_callback(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    state = get_state(uid)
    state["images"] = []
    await query.edit_message_text("🔄 Charts cleared. Send a new screenshot!")


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable not set!")
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analyze", analyze_command))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(CallbackQueryHandler(reset_callback, pattern="^reset_charts$"))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("NEXUS Bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
