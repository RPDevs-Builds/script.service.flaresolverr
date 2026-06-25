# FlareSolverr Service for Kodi

`script.service.flaresolverr` is a self-contained Kodi add-on that hosts a local instance of the [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr) proxy server to bypass Cloudflare and other advanced anti-bot protections.

By running FlareSolverr directly on your device, Kodi add-ons (such as Megacloud Decryptor or Otaku) can seamlessly resolve Cloudflare challenges without relying on external, third-party server infrastructure.

## Features
- **Local Proxy:** Runs entirely on-device, listening locally on port `8191` (configurable in settings).
- **Auto-Browser Provisioning:** Includes a smart downloader that automatically fetches and extracts a headless version of Chromium/Chrome if one isn't natively available on your system or within your Flatpak sandbox.
- **Zombie Process Management:** Safely destroys all active Selenium WebDriver instances when the Kodi add-on stops, preventing memory leaks and background hangs.
- **Upstream Auto-Sync:** Fully automated CI/CD pipeline synchronizes the core application source with the official upstream repository on GitHub every 24 hours.

## Installation
1. Navigate to the **Releases** page of this repository.
2. Download the latest `script.service.flaresolverr-vX.X.X.zip` file.
3. Open Kodi and go to **Add-ons** > **Install from zip file**.
4. Select the downloaded `.zip` file.

## Configuration
You can access the add-on settings via **Add-ons** > **My add-ons** > **Services** > **FlareSolverr Service** > **Configure**.
- **Host:** Default is `0.0.0.0` (accessible to your local network). You can restrict it to `127.0.0.1`.
- **Port:** Default is `8191`.
- **Headless Mode:** Enabled by default. Keeps the Chrome browser invisible.

## How it Works
When enabled, the add-on starts the standard FlareSolverr Waitress HTTP server as a background `xbmc.service`.

Because Kodi addon environments are often read-only (especially Flatpak installations on Linux), we dynamically monkey-patch the original `flaresolverr_service.py` to prevent hard crashes and enforce write-safe operations inside the Kodi `userdata/addon_data` directory. 

If Chrome is not found on your system, the add-on downloads Google's official "Chrome for Testing" Linux binaries and unpacks them locally into your Kodi profile, ensuring total portability.
