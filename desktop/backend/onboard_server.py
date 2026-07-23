"""Frontend server for nanobot Desktop.

A tiny stdlib HTTP server (always-on, binds instantly) that the Pake window
points at.  It guarantees the window *never* shows a connection-refused page:

  - while the gateway is still starting → friendly loading animation
  - on first run (no config)            → web onboarding form
  - once ready                           → redirects to the gateway WebUI

Routes:
  GET  /             loader / smart redirect
  GET  /setup        onboarding form
  GET  /api/status   {configured, gateway_up}
  POST /api/setup    write config + restart gateway
"""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROUTER_PORT = 8766
GATEWAY_PORT = 8765
GATEWAY_URL = f"http://127.0.0.1:{GATEWAY_PORT}"

PROVIDERS = [
    {"id": "deepseek", "label": "DeepSeek (深度求索)", "base": "https://api.deepseek.com/v1", "model": "deepseek-v4-pro"},
    {"id": "zhipu", "label": "智谱 GLM", "base": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-flash"},
    {"id": "moonshot", "label": "月之暗面 Kimi", "base": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
    {"id": "openai", "label": "OpenAI", "base": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    {"id": "anthropic", "label": "Anthropic Claude", "base": "", "model": "claude-3-5-sonnet-20241022"},
    {"id": "openrouter", "label": "OpenRouter", "base": "https://openrouter.ai/api/v1", "model": "anthropic/claude-3.5-sonnet"},
    {"id": "gemini", "label": "Google Gemini", "base": "https://generativelanguage.googleapis.com/v1beta/openai/", "model": "gemini-2.0-flash"},
    {"id": "custom", "label": "自定义 (OpenAI 兼容)", "base": "", "model": ""},
]


# ---------------------------------------------------------------------------
# State checks
# ---------------------------------------------------------------------------


def gateway_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", GATEWAY_PORT), timeout=0.5):
            return True
    except OSError:
        return False


def _provider_default_base(provider_id: str) -> str:
    for p in PROVIDERS:
        if p["id"] == provider_id:
            return p["base"]
    return ""


def config_is_configured() -> bool:
    try:
        from nanobot.config.loader import get_config_path, load_config
    except Exception:
        return False
    path = get_config_path()
    if not path.exists():
        return False
    try:
        cfg = load_config(path)
    except Exception:
        return False
    for name in dir(cfg.providers):
        if name.startswith("_"):
            continue
        p = getattr(cfg.providers, name, None)
        if p is not None and getattr(p, "api_key", None):
            return True
    for p in (getattr(cfg.providers, "model_extra", None) or {}).values():
        if getattr(p, "api_key", None):
            return True
    return False


def build_and_save_config(*, provider, api_key, model, api_base=None) -> None:
    """Build a config and save it.

    No WebUI password is set: with an empty ``token_issue_secret`` the gateway
    serves a passwordless bootstrap to localhost, so the local WebUI never shows
    a login page.  Suitable for a single-user local agent.
    """
    from nanobot.config.loader import get_config_path, save_config
    from nanobot.config.schema import Config

    config = Config()
    provider_cfg = getattr(config.providers, provider, None)
    if provider_cfg is not None:
        provider_cfg.api_key = api_key.strip()
        base = (api_base or "").strip().rstrip("/") or _provider_default_base(provider)
        if base:
            provider_cfg.api_base = base
    config.agents.defaults.model = model.strip()
    config.agents.defaults.provider = provider
    # Enable the local WebUI. token_issue_secret left empty => passwordless for localhost.
    config.channels.websocket = {
        "enabled": True,
        "port": GATEWAY_PORT,
    }
    save_config(config, get_config_path())


# ---------------------------------------------------------------------------
# HTML pages
# ---------------------------------------------------------------------------


_PAGE_CSS = """
  :root { --bg:#0f1115; --card:#171a21; --border:#262b36; --text:#e6e8eb;
          --muted:#9aa3ad; --accent:#6B9BFA; --accent-2:#4f7be0; --ok:#6AAB73; --err:#e06c6c; }
  * { box-sizing:border-box; }
  body { margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
         background:radial-gradient(1200px 600px at 50% -10%,#1c2230,var(--bg)); color:var(--text); padding:24px; }
  .card { width:100%; max-width:480px; background:var(--card); border:1px solid var(--border);
          border-radius:16px; padding:36px 32px; box-shadow:0 20px 60px rgba(0,0,0,.45); }
"""


def _loader_html() -> str:
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>nanobot</title><style>{_PAGE_CSS}
  .center {{ text-align:center; }}
  .logo {{ font-size:52px; line-height:1; margin-bottom:18px; }}
  .title {{ font-size:20px; margin-bottom:6px; }}
  .sub {{ color:var(--muted); font-size:14px; margin-bottom:26px; }}
  .dots {{ display:flex; gap:8px; justify-content:center; }}
  .dot {{ width:10px; height:10px; border-radius:50%; background:var(--accent); opacity:.4; animation:bounce 1s infinite ease-in-out; }}
  .dot:nth-child(2){{ animation-delay:.15s; }} .dot:nth-child(3){{ animation-delay:.3s; }}
  @keyframes bounce {{ 0%,80%,100%{{ transform:scale(.6); opacity:.4; }} 40%{{ transform:scale(1); opacity:1; }} }}
</style></head>
<body><div class="card center">
  <div class="logo">🐈</div>
  <div class="title" id="t">正在启动 nanobot…</div>
  <div class="sub" id="s">首次启动需要几秒钟，请稍候</div>
  <div class="dots"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div>
</div>
<script>
async function poll(){{
  try {{
    const r = await fetch('/api/status', {{cache:'no-store'}}); const j = await r.json();
    if (!j.configured) {{ window.location.replace('/setup'); return; }}
    if (j.gateway_up)  {{ window.location.replace('{GATEWAY_URL}'); return; }}
    document.getElementById('t').textContent = '正在启动 nanobot…';
    document.getElementById('s').textContent = '后端即将就绪…';
  }} catch(e) {{}}
  setTimeout(poll, 800);
}}
poll();
</script></body></html>"""


def _onboarding_html() -> str:
    provider_opts = "\n".join(
        f'<option value="{p["id"]}" data-base="{p["base"]}" data-model="{p["model"]}">{p["label"]}</option>'
        for p in PROVIDERS
    )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>nanobot · 初始化</title><style>{_PAGE_CSS}
  .logo {{ font-size:40px; line-height:1; margin-bottom:4px; }}
  h1 {{ font-size:22px; margin:6px 0 4px; }}
  .sub {{ color:var(--muted); font-size:14px; margin-bottom:26px; }}
  label {{ display:block; font-size:13px; color:var(--muted); margin:18px 0 7px; }}
  input,select {{ width:100%; padding:12px 14px; border-radius:10px; border:1px solid var(--border);
    background:#0d1016; color:var(--text); font-size:15px; outline:none; transition:border-color .15s; }}
  input:focus,select:focus {{ border-color:var(--accent); }}
  input::placeholder {{ color:#5f6873; }}
  .hint {{ font-size:12px; color:var(--muted); margin-top:6px; }}
  .hint a {{ color:var(--accent); text-decoration:none; }}
  button {{ margin-top:26px; width:100%; padding:13px; border:0; border-radius:10px; cursor:pointer;
    background:var(--accent); color:#fff; font-size:15px; font-weight:600; transition:background .15s; }}
  button:hover {{ background:var(--accent-2); }} button:disabled {{ opacity:.6; cursor:default; }}
  .msg {{ margin-top:14px; font-size:14px; min-height:20px; }}
  .msg.ok {{ color:var(--ok); }} .msg.err {{ color:var(--err); }}
  .spinner {{ display:inline-block; width:14px; height:14px; border:2px solid rgba(255,255,255,.3);
    border-top-color:#fff; border-radius:50%; animation:spin .7s linear infinite; vertical-align:-2px; margin-right:8px; }}
  @keyframes spin {{ to {{ transform:rotate(360deg); }} }}
</style></head>
<body><form class="card" id="form" autocomplete="off">
  <div class="logo">🐈</div>
  <h1>欢迎使用 nanobot</h1>
  <div class="sub">填写下方信息即可开始，整个过程不到一分钟。</div>
  <label for="provider">AI 服务商</label>
  <select id="provider">{provider_opts}</select>
  <div id="baseWrap" style="display:none"><label for="base">接口地址 (API Base URL)</label>
    <input id="base" type="text" placeholder="https://api.example.com/v1" /></div>
  <label for="key">API Key</label>
  <input id="key" type="password" placeholder="sk-..." required />
  <div class="hint" id="keyHint"></div>
  <label for="model">模型名称</label>
  <input id="model" type="text" placeholder="模型 ID" required />
  <button id="btn" type="submit">完成设置并启动</button>
  <div class="msg" id="msg"></div>
</form>
<script>
const $=id=>document.getElementById(id);
const provs=Array.from($('provider').options);
function onProv(){{ const o=$('provider').selectedOptions[0];
  $('baseWrap').style.display=(o.value==='custom')?'':'none';
  $('base').value=o.dataset.base||'';
  if(!$('model').value||provs.some(p=>p.dataset.model===$('model').value)) $('model').value=o.dataset.model||'';
  const h={{deepseek:'https://platform.deepseek.com/api_keys',openai:'https://platform.openai.com/api-keys',
    anthropic:'https://console.anthropic.com/settings/keys',openrouter:'https://openrouter.ai/keys',
    zhipu:'https://open.bigmodel.cn/usercenter/apikeys',moonshot:'https://platform.moonshot.cn/console/api-keys',
    gemini:'https://aistudio.google.com/app/apikey',custom:''}};
  $('keyHint').innerHTML=h[o.value]?'还没有 Key？<a href="'+h[o.value]+'" target="_blank">点此获取</a>':'';
}}
$('provider').addEventListener('change',onProv); onProv();
$('form').addEventListener('submit',async e=>{{ e.preventDefault();
  const btn=$('btn'),msg=$('msg');
  const body={{provider:$('provider').value,api_key:$('key').value.trim(),api_base:$('base').value.trim(),
    model:$('model').value.trim()}};
  if(!body.api_key||!body.model){{msg.className='msg err';msg.textContent='请填写所有字段。';return;}}
  btn.disabled=true;msg.className='msg';
  msg.innerHTML='<span class="spinner"></span>正在保存并启动 nanobot…';
  try{{ const r=await fetch('/api/setup',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
    const j=await r.json();
    if(j.ok){{ msg.className='msg ok';msg.innerHTML='<span class="spinner"></span>设置完成，正在打开聊天界面…';
      setTimeout(()=>window.location.replace('/'),1500); }}
    else{{msg.className='msg err';msg.textContent='失败：'+(j.error||'未知错误');btn.disabled=false;}}
  }}catch(err){{msg.className='msg err';msg.textContent='请求失败：'+err;btn.disabled=false;}}
}});
</script></body></html>"""


# ---------------------------------------------------------------------------
# HTTP router
# ---------------------------------------------------------------------------


def make_handler(*, on_setup, ready_event):
    class Router(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _send(self, code, body=b"", ctype="text/html; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                if config_is_configured() and gateway_up():
                    self.send_response(302)
                    self.send_header("Location", GATEWAY_URL)
                    self.end_headers()
                    return
                return self._send(200, _loader_html().encode("utf-8"))
            if self.path.startswith("/setup"):
                if config_is_configured():
                    self.send_response(302)
                    self.send_header("Location", "/")
                    self.end_headers()
                    return
                return self._send(200, _onboarding_html().encode("utf-8"))
            if self.path.startswith("/api/status"):
                return self._json({"configured": config_is_configured(), "gateway_up": gateway_up()})
            self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if self.path != "/api/setup":
                return self._send(404, b"not found", "text/plain")
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw.decode("utf-8"))
            except Exception:
                data = {}
            try:
                build_and_save_config(
                    provider=data.get("provider", "custom"),
                    api_key=data.get("api_key", ""),
                    api_base=data.get("api_base") or None,
                    model=data.get("model", ""),
                )
                ready_event.clear()
                on_setup()
                ready_event.wait(timeout=90.0)
                self._json({"ok": True})
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": str(exc)})

    return Router


class OnboardRouter:
    def __init__(self, *, on_setup, ready_event, port=ROUTER_PORT):
        handler = make_handler(on_setup=on_setup, ready_event=ready_event)
        self._server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        try:
            self._server.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    import threading
    ev = threading.Event()
    OnboardRouter(on_setup=lambda: None, ready_event=ev).start()
    print(f"frontend server on http://127.0.0.1:{ROUTER_PORT}")
    threading.Event().wait()
