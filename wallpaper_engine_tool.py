from __future__ import annotations
import base64
import json
import shutil
import subprocess
import re
import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import requests
from bs4 import BeautifulSoup
import ctypes
import winreg
import webview
from flask import Flask, jsonify, request, send_from_directory

APPID = "431960"
RELATIVE_PATH = Path("projects/myprojects")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
STEAM_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9",
}
ROOT_DIR = Path(__file__).resolve().parent.parent
APP_DIR = Path(__file__).resolve().parent
RESOURCES_DIR = APP_DIR / "resources"
SECRET_KEY = b"wallpaper-engine-secret"
ENCRYPTED_ACCOUNTS = [
    {"username": "ruiiixx", "password": "JFdbKzI1Ml1BaVY3"},
    {"username": "premexilmenledgconis", "password": "RBE0Djg7Ogk2Tw=="},
    {"username": "vAbuDy", "password": "NQ4DAAFZBgwC"},
    {"username": "adgjl1182", "password": "JiQ4OT9YSVxLFA=="},
    {"username": "gobjj16182", "password": "DRQDDhkAH11AH1c="},
    {"username": "787109690", "password": "PxQPOQg4PTQbSlRb"},
]


def log(msg: str):
    print(f"[debug] {msg}", flush=True)
def bundled_path(relative: str) -> Path:
    if getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS) / relative
    return APP_DIR / relative


DEPOT_EXE = bundled_path("DepotDownloaderMod/DepotDownloaderMod.exe")
FLASK_PORT = 5005


def xor_decrypt(encoded: str) -> str:
    data = base64.b64decode(encoded)
    out = bytes([b ^ SECRET_KEY[i % len(SECRET_KEY)] for i, b in enumerate(data)])
    return out.decode("utf-8")


def get_game_config(appid: str = APPID) -> Dict[str, object]:
    if appid != APPID:
        raise ValueError("Unsupported appid")
    log("Loading game config and decrypting accounts")
    accounts: List[Dict[str, str]] = []
    for entry in ENCRYPTED_ACCOUNTS:
        try:
            accounts.append(
                {"username": entry["username"], "password": xor_decrypt(entry["password"])}
            )
        except Exception:
            continue
    return {"accounts": accounts, "relative_path": RELATIVE_PATH}


def get_steam_path_from_registry() -> Optional[Path]:
    log("Checking Steam registry keys...")
    reg_paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Valve\Steam", "SteamPath"),
    ]
    for root, subkey, value_name in reg_paths:
        try:
            with winreg.OpenKey(root, subkey) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
                path = Path(str(value)).expanduser()
                if path.exists():
                    log(f"Found Steam path via registry: {path}")
                    return path
        except FileNotFoundError:
            continue
        except OSError:
            continue

    for fallback in (
        Path(r"C:\Program Files (x86)\Steam"),
        Path(r"C:\Program Files\Steam"),
        Path.home() / "Steam",
    ):
        if fallback.exists():
            log(f"Found Steam via fallback: {fallback}")
            return fallback
    return None


def get_install_dir_from_registry() -> Optional[Path]:
    log("Checking Wallpaper Engine registry key...")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\WallpaperEngine") as key:
            value, _ = winreg.QueryValueEx(key, "installPath")
            install_path = Path(str(value)).expanduser()
            if install_path.suffix.lower() == ".exe":
                install_path = install_path.parent
            if install_path.exists():
                log(f"Found install dir via registry: {install_path}")
                return install_path
    except FileNotFoundError:
        return None
    except OSError:
        return None
    return None


def find_install_dir(appid: str = APPID) -> Optional[Path]:
    registry_dir = get_install_dir_from_registry()
    if registry_dir:
        return registry_dir

    steam_root = get_steam_path_from_registry()
    if not steam_root:
        log("Steam root not found")
        return None
    for steamapps_name in ("steamapps", "SteamApps"):
        steamapps = steam_root / steamapps_name
        manifest = steamapps / f"appmanifest_{appid}.acf"
        if manifest.exists():
            content = manifest.read_text(errors="ignore")
            match = re.search(r'"installdir"\s+"(.+?)"', content)
            if match:
                candidate = steamapps / "common" / match.group(1)
                if candidate.exists():
                    log(f"Found install dir: {candidate}")
                    return candidate
    return None


def wallpaper_base_dir(appid: str = APPID) -> Optional[Path]:
    install_dir = find_install_dir(appid)
    if not install_dir:
        return None
    cfg = get_game_config(appid)
    target = install_dir / cfg["relative_path"]
    target.mkdir(parents=True, exist_ok=True)
    log(f"Wallpaper base dir: {target}")
    return target


def rating_image_to_stars(rating_url: str) -> str:
    if not rating_url:
        return ""
    match = re.search(r"(\d)-star\.png", rating_url)
    return "★" * int(match.group(1)) if match else ""


def fetch_item_metadata(workshop_id: str) -> Dict[str, str]:
    log(f"Fetching item metadata {workshop_id}")
    url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}"
    response = requests.get(url, headers=STEAM_HEADERS, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    title = soup.select_one(".workshopItemTitle")
    author = soup.select_one(".friendBlockContent")
    img = (
        soup.select_one("#previewImageMain")
        or soup.select_one("#previewImage")
        or soup.select_one("img.workshopItemPreviewImage")
    )
    rating_img = soup.select_one(".fileRating")
    return {
        "id": workshop_id,
        "title": title.get_text(strip=True) if title else workshop_id,
        "author": author.get_text(strip=True) if author else "Unknown",
        "img": img["src"].split("?", 1)[0] if img and img.get("src") else "",
        "link": url,
        "rating": rating_image_to_stars(rating_img["src"]) if rating_img and rating_img.get("src") else "",
    }


def fetch_top_wallpapers(
    page: int = 1,
    searchtext: str = "",
    sortmethod: str = "trend",
    timeperiod: str = "-1",
    numperpage: int = 24,
) -> List[Dict[str, str]]:
    log(f"Fetching workshop page={page} search='{searchtext}'")
    base_url = (
        f"https://steamcommunity.com/workshop/browse/?appid={APPID}"
        f"&browsesort={sortmethod}"
        f"&actualsort={sortmethod}"
        f"&section=readytouseitems"
        f"&p={page}"
        f"&days={timeperiod}"
        f"&numperpage={numperpage}"
        f"&created_date_range_filter_start=0&created_date_range_filter_end=0"
        f"&updated_date_range_filter_start=0&updated_date_range_filter_end=0"
    )
    searchtext = searchtext.strip()
    if searchtext:
        base_url += f"&searchtext={requests.utils.quote(searchtext)}"

    response = requests.get(base_url, headers=STEAM_HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    items: List[Dict[str, str]] = []

    for element in soup.select(".workshopItem"):
        pfid = element.get("data-publishedfileid")
        if not pfid:
            link_tag = element.find("a")
            pfid = link_tag.get("data-publishedfileid") if link_tag else None
        title = element.select_one(".workshopItemTitle")
        img = element.select_one(".workshopItemPreviewImage")
        author = element.select_one(".workshopItemAuthorName a")
        link_holder = element.select_one("a.workshopItemPreviewHolder")

        if not pfid or not title or not img:
            continue

        rating_img = ""
        file_rating = element.select_one(".fileRating")
        if file_rating and file_rating.get("src"):
            rating_img = file_rating["src"]

        items.append(
            {
                "id": pfid,
                "title": title.get_text(strip=True),
                "img": img.get("src", ""),
                "author": author.get_text(strip=True) if author else "Unknown",
                "link": link_holder.get("href", "") if link_holder else "",
                "rating": rating_image_to_stars(rating_img),
                "rating_img": rating_img,
            }
        )

    return items


def run_depot_download(workshop_id: str, appid: str = APPID) -> Tuple[bool, str, Optional[Path]]:
    if not DEPOT_EXE.exists():
        log("DepotDownloaderMod.exe missing")
        return False, "DepotDownloaderMod.exe not found", None

    base_dir = wallpaper_base_dir(appid)
    if not base_dir:
        return False, "Wallpaper Engine folder not found", None

    target_dir = base_dir / workshop_id
    target_dir.mkdir(parents=True, exist_ok=True)

    cfg = get_game_config(appid)
    account_entries = cfg.get("accounts", [])
    if not account_entries:
        return False, "No accounts configured", None

    last_error = "All accounts failed"
    for acct in account_entries:
        username = acct.get("username")
        password = acct.get("password")
        if not username or not password:
            continue
        log(f"Trying Depot download for {workshop_id} using {username}")
        args = [
            str(DEPOT_EXE),
            "-app",
            appid,
            "-pubfile",
            workshop_id,
            "-username",
            username,
            "-password",
            password,
            "-verify-all",
            "-dir",
            str(target_dir),
        ]
        try:
            proc = subprocess.run(
                args,
                cwd=DEPOT_EXE.parent,
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
                creationflags=_NO_WINDOW,
            )
            log(proc.stdout)
            if proc.stderr:
                print(proc.stderr, file=sys.stderr)
            if proc.returncode == 0:
                try:
                    meta = fetch_item_metadata(workshop_id)
                    (target_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
                except Exception:
                    pass
                return True, "Download complete", target_dir
            last_error = proc.stderr.strip() or proc.stdout.strip() or "Download failed"
        except FileNotFoundError:
            return False, "DepotDownloaderMod.exe not found", None
        except subprocess.TimeoutExpired:
            last_error = "Download timed out, trying next account"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            continue
    return False, last_error, None


def list_local_downloads() -> List[Dict[str, str]]:
    base_dir = wallpaper_base_dir()
    if not base_dir or not base_dir.exists():
        log("No wallpaper base dir; list_local_downloads empty")
        return []
    items: List[Dict[str, str]] = []
    for entry in sorted(base_dir.iterdir()):
        if entry.is_dir():
            meta_file = entry / "meta.json"
            meta: Dict[str, str] = {
                "id": entry.name,
                "title": f"Workshop {entry.name}",
                "author": "",
                "img": "",
                "link": f"https://steamcommunity.com/sharedfiles/filedetails/?id={entry.name}",
                "rating": "",
                "path": str(entry),
            }
            if meta_file.exists():
                try:
                    loaded = json.loads(meta_file.read_text(encoding="utf-8"))
                    meta.update(loaded)
                except Exception:
                    pass
            else:
                try:
                    fetched = fetch_item_metadata(entry.name)
                    meta.update(fetched)
                    meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")
                except Exception:
                    pass
            meta["path"] = str(entry)
            try:
                meta["pathShort"] = f"\\projects\\myprojects\\{entry.name}"
            except Exception:
                meta["pathShort"] = meta["path"]
            items.append(meta)
    log(f"Found {len(items)} local downloads")
    return items


def delete_download(workshop_id: str) -> bool:
    base_dir = wallpaper_base_dir()
    if not base_dir:
        return False
    candidate = (base_dir / workshop_id).resolve()
    if base_dir not in candidate.parents and candidate != base_dir:
        return False
    if candidate.exists():
        shutil.rmtree(candidate, ignore_errors=True)
        return True
    return False


class Api:
    def get_info(self):
        log("API get_info called")
        install_dir = find_install_dir()
        download_dir = wallpaper_base_dir()
        return {
            "install_dir": str(install_dir) if install_dir else None,
            "download_dir": str(download_dir) if download_dir else None,
            "depot_exists": DEPOT_EXE.exists(),
        }

    def list_downloads(self):
        log("API list_downloads called")
        return {"items": list_local_downloads()}

    def search_workshop(self, searchtext: str = "", page: int = 1, sortmethod: str = "trend", timeperiod: str = "-1"):
        log(f"API search_workshop '{searchtext}' page {page} sort={sortmethod} time={timeperiod}")
        items = fetch_top_wallpapers(page=page, searchtext=searchtext, sortmethod=sortmethod, timeperiod=timeperiod)
        return {"items": items}

    def get_item(self, workshop_id: str):
        log(f"API get_item {workshop_id}")
        return fetch_item_metadata(workshop_id)

    def download(self, workshop_id: str):
        log(f"API download {workshop_id}")
        success, message, path = run_depot_download(workshop_id)
        return {"success": success, "message": message, "path": str(path) if path else None}

    def delete(self, workshop_id: str):
        log(f"API delete {workshop_id}")
        ok = delete_download(workshop_id)
        return {"success": ok}

    def open_folder(self, workshop_id: str):
        log(f"API open_folder {workshop_id}")
        base_dir = wallpaper_base_dir()
        if not base_dir:
            return {"success": False, "message": "Wallpaper Engine folder not found"}
        candidate = (base_dir / workshop_id).resolve()
        if base_dir not in candidate.parents and candidate != base_dir:
            return {"success": False, "message": "Invalid path"}
        if not candidate.exists():
            return {"success": False, "message": "Folder not found"}
        try:
            import os

            os.startfile(candidate)  # type: ignore[attr-defined]
            return {"success": True}
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "message": str(exc)}


def create_flask_app(api_instance: Api, *, port: int = FLASK_PORT) -> Flask:
    templates_root = bundled_path("templates")
    static_root = bundled_path("static")
    resources_root = RESOURCES_DIR
    app = Flask(
        __name__,
        static_folder=str(static_root),
        template_folder=str(templates_root),
    )

    @app.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,DELETE,OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    @app.route("/")
    def serve_index():
        index_file = Path(app.template_folder) / "index.html"
        if not index_file.exists():
            return (
                "templates/index.html missing. When packaging, include templates/static/resources "
                "via PyInstaller --add-data.",
                500,
            )
        return send_from_directory(app.template_folder, "index.html")

    @app.route("/static/<path:filename>")
    def serve_static(filename: str):
        return send_from_directory(app.static_folder, filename)

    @app.route("/resources/<path:filename>")
    def serve_resources(filename: str):
        return send_from_directory(str(resources_root), filename)

    @app.route("/api/info")
    def api_info():
        return jsonify(api_instance.get_info())

    @app.route("/api/downloads")
    def api_downloads():
        return jsonify(api_instance.list_downloads())

    @app.route("/api/search")
    def api_search():
        searchtext = request.args.get("searchtext", "")
        try:
            page = int(request.args.get("page", "1"))
        except ValueError:
            page = 1
        sortmethod = request.args.get("sortmethod", "trend")
        timeperiod = request.args.get("timeperiod", "-1")
        return jsonify(api_instance.search_workshop(searchtext, page, sortmethod, timeperiod))

    @app.route("/api/item/<workshop_id>")
    def api_item(workshop_id: str):
        return jsonify(api_instance.get_item(workshop_id))

    @app.route("/api/download", methods=["POST"])
    def api_download():
        payload = request.get_json(force=True, silent=True) or {}
        workshop_id = payload.get("workshop_id") or payload.get("id")
        if not workshop_id:
            return jsonify({"success": False, "message": "Missing workshop_id"}), 400
        return jsonify(api_instance.download(workshop_id))

    @app.route("/api/download/<workshop_id>", methods=["DELETE"])
    def api_delete(workshop_id: str):
        return jsonify(api_instance.delete(workshop_id))

    @app.route("/api/open-folder", methods=["POST"])
    def api_open_folder():
        payload = request.get_json(force=True, silent=True) or {}
        workshop_id = payload.get("workshop_id") or payload.get("id")
        if not workshop_id:
            return jsonify({"success": False, "message": "Missing workshop_id"}), 400
        return jsonify(api_instance.open_folder(workshop_id))

    return app


def start_flask_server(api_instance: Api, *, port: int = FLASK_PORT) -> threading.Thread:
    app = create_flask_app(api_instance, port=port)

    def _run():
        log(f"Starting Flask API server on http://127.0.0.1:{port}")
        app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread


def get_screen_dimensions() -> Tuple[int, int]:
    """
    Grab the primary screen dimensions. If anything fails, fall back to a sane default.
    """
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
    except Exception:
        return 1920, 1080


def run():
    api = Api()
    start_flask_server(api, port=FLASK_PORT)
    html_path = f"http://127.0.0.1:{FLASK_PORT}"
    log(f"Loading UI from {html_path}")
    screen_w, screen_h = get_screen_dimensions()
    border = 32
    window_width = max(800, screen_w - border * 2)
    window_height = max(600, screen_h - border * 2)
    webview.create_window(
        "Wallpaper Engine Downloader",
        html_path,
        js_api=api,
        width=window_width,
        height=window_height,
        x=border,
        y=border,
    )
    webview.start(debug=False)


if __name__ == "__main__":
    run()
