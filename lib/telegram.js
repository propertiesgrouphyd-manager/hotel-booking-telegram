function parseChatMap() {
  const raw = process.env.TELEGRAM_PROPERTY_CHAT_MAP || "";
  const map = {};
  for (const part of raw.split(",")) {
    const p = part.trim();
    if (!p || !p.includes(":")) continue;
    const [code, chat] = p.split(":");
    map[code.trim()] = Number(chat.trim());
  }
  return map;
}

const CHAT_MAP = parseChatMap();

export function resolveTelegramRoute(propertyCode) {
  if (propertyCode === "ALL") {
    return {
      botToken: process.env.TELEGRAM_CONSOLIDATED_BOT_TOKEN,
      chatId: Number(process.env.TELEGRAM_CONSOLIDATED_CHAT_ID)
    };
  }
  return {
    botToken: process.env.TELEGRAM_DEFAULT_BOT_TOKEN,
    chatId: CHAT_MAP[propertyCode] || Number(process.env.TELEGRAM_DEFAULT_CHAT_ID || 0)
  };
}

export async function telegramSendText({ botToken, chatId, text }) {
  const url = `https://api.telegram.org/bot${botToken}/sendMessage`;
  const resp = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text, parse_mode: "HTML" })
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok || data.ok !== true) {
    const desc = data?.description || resp.statusText;
    throw new Error(`Telegram failed: ${resp.status} ${desc}`);
  }
  return data;
}
