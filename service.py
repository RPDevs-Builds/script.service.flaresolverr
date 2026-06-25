import sys
import os
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

        # Setup standard Python logging to file
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

def cleanup_sessions():
    try:
        import flaresolverr_service
        import logging
        session_ids = list(flaresolverr_service.SESSIONS_STORAGE.session_ids())
        logging.info(f"Cleaning up {len(session_ids)} FlareSolverr sessions...")
        for sid in session_ids:
            flaresolverr_service.SESSIONS_STORAGE.destroy(sid)
    except Exception as e:
        logging.error(f"Error cleaning up FlareSolverr sessions: {str(e)}")

if __name__ == '__main__':
    monitor = xbmc.Monitor()
    
    setup_flaresolverr_env()
    
    server_thread = threading.Thread(target=run_flaresolverr_server)
    server_thread.daemon = True
    server_thread.start()
    
    while not monitor.abortRequested():
        if monitor.waitForAbort(1):
            break
            
    import logging
    logging.info("FlareSolverr Service stopping...")
    cleanup_sessions()
