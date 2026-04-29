from __future__ import annotations

import argparse
import json
import os
import re
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


HTML_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>A+ 扫码登录桥接</title>
  <style>
    body { font-family: "Microsoft YaHei", sans-serif; background: #f7f8fa; margin: 0; }
    .wrap { max-width: 760px; margin: 24px auto; background: #fff; border-radius: 10px; padding: 18px; box-shadow: 0 8px 20px rgba(0,0,0,.08); }
    .top { display: flex; gap: 18px; align-items: flex-start; }
    .qr { width: 240px; height: 240px; border: 1px solid #e5e8ef; display: flex; align-items: center; justify-content: center; border-radius: 8px; overflow: hidden; background: #fff; }
    .ops { flex: 1; }
    .btn { background: #1677ff; color: #fff; border: none; border-radius: 6px; padding: 10px 14px; cursor: pointer; }
    .btn:disabled { background: #9bbcff; cursor: not-allowed; }
    .status { margin-top: 8px; line-height: 1.7; white-space: pre-wrap; color: #222; }
    .ticket { margin-top: 10px; word-break: break-all; color: #0f766e; }
    .hint { margin-top: 10px; color: #666; font-size: 13px; }
    .box { margin-top: 14px; padding: 10px; border-radius: 8px; background: #f3f6ff; font-family: Consolas, monospace; font-size: 12px; line-height: 1.55; max-height: 260px; overflow: auto; }
  </style>
</head>
<body>
  <div class="wrap">
    <h2>A+ 桌面登录二维码（本地生成）</h2>
    <div class="top">
      <div id="qrcode" class="qr">初始化中...</div>
      <div class="ops">
        <button id="refreshBtn" class="btn">刷新二维码</button>
        <div id="status" class="status">准备中...</div>
        <div id="ticket" class="ticket"></div>
        <div class="hint">扫码后请在手机端确认。页面会自动轮询状态并保存结果到本地。</div>
      </div>
    </div>
    <div id="jsonBox" class="box"></div>
  </div>
  <div id="loginHolder" style="display:none;"></div>
  <script src="/captcha.js"></script>
  <script src="/passport-sdk.js"></script>
  <script>
    window.UC_HOST = "https://login.ke.com";
    window.CAPTCHA_HOST = "https://captcha.lianjia.com";
    window.SAAS_HOST = "https://saas.a.ke.com";

    const statusEl = document.getElementById("status");
    const ticketEl = document.getElementById("ticket");
    const boxEl = document.getElementById("jsonBox");
    const qrEl = document.getElementById("qrcode");
    const refreshBtn = document.getElementById("refreshBtn");

    let sdk = null;
    let qrInfo = null;
    let timer = null;

    function show(msg) {
      statusEl.textContent = msg;
      console.log(msg);
    }

    function showJson(payload) {
      boxEl.textContent = JSON.stringify(payload, null, 2);
    }

    async function saveResult(payload) {
      await fetch("/result", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      });
    }

    function withTimeout(promise, ms, label) {
      let timeoutId = null;
      const timeoutPromise = new Promise((_, reject) => {
        timeoutId = setTimeout(() => {
          reject(new Error(label + " timeout after " + ms + "ms"));
        }, ms);
      });
      return Promise.race([
        promise.finally(() => {
          if (timeoutId) clearTimeout(timeoutId);
        }),
        timeoutPromise
      ]);
    }

    async function sdkCall(funcName, payload, timeoutMs) {
      return withTimeout(sdk.call(funcName, payload), timeoutMs || 12000, String(funcName || "sdk.call"));
    }

    function clearTimer() {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    }

    async function checkQRCode() {
      if (!sdk || !qrInfo || !qrInfo.id) return;
      try {
        const checkResp = await sdkCall(window.PassportSDK.PassportFunc.CHECK_QRCODE, { id: qrInfo.id }, 10000);
        if (!checkResp || !checkResp.success) return;
        const state = checkResp.state || "UNKNOWN";
        if (state === "BINDING") {
          show("已扫码，请在手机端确认登录");
          return;
        }
        if (state === "EXPIRED") {
          clearTimer();
          show("二维码已过期，请点击刷新二维码");
          return;
        }
        if (state === "CONFIRMED") {
          clearTimer();
          show("已确认，正在换取登录票据...");
          await doLogin();
          return;
        }
        show("QR state: " + state);
      } catch (err) {
        show("checkQRCode error: " + (err && err.message ? err.message : String(err)));
      }
    }

    async function doLogin() {
      try {
        const loginResp = await sdkCall(window.PassportSDK.PassportFunc.DO_LOGIN, {
          isMigrate: false,
          service: window.SAAS_HOST + "/cas",
          clientSource: "web",
          authenticateType: "qrcode",
          credential: { id: qrInfo.id }
        }, 15000);
        const result = {
          time: new Date().toISOString(),
          qr: qrInfo,
          login: loginResp
        };
        showJson(result);
        await saveResult(result);
        if (loginResp && loginResp.success && loginResp.serviceTicket && loginResp.serviceTicket.id) {
          ticketEl.textContent = "serviceTicket: " + loginResp.serviceTicket.id;
          show("登录成功，结果已写入运行时目录");
        } else {
          show("登录响应返回失败，请刷新二维码重试");
        }
      } catch (err) {
        show("登录失败: " + (err && err.message ? err.message : String(err)));
      }
    }

    async function refreshQRCode() {
      if (!sdk) return;
      refreshBtn.disabled = true;
      clearTimer();
      try {
        show("正在获取二维码...");
        const resp = await sdkCall(
          window.PassportSDK.PassportFunc.REFRESH_QRCODE,
          { service: window.SAAS_HOST + "/cas" },
          15000
        );
        const payload = (resp && resp.data) ? resp.data : resp;
        if (!payload || !payload.id || !payload.qrCodeContent) {
          showJson({refreshResp: resp});
          show("二维码获取失败");
          refreshBtn.disabled = false;
          return;
        }
        qrInfo = payload;
        const img = sdk.generateByDom(payload.qrCodeContent);
        qrEl.innerHTML = "";
        qrEl.appendChild(img);
        show("请用手机贝壳客户端扫码");
        timer = setInterval(checkQRCode, 2000);
      } catch (err) {
        show("二维码获取异常: " + (err && err.message ? err.message : String(err)));
      } finally {
        refreshBtn.disabled = false;
      }
    }

    async function init() {
      try {
        sdk = new window.PassportSDK({
          debug: { enabled: true },
          useWebview: false,
          iframeHolderId: "loginHolder",
          passportUrl: window.UC_HOST + "/authentication/sdk/init?version=2.0",
          captchaEndpoint: window.CAPTCHA_HOST
        });
        await withTimeout(sdk.init(), 15000, "sdk.init");
        window.passportSDK = sdk;
        sdk.initQrCodeGenerator({ width: 220, height: 220 });
        await sdkCall(window.PassportSDK.PassportFunc.GET_INITIAL, { service: window.SAAS_HOST + "/cas" }, 15000);
        await sdkCall(window.PassportSDK.PassportFunc.SET_ACCOUNT_SYSTEM, "employee", 10000);
        await refreshQRCode();
      } catch (err) {
        show("初始化失败: " + (err && err.message ? err.message : String(err)));
      }
    }

    refreshBtn.addEventListener("click", refreshQRCode);
    window.addEventListener("beforeunload", clearTimer);
    init();
  </script>
</body>
</html>
"""


class AplusQrRequestHandler(BaseHTTPRequestHandler):
    passport_sdk_path: Path | None = None
    captcha_sdk_path: Path | None = None
    result_file_path: Path | None = None

    def _send_text(self, status: HTTPStatus, payload: str, content_type: str = "text/plain; charset=utf-8") -> None:
        body = payload.encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, status: HTTPStatus, payload: bytes, content_type: str) -> None:
        self.send_response(status.value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_file_bytes(self, path: Path | None) -> bytes | None:
        if not path or not path.exists():
            return None
        try:
            return path.read_bytes()
        except OSError:
            return None

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/" or self.path.startswith("/index.html"):
            self._send_text(HTTPStatus.OK, HTML_PAGE, "text/html; charset=utf-8")
            return

        if self.path.startswith("/passport-sdk.js"):
            payload = self._read_file_bytes(self.passport_sdk_path)
            if payload is None:
                self._send_text(HTTPStatus.NOT_FOUND, "passport sdk not found")
                return
            self._send_bytes(HTTPStatus.OK, payload, "application/javascript; charset=utf-8")
            return

        if self.path.startswith("/captcha.js"):
            payload = self._read_file_bytes(self.captcha_sdk_path)
            if payload is None:
                self._send_text(HTTPStatus.NOT_FOUND, "captcha sdk not found")
                return
            self._send_bytes(HTTPStatus.OK, payload, "application/javascript; charset=utf-8")
            return

        if self.path.startswith("/status"):
            if not self.result_file_path or not self.result_file_path.exists():
                self._send_text(HTTPStatus.OK, json.dumps({"exists": False}), "application/json; charset=utf-8")
                return
            self._send_text(
                HTTPStatus.OK,
                self.result_file_path.read_text(encoding="utf-8"),
                "application/json; charset=utf-8",
            )
            return

        self._send_text(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.startswith("/result"):
            self._send_text(HTTPStatus.NOT_FOUND, "not found")
            return
        if not self.result_file_path:
            self._send_text(HTTPStatus.INTERNAL_SERVER_ERROR, "result path not configured")
            return

        content_length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_text(HTTPStatus.BAD_REQUEST, "invalid json")
            return

        payload["savedAt"] = datetime.now().isoformat(timespec="seconds")
        self.result_file_path.parent.mkdir(parents=True, exist_ok=True)
        self.result_file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._send_text(HTTPStatus.OK, json.dumps({"ok": True}), "application/json; charset=utf-8")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def _find_passport_file(resources_root: Path) -> Path:
    index_html = resources_root / "index.html"
    if index_html.exists():
        try:
            html_text = index_html.read_text(encoding="utf-8", errors="ignore")
            match = re.search(r"js/assets/passport/(PassportSDK[^\"']+\.js)", html_text)
            if match:
                candidate = resources_root / "js" / "assets" / "passport" / match.group(1)
                if candidate.exists():
                    return candidate
        except OSError:
            pass

    candidates = sorted(
        (resources_root / "js" / "assets" / "passport").glob("PassportSDK*.js"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"PassportSDK*.js not found under: {resources_root}")
    return candidates[0]


def _find_captcha_file(resources_root: Path) -> Path:
    captcha = resources_root / "js" / "assets" / "passport" / "captcha.js"
    if not captcha.exists():
        raise FileNotFoundError(f"captcha.js not found under: {resources_root}")
    return captcha


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Host a local A+ QR login page")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host, default 127.0.0.1")
    parser.add_argument("--port", default=18765, type=int, help="Bind port, default 18765")
    parser.add_argument(
        "--aplus-resources",
        default=str(Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming"))) / "A+" / "resources" / "app"),
        help="A+ resources/app directory",
    )
    parser.add_argument(
        "--result-file",
        default=str(Path(__file__).resolve().parents[1] / "runtime" / "aplus_qr_login_result.json"),
        help="Where to save login result payload",
    )
    parser.add_argument("--no-open", action="store_true", help="Do not auto open browser")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    resources_root = Path(args.aplus_resources)

    passport_file = _find_passport_file(resources_root)
    captcha_file = _find_captcha_file(resources_root)
    result_file = Path(args.result_file).resolve()

    handler_cls = AplusQrRequestHandler
    handler_cls.passport_sdk_path = passport_file
    handler_cls.captcha_sdk_path = captcha_file
    handler_cls.result_file_path = result_file

    server = ThreadingHTTPServer((args.host, args.port), handler_cls)
    url = f"http://{args.host}:{args.port}/"
    print(f"[aplus-qr] server started: {url}")
    print(f"[aplus-qr] passport sdk: {passport_file}")
    print(f"[aplus-qr] result file: {result_file}")

    if not args.no_open:
        webbrowser.open(url, new=2)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("[aplus-qr] server stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
