import os
import json
import base64
import logging
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
GEMINI_KEY = os.environ.get("GEMINI_KEY", "")

GEMINI_MODELS = ["gemini-2.0-flash", "gemini-1.5-flash-latest", "gemini-1.5-flash"]

INSTRUMENTS = [
    "Volatility 10 Index", "Volatility 25 Index", "Volatility 50 Index",
    "Volatility 75 Index", "Volatility 100 Index", "Boom 500 Index",
    "Boom 1000 Index", "Crash 500 Index", "Crash 1000 Index", "Step Index"
]

TIMEFRAMES = ["M1", "M5", "M15", "H1", "H4", "D1", "W1", "Multi TF"]

MODES = ["Full Trade Plan", "Entry Signal", "Liquidity Sweep", "RSI Divergence", "S/R Mapping"]

user_state = {}


def get_state(uid):
    if uid not in user_state:
        user_state[uid] = {
            "instrument": "Volatility 50 Index",
            "timeframe": "M5",
            "mode": "Full Trade Plan",
            "images": []
        }
    return user_state[uid]


def main_keyboard(state):
    n = len(state["images"])
    kb = []
    if n > 0:
        label = "ANALYZE NOW ({} chart{})".format(n, "s" if n > 1 else "")
        kb.append([InlineKeyboardButton(label, callback_data="analyze_now")])
    kb.append([
        InlineKeyboardButton("Set Instrument", callback_data="set_instrument"),
        InlineKeyboardButton("Set Timeframe", callback_data="set_timeframe")
    ])
    kb.append([
        InlineKeyboardButton("Set Mode", callback_data="set_mode"),
        InlineKeyboardButton("Reset Charts", callback_data="reset_charts")
    ])
    kb.append([InlineKeyboardButton("How to use", callback_data="howto")])
    return InlineKeyboardMarkup(kb)


def main_text(state):
    n = len(state["images"])
    return (
        "NEXUS AI Chart Analyzer\n\n"
        "Settings:\n"
        "  Instrument: {}\n"
        "  Timeframe: {}\n"
        "  Mode: {}\n"
        "  Charts queued: {}\n\n"
        "Send your MT5 screenshot or configure below."
    ).format(state["instrument"], state["timeframe"], state["mode"], n)


async def start(update, ctx):
    uid = update.effective_user.id
    state = get_state(uid)
    state["images"] = []
    await update.message.reply_text(main_text(state), reply_markup=main_keyboard(state))


async def button_handler(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    state = get_state(uid)
    data = query.data

    if data == "set_instrument":
        kb = [[InlineKeyboardButton(i, callback_data="inst_" + i)] for i in INSTRUMENTS]
        kb.append([InlineKeyboardButton("Back", callback_data="back_main")])
        await query.edit_message_text("Select Instrument:", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("inst_"):
        state["instrument"] = data[5:]
        await query.edit_message_text(main_text(state), reply_markup=main_keyboard(state))

    elif data == "set_timeframe":
        kb = [[InlineKeyboardButton(t, callback_data="tf_" + t)] for t in TIMEFRAMES]
        kb.append([InlineKeyboardButton("Back", callback_data="back_main")])
        await query.edit_message_text("Select Timeframe:", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("tf_"):
        state["timeframe"] = data[3:]
        await query.edit_message_text(main_text(state), reply_markup=main_keyboard(state))

    elif data == "set_mode":
        kb = [[InlineKeyboardButton(m, callback_data="mode_" + m)] for m in MODES]
        kb.append([InlineKeyboardButton("Back", callback_data="back_main")])
        await query.edit_message_text("Select Mode:", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("mode_"):
        state["mode"] = data[5:]
        await query.edit_message_text(main_text(state), reply_markup=main_keyboard(state))

    elif data == "back_main":
        await query.edit_message_text(main_text(state), reply_markup=main_keyboard(state))

    elif data == "reset_charts":
        state["images"] = []
        await query.edit_message_text(main_text(state), reply_markup=main_keyboard(state))

    elif data == "howto":
        text = (
            "How to use NEXUS:\n\n"
            "1. Set your Instrument and Timeframe\n"
            "2. Take a screenshot of your MT5 chart\n"
            "3. Send the screenshot here\n"
            "4. Tap ANALYZE NOW\n"
            "5. Get your full trade plan!\n\n"
            "Tip: Send multiple screenshots for top-down analysis."
        )
        kb = [[InlineKeyboardButton("Back", callback_data="back_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "analyze_now":
        await query.edit_message_text("Analyzing your chart... please wait.")
        await run_analysis(query.message, state, ctx)


async def photo_handler(update, ctx):
    uid = update.effective_user.id
    state = get_state(uid)

    photo = update.message.photo[-1]
    tg_file = await ctx.bot.get_file(photo.file_id)

    async with httpx.AsyncClient() as client:
        resp = await client.get(tg_file.file_path)
        img_bytes = resp.content

    b64 = base64.b64encode(img_bytes).decode()
    state["images"].append(b64)
    n = len(state["images"])

    text = "Chart {} received!\n\nInstrument: {}\nTimeframe: {}\nCharts queued: {}\n\nTap Analyze or send more charts.".format(
        n, state["instrument"], state["timeframe"], n
    )
    kb = [
        [InlineKeyboardButton("ANALYZE NOW ({} chart{})".format(n, "s" if n > 1 else ""), callback_data="analyze_now")],
        [InlineKeyboardButton("Reset Charts", callback_data="reset_charts"),
         InlineKeyboardButton("Settings", callback_data="back_main")]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))


async def analyze_command(update, ctx):
    uid = update.effective_user.id
    state = get_state(uid)
    if not state["images"]:
        await update.message.reply_text("No charts queued. Send a screenshot first.")
        return
    msg = await update.message.reply_text("Analyzing...")
    await run_analysis(msg, state, ctx)


async def run_analysis(msg, state, ctx):
    instrument = state["instrument"]
    timeframe = state["timeframe"]
    mode = state["mode"]
    images = state["images"]

    prompt = (
        "You are an expert technical analyst specializing in ICT concepts, synthetic indices, "
        "liquidity sweeps, RSI divergence, and MetaTrader 5 price action trading.\n\n"
        "Analyze the MT5 chart screenshot(s):\n"
        "- Instrument: " + instrument + "\n"
        "- Timeframe: " + timeframe + "\n"
        "- Mode: " + mode + "\n\n"
        "Apply ICT methodology: liquidity sweeps, stop hunts, BOS, displacement, orderblocks.\n\n"
        "Return ONLY valid JSON with no markdown and no extra text:\n"
        '{"instrument":"string","timeframe":"string","currentPrice":"string","bias":"BULLISH or BEARISH or NEUTRAL","biasStrength":"STRONG or MODERATE or WEAK","patternDetected":"string","summary":"string","rsi":{"value":0,"ma9":0,"ma21":0,"condition":"string"},"timeframes":[{"tf":"W1","bias":"BULL or BEAR or NEUT","rsi":0,"note":"string"},{"tf":"D1","bias":"BULL","rsi":0,"note":"string"},{"tf":"H4","bias":"BULL","rsi":0,"note":"string"},{"tf":"H1","bias":"BULL","rsi":0,"note":"string"},{"tf":"M5","bias":"BULL","rsi":0,"note":"string"}],"keyLevels":{"entry":"string","stopLoss":"string","tp1":"string","tp2":"string","resistance":"string","support":"string"},"riskReward":{"riskPoints":"string","rewardTp1":"string","ratio":"string"},"confluence":[{"factor":"string","aligned":true}],"executionSteps":[{"title":"string","detail":"string","action":"BUY or SELL or WAIT or MANAGE"}],"invalidation":"string","fullAnalysis":"string"}'
    )

    parts = [{"inline_data": {"mime_type": "image/jpeg", "data": b}} for b in images]
    parts.append({"text": prompt})

    result = None
    error_msg = "Unknown error"

    async with httpx.AsyncClient(timeout=60) as client:
        for model in GEMINI_MODELS:
            try:
                resp = await client.post(
                    "https://generativelanguage.googleapis.com/v1beta/models/" + model + ":generateContent?key=" + GEMINI_KEY,
                    json={"contents": [{"parts": parts}], "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048}}
                )
                data = resp.json()
                if "error" in data:
                    error_msg = data["error"].get("message", "API error")
                    continue
                raw = data["candidates"][0]["content"]["parts"][0]["text"]
                raw = raw.replace("```json", "").replace("```", "").strip()
                result = json.loads(raw)
                break
            except Exception as e:
                error_msg = str(e)

    state["images"] = []

    if not result:
        await ctx.bot.send_message(chat_id=msg.chat_id, text="Analysis failed: " + error_msg)
        return

    output = format_result(result)
    for chunk in split_message(output):
        await ctx.bot.send_message(chat_id=msg.chat_id, text=chunk)

    kb = [[InlineKeyboardButton("Analyze Another Chart", callback_data="back_main")]]
    await ctx.bot.send_message(
        chat_id=msg.chat_id,
        text="Analysis complete! Send another chart anytime.",
        reply_markup=InlineKeyboardMarkup(kb)
    )


def format_result(r):
    bias = r.get("bias", "NEUTRAL")
    icon = "UP" if bias == "BULLISH" else "DOWN" if bias == "BEARISH" else "NEUTRAL"
    kl = r.get("keyLevels", {})
    rr = r.get("riskReward", {})
    rsi = r.get("rsi", {})

    tf_lines = ""
    for t in r.get("timeframes", []):
        b = t.get("bias", "NEUT")
        arrow = "UP" if b == "BULL" else "DOWN" if b == "BEAR" else "NEUT"
        tf_lines += "  {} {} - RSI {} - {}\n".format(arrow, t.get("tf", "?"), t.get("rsi", "?"), t.get("note", ""))

    conf_lines = ""
    for c in r.get("confluence", []):
        check = "YES" if c.get("aligned") else "NO"
        conf_lines += "  [{}] {}\n".format(check, c.get("factor", ""))

    step_lines = ""
    for i, s in enumerate(r.get("executionSteps", []), 1):
        step_lines += "  {}. {} - {}\n     {}\n".format(i, s.get("action", ""), s.get("title", ""), s.get("detail", ""))

    lines = [
        "=== NEXUS AI ANALYSIS ===",
        "",
        "{} {} | {}".format(icon, r.get("instrument", "?"), r.get("timeframe", "?")),
        "Price: {}".format(r.get("currentPrice", "?")),
        "Bias: {} ({})".format(bias, r.get("biasStrength", "")),
        "Pattern: {}".format(r.get("patternDetected", "")),
        "",
        r.get("summary", ""),
        "",
        "--- TIMEFRAMES ---",
        tf_lines,
        "--- RSI ---",
        "Value: {} | Condition: {}".format(rsi.get("value", "?"), rsi.get("condition", "?")),
        "MA9: {} | MA21: {}".format(rsi.get("ma9", "?"), rsi.get("ma21", "?")),
        "",
        "--- KEY LEVELS ---",
        "Entry:      {}".format(kl.get("entry", "?")),
        "Stop Loss:  {}".format(kl.get("stopLoss", "?")),
        "TP1 (50%):  {}".format(kl.get("tp1", "?")),
        "TP2 (50%):  {}".format(kl.get("tp2", "?")),
        "Resistance: {}".format(kl.get("resistance", "?")),
        "Support:    {}".format(kl.get("support", "?")),
        "",
        "--- RISK / REWARD ---",
        "Risk: {} pts | Reward: {} pts | Ratio: {}".format(
            rr.get("riskPoints", "?"), rr.get("rewardTp1", "?"), rr.get("ratio", "?")),
        "",
        "--- CONFLUENCE ---",
        conf_lines,
        "--- EXECUTION STEPS ---",
        step_lines,
        "--- INVALIDATION ---",
        r.get("invalidation", "?"),
        "",
        "--- FULL ANALYSIS ---",
        r.get("fullAnalysis", ""),
        "",
        "Educational only. Not financial advice."
    ]
    return "\n".join(lines)


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


if __name__ == "__main__":
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN not set!")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analyze", analyze_command))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("NEXUS Bot running...")
    app.run_polling(drop_pending_updates=True)
