#!/usr/bin/env python3
"""
Monitor de tarefas da XV Gincataí (alquimiaorganizadora.com.br)

Consulta a API REST pública do WordPress e avisa no WhatsApp (Green API) e/ou Telegram quando:
  1. Uma nova tarefa/post é publicada;
  2. Um novo arquivo (PDF etc.) aparece na biblioteca de mídia (às vezes sobe antes do post);
  3. A página principal da gincana é alterada (Avisos / Downloads).

Modos:
  python monitor.py              -> roda uma verificação e sai (ideal p/ GitHub Actions)
  RUN_FOREVER=1 python monitor.py -> fica em loop, verificando a cada INTERVAL segundos

Variáveis de ambiente:
  Configure pelo menos um canal:
  GREEN_API_INSTANCE    idInstance da Green API
  GREEN_API_TOKEN       apiTokenInstance da Green API
  GREEN_API_CHATS       "5551999999999,120363xxxxxxxx@g.us" (números e/ou grupos; máx. 3 no plano grátis)
  GREEN_API_URL         apiUrl mostrado no console (padrão: https://api.green-api.com)
  TELEGRAM_BOT_TOKEN    token do @BotFather
  TELEGRAM_CHAT_IDS     "123456789,-100987654321"
  CALLMEBOT_RECIPIENTS  "5551999999999:APIKEY" (opcional, legado)
  STATE_FILE            caminho do arquivo de estado (padrão: state.json)
  INTERVAL              segundos entre verificações no modo loop (padrão: 60)
  RUN_FOREVER           "1" para modo loop
  DRY_RUN               "1" para só imprimir as mensagens, sem enviar
"""

import hashlib
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = "https://alquimiaorganizadora.com.br"
API = f"{BASE}/wp-json/wp/v2"
MAIN_POST_ID = 1643  # post "XV GINCATAÍ"

# IDs das categorias usadas no site (descobertos na API)
CATEGORIAS = {
    37: "TODAS",
    38: "ARTÍSTICA",
    39: "ESPORTIVA",
    41: "CHARADA",
    42: "RUA",
    43: "DIVERSA",
    44: "RELÍQUIA",
    45: "ESPECIAL",
}

STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))
INTERVAL = int(os.getenv("INTERVAL", "60"))
RUN_FOREVER = os.getenv("RUN_FOREVER") == "1"
DRY_RUN = os.getenv("DRY_RUN") == "1"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (GincataiMonitor/1.0)",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
})


# ---------------------------------------------------------------- utilidades
def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%d/%m %H:%M:%S')}] {msg}", flush=True)


def clean(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def api_get(path: str, params: dict) -> list | dict:
    params = {**params, "_": int(time.time())}  # fura cache de página/CDN
    r = session.get(f"{API}/{path}", params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- notificações
def _post(url: str, payload: dict, label: str) -> None:
    for attempt in range(3):
        try:
            r = requests.post(url, json=payload, timeout=30)
            if r.ok:
                log(f"Enviado: {label}")
                return
            log(f"{label} respondeu {r.status_code}: {r.text[:200]}")
        except requests.RequestException as e:
            log(f"Erro ao enviar ({label}): {e}")
        time.sleep(5 * (attempt + 1))


def send_green_api(message: str) -> bool:
    """WhatsApp via Green API (plano Developer grátis: até 3 chats, contatos ou grupos)."""
    inst = os.getenv("GREEN_API_INSTANCE", "").strip()
    token = os.getenv("GREEN_API_TOKEN", "").strip()
    chats = [c.strip() for c in os.getenv("GREEN_API_CHATS", "").split(",") if c.strip()]
    if not (inst and token and chats):
        return False
    # secret vazio no Actions vira string vazia -> usa o padrão
    base = (os.getenv("GREEN_API_URL") or "https://api.green-api.com").strip().rstrip("/")
    url = f"{base}/waInstance{inst}/sendMessage/{token}"
    for chat in chats:
        if "@" not in chat:  # só o número -> contato
            chat = f"{chat}@c.us"
        _post(url, {"chatId": chat, "message": message}, f"WhatsApp {chat[:8]}…")
    return True


def send_telegram(message: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chats = [c.strip() for c in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()]
    if not (token and chats):
        return False
    for chat in chats:
        _post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            {"chat_id": chat, "text": message.replace("*", "").replace("_", ""),
             "disable_web_page_preview": True},
            f"Telegram {chat}",
        )
    return True


def send_callmebot(message: str) -> bool:
    raw = os.getenv("CALLMEBOT_RECIPIENTS", "").strip()
    items = [i.strip() for i in raw.split(",") if ":" in i]
    if not items:
        return False
    for item in items:
        phone, _, key = item.partition(":")
        try:
            r = requests.get("https://api.callmebot.com/whatsapp.php",
                             params={"phone": phone, "text": message, "apikey": key}, timeout=30)
            log(f"CallMeBot {phone[:6]}…: {r.status_code}")
        except requests.RequestException as e:
            log(f"CallMeBot erro: {e}")
        time.sleep(2)
    return True


def notify(message: str) -> None:
    if DRY_RUN:
        log(f"[DRY_RUN] {message}")
        return
    sent = [f(message) for f in (send_green_api, send_telegram, send_callmebot)]
    if not any(sent):
        log("Nenhum canal configurado — mensagem não enviada:")
        log(message)


# ---------------------------------------------------------------- verificações
def check_posts(state: dict) -> list[str]:
    posts = api_get("posts", {
        "per_page": 30,
        "orderby": "date",
        "order": "desc",
        "_fields": "id,date,title,link,categories,content",
    })
    first_run = "posts" not in state
    seen = set(state.get("posts", []))
    msgs = []
    for p in reversed(posts):  # mais antigas primeiro
        if p["id"] in seen or p["id"] == MAIN_POST_ID:
            continue
        seen.add(p["id"])
        if first_run:
            continue
        titulo = clean(p["title"]["rendered"])
        setores = [CATEGORIAS[c] for c in p.get("categories", []) if c in CATEGORIAS and c != 37]
        pdf = re.search(r'href="([^"]+\.pdf)"', p.get("content", {}).get("rendered", ""))
        data = datetime.fromisoformat(p["date"]).strftime("%d/%m %H:%M")
        linhas = [
            "🧪 *NOVA TAREFA – XV GINCATAÍ*",
            f"*{titulo}*",
        ]
        if setores:
            linhas.append(f"Setor: {', '.join(setores)}")
        linhas.append(f"Publicada: {data}")
        linhas.append(p["link"])
        if pdf:
            linhas.append(f"PDF: {pdf.group(1)}")
        msgs.append("\n".join(linhas))
    state["posts"] = sorted(seen)
    return msgs


def check_media(state: dict) -> list[str]:
    """Arquivos novos na biblioteca de mídia. Só aparecem aqui os que não estão
    presos a um post ainda não publicado — quando aparece, costuma ser antecipado."""
    try:
        media = api_get("media", {
            "per_page": 30,
            "orderby": "date",
            "order": "desc",
            "_fields": "id,date,source_url,mime_type,title",
        })
    except requests.HTTPError as e:
        log(f"Endpoint de mídia indisponível ({e}); ignorando.")
        return []
    first_run = "media" not in state
    seen = set(state.get("media", []))
    msgs = []
    for m in reversed(media):
        if m["id"] in seen:
            continue
        seen.add(m["id"])
        if first_run:
            continue
        if not m.get("mime_type", "").startswith(("application/", "image/")):
            continue
        msgs.append(
            "📎 *Novo arquivo no site da Alquimia*\n"
            f"{clean(m['title']['rendered'])} ({m['mime_type']})\n"
            f"{m['source_url']}\n"
            "_Pode ser material de tarefa ainda não divulgada._"
        )
    state["media"] = sorted(seen)
    return msgs


def check_main_page(state: dict) -> list[str]:
    p = api_get(f"posts/{MAIN_POST_ID}", {"_fields": "modified_gmt,content"})
    content = p.get("content", {}).get("rendered", "")
    # Remove os itens do grid de tarefas (mudam sozinhos quando sai tarefa nova)
    # p/ detectar só mudanças em Avisos/Downloads
    stripped = re.sub(r"<article.*?</article>", "", content, flags=re.S)
    stripped = stripped.replace("<p>No Posts Found</p>", "")
    stripped = re.sub(r"\s+", " ", stripped)
    fingerprint = hashlib.sha256(stripped.encode("utf-8")).hexdigest()
    msgs = []
    old = state.get("main_fingerprint")
    if old and old != fingerprint:
        msgs.append(
            "📢 *Página da XV Gincataí foi atualizada*\n"
            "Confira as abas Avisos e Downloads:\n"
            f"{BASE}/2026/10/xv-gincatai/"
        )
    state["main_fingerprint"] = fingerprint
    state["main_modified"] = p.get("modified_gmt")
    return msgs


# ---------------------------------------------------------------- execução
def run_once() -> None:
    state = load_state()
    # Cada verificação só grava sua "linha de base" depois de funcionar;
    # assim uma falha na 1ª execução não faz posts antigos virarem "novos" depois.
    first_run = "posts" not in state
    msgs: list[str] = []
    for check in (check_posts, check_media, check_main_page):
        try:
            msgs += check(state)
        except Exception as e:  # um check com erro não derruba os outros
            log(f"Falha em {check.__name__}: {e}")

    state.pop("last_check", None)  # não gravar timestamp: evita um commit por execução
    save_state(state)

    if os.getenv("SEND_TEST") == "true":
        notify(
            "🔔 Teste do monitor da XV Gincataí: se você está lendo isto, os avisos estão funcionando.\n"
            f"{len(state.get('posts', []))} post(s) monitorado(s)."
        )

    if first_run and "posts" in state:
        log("Primeira execução: estado inicial salvo.")
        notify(
            "✅ Monitor da XV Gincataí ativo.\n"
            f"{len(state.get('posts', []))} post(s) já existentes foram registrados. "
            "Você será avisado das próximas tarefas."
        )
    for m in msgs:
        notify(m)
    log(f"Verificação concluída. {len(msgs)} novidade(s).")


def main() -> None:
    if not RUN_FOREVER:
        run_once()
        return
    log(f"Modo contínuo: verificando a cada {INTERVAL}s.")
    while True:
        try:
            run_once()
        except Exception as e:
            log(f"Erro inesperado: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
