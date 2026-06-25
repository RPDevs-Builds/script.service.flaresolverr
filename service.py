import sys
import os
import platform
import threading
import time
import urllib.request
import zipfile
import shutil
import xbmc
import xbmcaddon
import xbmcvfs

ADDON = xbmcaddon.Addon()
ADDON_PATH = ADDON.getAddonInfo('path')
LIB_PATH = os.path.join(ADDON_PATH, 'resources', 'lib')
FLARESOLVERR_PATH = os.path.join(LIB_PATH, 'flaresolverr')
PROFILE_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))

sys.path.insert(0, FLARESOLVERR_PATH)
sys.path.insert(0, LIB_PATH)


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

def is_android():
    """
    Detect whether we are running on Android (e.g. NVIDIA Shield TV).
    Multiple heuristics are combined because Kodi's embedded Python
    reports sys.platform as 'linux' even on Android.
    """
    # Python 3.7+ exposes this on Android
    if hasattr(sys, 'getandroidapilevel'):
        return True
    # Android system fingerprint
    if os.path.exists('/system/build.prop'):
        return True
    # Kodi on Android stores data here
    if os.path.exists('/data/user/0/org.xbmc.kodi'):
        return True
    # Check platform string
    if 'ANDROID' in platform.platform().upper():
        return True
    return False


# ---------------------------------------------------------------------------
# __pycache__ buster — ensures stale bytecache from a previous version
# does not shadow updated .py files after an addon upgrade.
# ---------------------------------------------------------------------------

def purge_pycache(root_dir):
    """
    Recursively delete all __pycache__ directories under root_dir.
    This is called once at service startup to guarantee fresh imports.
    """
    count = 0
    for dirpath, dirnames, _filenames in os.walk(root_dir):
        for d in dirnames:
            if d == '__pycache__':
                cache_path = os.path.join(dirpath, d)
                try:
                    shutil.rmtree(cache_path)
                    count += 1
                except Exception:
                    pass
    if count:
        xbmc.log(f"[FlareSolverr] Purged {count} __pycache__ directories", xbmc.LOGINFO)


# ---------------------------------------------------------------------------
# Chrome / Chromium provisioning (desktop Linux only)
# ---------------------------------------------------------------------------

def ensure_chrome():
    # If already downloaded
    chrome_dir = os.path.join(PROFILE_PATH, 'chrome-linux64')
    chrome_bin = os.path.join(chrome_dir, 'chrome')
    
    if os.path.exists(chrome_bin) and os.access(chrome_bin, os.X_OK):
        # Even if already downloaded, make sure helper binaries are executable
        for helper in ['chrome_crashpad_handler', 'chrome-wrapper', 'chrome_sandbox', 'xdg-mime', 'xdg-settings']:
            helper_path = os.path.join(chrome_dir, helper)
            if os.path.exists(helper_path) and not os.access(helper_path, os.X_OK):
                try:
                    os.chmod(helper_path, 0o755)
                except Exception:
                    pass
        return chrome_bin
        
    # Check system
    for cmd in ['chromium', 'chromium-browser', 'google-chrome', 'chrome']:
        path = shutil.which(cmd)
        if path:
            return path
            
    # Auto-download for Linux x64 Flatpak/Native environments missing Chrome
    xbmc.log("[FlareSolverr] Chrome not found natively. Downloading Chrome for Testing...", xbmc.LOGINFO)
    os.makedirs(PROFILE_PATH, exist_ok=True)
    zip_path = os.path.join(PROFILE_PATH, 'chrome.zip')
    
    url = "https://storage.googleapis.com/chrome-for-testing-public/124.0.6367.91/linux64/chrome-linux64.zip"
    urllib.request.urlretrieve(url, zip_path)
    
    xbmc.log("[FlareSolverr] Extracting Chrome...", xbmc.LOGINFO)
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(PROFILE_PATH)
        
    os.chmod(chrome_bin, 0o755)
    for helper in ['chrome_crashpad_handler', 'chrome-wrapper', 'chrome_sandbox', 'xdg-mime', 'xdg-settings']:
        helper_path = os.path.join(chrome_dir, helper)
        if os.path.exists(helper_path):
            try:
                os.chmod(helper_path, 0o755)
            except Exception:
                pass
        
    os.remove(zip_path)
    xbmc.log(f"[FlareSolverr] Chrome installed to {chrome_bin}", xbmc.LOGINFO)
    return chrome_bin


# ---------------------------------------------------------------------------
# Environment setup
# ---------------------------------------------------------------------------

def setup_flaresolverr_env():
    host = ADDON.getSetting('host') or '0.0.0.0'
    port = ADDON.getSetting('port') or '8191'
    headless = ADDON.getSettingBool('headless')
    
    os.environ["HOST"] = host
    os.environ["PORT"] = port
    os.environ["HEADLESS"] = "true" if headless else "false"
    
    # Read logging settings
    enable_log = ADDON.getSettingBool('enable_log')
    try:
        log_level_str = ADDON.getSetting('log_level')
        log_level_setting = int(log_level_str) if log_level_str else 1
    except ValueError:
        log_level_setting = 1
    
    level_map = {0: "debug", 1: "info", 2: "warning", 3: "error"}
    log_level = level_map.get(log_level_setting, "info")
    os.environ["LOG_LEVEL"] = log_level if enable_log else "error"
    
    import certifi
    os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
    os.environ["SSL_CERT_FILE"] = certifi.where()


# ---------------------------------------------------------------------------
# Local FlareSolverr server (desktop Linux / Windows / macOS)
# ---------------------------------------------------------------------------

def run_flaresolverr_server():
    import logging
    import utils
    import flaresolverr_service
    from flaresolverr import app
    from bottle_plugins.error_plugin import error_plugin
    from bottle_plugins.logger_plugin import logger_plugin
    from bottle_plugins import prometheus_plugin
    from bottle import run, ServerAdapter

    try:
        chrome_path = ensure_chrome()
        utils.CHROME_EXE_PATH = chrome_path
        
        def safe_test_browser():
            logging.info(f"Using Chrome path: {chrome_path}")
            
        flaresolverr_service.test_browser_installation = safe_test_browser

        # Setup standard Python logging to file.
        # This implementation replaces Kodi's native xbmc.log for the Python sub-process,
        # providing an independent, rotating log file (max 5MB) at a user-defined path.
        # This prevents Kodi's main `kodi.log` from being flooded by verbose server output
        # and allows users to access logs directly via standard text files or WebTail UI.
        enable_log = ADDON.getSettingBool('enable_log')
        try:
            log_level_str = ADDON.getSetting('log_level')
            log_level_setting = int(log_level_str) if log_level_str else 1
        except ValueError:
            log_level_setting = 1
        
        py_level_map = {0: logging.DEBUG, 1: logging.INFO, 2: logging.WARNING, 3: logging.ERROR}
        py_log_level = py_level_map.get(log_level_setting, logging.INFO)
        
        handlers = []
        if enable_log:
            from logging.handlers import RotatingFileHandler
            log_path = ADDON.getSetting('log_path') or ""
            if not log_path or not log_path.strip():
                log_path = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
            else:
                log_path = xbmcvfs.translatePath(log_path)
            
            os.makedirs(log_path, exist_ok=True)
            log_file = os.path.join(log_path, 'flaresolverr.log')
            
            file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=1, encoding='utf-8')
            handlers.append(file_handler)
            xbmc.log(f"[FlareSolverr] Custom logging enabled -> {log_file}", xbmc.LOGINFO)
        else:
            handlers.append(logging.NullHandler())

        logging.basicConfig(level=py_log_level, format='%(asctime)s %(levelname)-8s %(message)s', handlers=handlers)
        logging.getLogger('urllib3').setLevel(logging.ERROR)
        logging.getLogger('selenium.webdriver.remote.remote_connection').setLevel(logging.WARNING)
        logging.getLogger('undetected_chromedriver').setLevel(logging.WARNING)
        
        utils.get_current_platform()
        flaresolverr_service.test_browser_installation()

        app.install(logger_plugin)
        app.install(error_plugin)
        prometheus_plugin.setup()
        app.install(prometheus_plugin.prometheus_plugin)

        # Add custom log viewer endpoints
        @app.route('/logs')
        def serve_logs_page():
            from bottle import static_file, HTTPError
            import xbmcaddon
            addon = xbmcaddon.Addon('script.service.flaresolverr')
            if not addon.getSettingBool('enable_remote_log_viewer'):
                raise HTTPError(403, "Remote log viewer is disabled.")
            addon_path = addon.getAddonInfo('path')
            html_path = os.path.join(addon_path, "resources", "templates", "webtail.html")
            return static_file("webtail.html", root=os.path.dirname(html_path))
            
        @app.route('/logs/tail')
        def serve_logs_tail():
            from bottle import request, response, HTTPError
            import xbmcaddon
            import xbmcvfs
            from resources.lib.logreader import LogReader
            
            addon = xbmcaddon.Addon('script.service.flaresolverr')
            if not addon.getSettingBool('enable_remote_log_viewer'):
                raise HTTPError(403, "Remote log viewer is disabled.")
                
            log_path_setting = addon.getSetting('log_path') or ""
            if not log_path_setting or not log_path_setting.strip():
                log_path_setting = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
            else:
                log_path_setting = xbmcvfs.translatePath(log_path_setting)
                
            flaresolverr_log = os.path.join(log_path_setting, 'flaresolverr.log')
            if not os.path.exists(flaresolverr_log):
                raise HTTPError(404, "Log file not found. Ensure logging is enabled.")
                
            offset = int(request.query.offset or 0)
            reader = LogReader(flaresolverr_log)
            reader.set_offset(offset)
            content = reader.tail().encode('utf-8')
            
            response.content_type = 'text/plain'
            response.set_header('X-Seek-Offset', str(reader.get_offset()))
            return content

        class WaitressServerPoll(ServerAdapter):
            def run(self, handler):
                from waitress import serve
                serve(handler, host=self.host, port=self.port, asyncore_use_poll=True)

        server_host = os.environ["HOST"]
        server_port = int(os.environ["PORT"])
        
        logging.info(f"Starting FlareSolverr server on {server_host}:{server_port}")
        run(app, host=server_host, port=server_port, quiet=True, server=WaitressServerPoll)
    except Exception as e:
        logging.error(f"FlareSolverr Server Error: {str(e)}")
        xbmc.log(f"FlareSolverr Server Error: {str(e)}", xbmc.LOGFATAL)


# ---------------------------------------------------------------------------
# Remote delegation mode (Android / restricted platforms)
# ---------------------------------------------------------------------------

def run_remote_proxy_mode():
    """
    On Android (and other platforms without Chrome), the addon does NOT start
    a local FlareSolverr server. Instead, it runs a lightweight HTTP reverse
    proxy that forwards all requests to a user-configured remote FlareSolverr
    instance. This lets consuming addons (Otaku, etc.) use the same
    localhost:8191 endpoint regardless of platform.
    """
    import json
    import logging
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from urllib.request import Request, urlopen
    from urllib.error import URLError

    remote_url = ADDON.getSetting('remote_url') or ''
    if not remote_url.strip():
        xbmc.log(
            "[FlareSolverr] Android detected but no remote FlareSolverr URL configured. "
            "Set one in Addon Settings -> General -> Remote FlareSolverr URL. "
            "Example: http://192.168.1.100:8191",
            xbmc.LOGWARNING,
        )
        return

    remote_url = remote_url.rstrip('/')
    local_host = ADDON.getSetting('host') or '0.0.0.0'
    local_port = int(ADDON.getSetting('port') or '8191')

    xbmc.log(
        f"[FlareSolverr] Android remote proxy mode: localhost:{local_port} -> {remote_url}",
        xbmc.LOGINFO,
    )

    class ProxyHandler(BaseHTTPRequestHandler):
        """Forward every request to the remote FlareSolverr instance."""

        def log_message(self, fmt, *args):
            # Route HTTP server logs through Kodi's logger
            xbmc.log(f"[FlareSolverr Proxy] {fmt % args}", xbmc.LOGDEBUG)

        def _proxy(self):
            target = remote_url + self.path
            try:
                body = None
                content_length = int(self.headers.get('Content-Length', 0))
                if content_length > 0:
                    body = self.rfile.read(content_length)

                req = Request(target, data=body, method=self.command)
                # Forward relevant headers
                for header in ('Content-Type', 'Accept', 'User-Agent'):
                    val = self.headers.get(header)
                    if val:
                        req.add_header(header, val)

                with urlopen(req, timeout=300) as resp:
                    resp_body = resp.read()
                    self.send_response(resp.status)
                    for key, val in resp.getheaders():
                        if key.lower() not in ('transfer-encoding', 'connection'):
                            self.send_header(key, val)
                    self.end_headers()
                    self.wfile.write(resp_body)
            except URLError as e:
                error_msg = json.dumps({
                    "status": "error",
                    "message": f"Remote FlareSolverr unreachable: {e}",
                    "solution": remote_url,
                })
                self.send_response(502)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(error_msg.encode('utf-8'))
            except Exception as e:
                error_msg = json.dumps({
                    "status": "error",
                    "message": f"Proxy error: {e}",
                })
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(error_msg.encode('utf-8'))

        def do_GET(self):
            self._proxy()

        def do_POST(self):
            self._proxy()

    try:
        server = HTTPServer((local_host, local_port), ProxyHandler)
        xbmc.log(
            f"[FlareSolverr] Remote proxy listening on {local_host}:{local_port}",
            xbmc.LOGINFO,
        )
        server.serve_forever()
    except Exception as e:
        xbmc.log(f"[FlareSolverr] Remote proxy error: {e}", xbmc.LOGFATAL)


# ---------------------------------------------------------------------------
# Session cleanup
# ---------------------------------------------------------------------------

def cleanup_sessions():
    try:
        import flaresolverr_service
        import logging
        session_ids = list(flaresolverr_service.SESSIONS_STORAGE.session_ids())
        logging.info(f"Cleaning up {len(session_ids)} FlareSolverr sessions...")
        for sid in session_ids:
            flaresolverr_service.SESSIONS_STORAGE.destroy(sid)
    except Exception as e:
        import logging
        logging.error(f"Error cleaning up FlareSolverr sessions: {str(e)}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    monitor = xbmc.Monitor()

    # Purge stale __pycache__ to prevent bytecache from a previous addon
    # version from shadowing updated .py files.
    purge_pycache(ADDON_PATH)

    android = is_android()
    # server_mode: 0 = auto, 1 = local, 2 = remote
    # Kodi getSetting returns strings even for integer settings
    try:
        mode_int = int(ADDON.getSetting('server_mode') or '0')
    except (ValueError, TypeError):
        mode_int = 0

    MODE_AUTO = 0
    MODE_LOCAL = 1
    MODE_REMOTE = 2

    use_remote = (mode_int == MODE_REMOTE) or (mode_int == MODE_AUTO and android)

    if use_remote:
        xbmc.log("[FlareSolverr] Starting in REMOTE delegation mode", xbmc.LOGINFO)
        server_thread = threading.Thread(target=run_remote_proxy_mode)
        server_thread.daemon = True
        server_thread.start()
    else:
        xbmc.log("[FlareSolverr] Starting in LOCAL server mode", xbmc.LOGINFO)
        setup_flaresolverr_env()
        server_thread = threading.Thread(target=run_flaresolverr_server)
        server_thread.daemon = True
        server_thread.start()

    while not monitor.abortRequested():
        if monitor.waitForAbort(1):
            break

    import logging
    logging.info("FlareSolverr Service stopping...")
    if not use_remote:
        cleanup_sessions()
