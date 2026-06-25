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
    crashpad = os.path.join(chrome_dir, 'crashpad_handler')
    if os.path.exists(crashpad):
        os.chmod(crashpad, 0o755)
        
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
    os.environ["LOG_LEVEL"] = "info"
    
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

        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)-8s %(message)s')
        logging.getLogger('urllib3').setLevel(logging.ERROR)
        logging.getLogger('selenium.webdriver.remote.remote_connection').setLevel(logging.WARNING)
        logging.getLogger('undetected_chromedriver').setLevel(logging.WARNING)
        
        utils.get_current_platform()
        flaresolverr_service.test_browser_installation()

        app.install(logger_plugin)
        app.install(error_plugin)
        prometheus_plugin.setup()
        app.install(prometheus_plugin.prometheus_plugin)

        class WaitressServerPoll(ServerAdapter):
            def run(self, handler):
                from waitress import serve
                serve(handler, host=self.host, port=self.port, asyncore_use_poll=True)

        server_host = os.environ["HOST"]
        server_port = int(os.environ["PORT"])
        
        xbmc.log(f"Starting FlareSolverr server on {server_host}:{server_port}", xbmc.LOGINFO)
        run(app, host=server_host, port=server_port, quiet=True, server=WaitressServerPoll)
    except Exception as e:
        xbmc.log(f"FlareSolverr Server Error: {str(e)}", xbmc.LOGFATAL)

def cleanup_sessions():
    try:
        import flaresolverr_service
        session_ids = list(flaresolverr_service.SESSIONS_STORAGE.session_ids())
        xbmc.log(f"Cleaning up {len(session_ids)} FlareSolverr sessions...", xbmc.LOGINFO)
        for sid in session_ids:
            flaresolverr_service.SESSIONS_STORAGE.destroy(sid)
    except Exception as e:
        xbmc.log(f"Error cleaning up FlareSolverr sessions: {str(e)}", xbmc.LOGERROR)

if __name__ == '__main__':
    monitor = xbmc.Monitor()
    
    setup_flaresolverr_env()
    
    server_thread = threading.Thread(target=run_flaresolverr_server)
    server_thread.daemon = True
    server_thread.start()
    
    while not monitor.abortRequested():
        if monitor.waitForAbort(1):
            break
            
    xbmc.log("FlareSolverr Service stopping...", xbmc.LOGINFO)
    cleanup_sessions()
