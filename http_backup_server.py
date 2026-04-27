#!/usr/bin/env python3
"""
HTTP Backup Server - Sisi Server Sumber
========================================
Berjalan di server yang berisi file yang akan dibackup.
Menyajikan file melalui protokol HTTP agar dapat diambil oleh backup client.

Fitur:
- List semua file dengan metadata (path, size, modified date)
- Download file individual via HTTP streaming
- Autentikasi dengan token rahasia
- Filter ekstensi dan folder yang dikecualikan
- Multi-threaded untuk handling concurrent connections
- Hanya menggunakan Python standard library (tanpa pip install)

Penggunaan:
    python http_backup_server.py [path/ke/server_config.ini]

Buat file server_config.ini terlebih dahulu atau jalankan sekali untuk
membuat konfigurasi default.
"""

import os
import sys
import json
import logging
import configparser
import threading
import socket
import time
import itertools
from datetime import datetime
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
from socketserver import ThreadingMixIn

VERSION = "1.0.0"
CHUNK_SIZE = 64 * 1024  # 64KB per chunk saat transfer file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_size(size_bytes: int) -> str:
    """Format byte count menjadi string yang mudah dibaca (KB, MB, GB, ...)"""
    if size_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    size = float(size_bytes)
    while size >= 1024.0 and i < len(units) - 1:
        size /= 1024.0
        i += 1
    return f"{size:.1f} {units[i]}"


def setup_logging(log_file: str) -> logging.Logger:
    """Setup logging ke file dan console sekaligus"""
    logger = logging.getLogger("BackupServer")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    # File handler
    try:
        log_dir = os.path.dirname(os.path.abspath(log_file))
        os.makedirs(log_dir, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception as e:
        print(f"[WARN] Tidak dapat membuat log file '{log_file}': {e}")

    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


# ---------------------------------------------------------------------------
# Konfigurasi
# ---------------------------------------------------------------------------

class BackupServerConfig:
    """
    Membaca dan menyimpan konfigurasi dari server_config.ini.
    Jika file belum ada, dibuat otomatis dengan nilai default.
    """

    def __init__(self, config_path: str = "server_config.ini"):
        self.config_path = config_path
        self.config = configparser.ConfigParser()

        # Default values
        self.host = "0.0.0.0"
        self.port = 8765
        self.auth_token = ""
        self.source_dirs: dict = {}   # {name: absolute_path}
        self.exclude_extensions: list = []
        self.exclude_folders: list = []
        self.log_file = "backup_server.log"

        self._load_config()

    def _load_config(self):
        if not os.path.exists(self.config_path):
            self._create_default_config()
            # _create_default_config memanggil sys.exit(0) setelah tulis file

        self.config.read(self.config_path, encoding="utf-8")

        self.host      = self.config.get("SERVER", "Host",      fallback="0.0.0.0")
        self.port      = self.config.getint("SERVER", "Port",   fallback=8765)
        self.auth_token = self.config.get("SERVER", "AuthToken", fallback="")
        self.log_file  = self.config.get("SERVER", "LogFile",   fallback="backup_server.log")

        # Parse SourceDirectories: format "Nama1=path1;Nama2=path2"
        raw = self.config.get("SERVER", "SourceDirectories", fallback="")
        self.source_dirs = {}
        for item in raw.split(";"):
            item = item.strip()
            if "=" in item:
                name, path = item.split("=", 1)
                name, path = name.strip(), path.strip()
                if name and path:
                    self.source_dirs[name] = path

        # Filter ekstensi
        ext_raw = self.config.get("FILTERS", "ExcludeExtensions", fallback=".tmp;.bak")
        self.exclude_extensions = [
            e.strip().lower() for e in ext_raw.split(";") if e.strip()
        ]

        # Filter folder
        folder_raw = self.config.get("FILTERS", "ExcludeFolders",
                                     fallback="temp;cache;node_modules")
        self.exclude_folders = [
            f.strip().lower() for f in folder_raw.split(";") if f.strip()
        ]

    def _create_default_config(self):
        cfg = configparser.ConfigParser()
        cfg["SERVER"] = {
            "Host": "0.0.0.0",
            "Port": "8765",
            "AuthToken": "ganti_token_ini_dengan_string_rahasia_minimal_32_karakter",
            "LogFile": "backup_server.log",
            # Format: NamaSumber1=D:\\FolderData1;NamaSumber2=D:\\FolderData2
            "SourceDirectories": "Data=D:\\Data;Documents=D:\\Documents",
        }
        cfg["FILTERS"] = {
            "ExcludeExtensions": ".tmp;.bak;.log;.temp",
            "ExcludeFolders": "temp;cache;node_modules;$RECYCLE.BIN;System Volume Information",
        }

        with open(self.config_path, "w", encoding="utf-8") as f:
            cfg.write(f)

        print(f"\n[INFO] File konfigurasi default dibuat: {self.config_path}")
        print("[INFO] Harap edit file konfigurasi tersebut lalu jalankan server kembali.")
        print()
        print("  [SERVER]")
        print("  AuthToken  = ganti dengan string rahasia Anda")
        print("  SourceDirectories = NamaSumber=D:\\PathFolder;Nama2=D:\\Path2")
        print()
        sys.exit(0)


# ---------------------------------------------------------------------------
# Scanner Direktori
# ---------------------------------------------------------------------------

class FileScanner:
    """
    Scanner direktori untuk mendapatkan daftar file beserta metadata.
    Menerapkan filter ekstensi dan folder dari konfigurasi.
    """

    def __init__(self, config: BackupServerConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger

    def _should_exclude(self, file_path: Path) -> bool:
        """
        Kembalikan True jika file harus dikecualikan dari backup.
        Cek berdasarkan ekstensi dan nama folder induk.
        """
        # Cek ekstensi
        if file_path.suffix.lower() in self.config.exclude_extensions:
            return True

        # Cek apakah ada folder yang dikecualikan di dalam path
        parts_lower = [p.lower() for p in file_path.parts]
        for folder in self.config.exclude_folders:
            if folder in parts_lower:
                return True

        return False

    def scan_all_sources(self) -> list:
        """
        Scan semua direktori sumber yang dikonfigurasi.
        Kembalikan list dict berisi metadata setiap file.
        """
        all_files = []

        for source_name, source_path in self.config.source_dirs.items():
            source = Path(source_path)
            if not source.exists() or not source.is_dir():
                self.logger.warning(
                    f"Source directory tidak ditemukan: '{source_path}' (source: {source_name})"
                )
                continue

            count = 0
            total_size = 0
            try:
                for file_path in source.rglob("*"):
                    if not file_path.is_file():
                        continue
                    if self._should_exclude(file_path):
                        continue

                    try:
                        stat = file_path.stat()
                        # Simpan relative path dengan separator '/' (cross-platform)
                        relative = str(file_path.relative_to(source)).replace("\\", "/")
                        all_files.append({
                            "source":        source_name,
                            "relative_path": relative,
                            "size":          stat.st_size,
                            "mtime":         stat.st_mtime,   # Unix timestamp float
                        })
                        count += 1
                        total_size += stat.st_size
                    except (OSError, ValueError):
                        continue  # File mungkin dihapus saat scan berlangsung

            except Exception as e:
                self.logger.error(f"Error scanning '{source_path}': {e}")

            self.logger.info(
                f"Scanned source '{source_name}': {count} files, "
                f"{_format_size(total_size)}"
            )

        return all_files

    def resolve_file_path(self, source_name: str, relative_path: str):
        """
        Resolve dan validasi path file yang diminta oleh client.

        Mencegah path traversal attack dengan memastikan file yang diresolve
        masih berada di dalam direktori sumber yang dikonfigurasi.

        Returns:
            Path object jika valid, None jika tidak valid/ditemukan.
        """
        if source_name not in self.config.source_dirs:
            return None

        source_base = Path(self.config.source_dirs[source_name]).resolve()

        # Normalisasi: ganti backslash, buang leading slash
        clean_rel = relative_path.replace("\\", "/").strip("/")

        # Tolak jika ada komponen '..' dalam path
        if ".." in clean_rel.split("/"):
            self.logger.warning(
                f"Path traversal attempt ditolak: source={source_name}, path={relative_path}"
            )
            return None

        target = (source_base / clean_rel).resolve()

        # Pastikan target masih berada di dalam source_base (double-check)
        try:
            target.relative_to(source_base)
        except ValueError:
            self.logger.warning(
                f"Path escapes source directory: source={source_name}, path={relative_path}"
            )
            return None

        if not target.exists() or not target.is_file():
            return None

        return target


# ---------------------------------------------------------------------------
# HTTP Request Handler
# ---------------------------------------------------------------------------

def make_handler(config: BackupServerConfig,
                 logger: logging.Logger,
                 scanner: FileScanner):
    """
    Factory function yang mengembalikan kelas HTTP request handler
    dengan akses ke config, logger, dan scanner.
    """

    class BackupRequestHandler(BaseHTTPRequestHandler):
        """
        Menangani HTTP GET request dari backup client.

        Endpoints:
          GET /health              -> status server (tanpa autentikasi)
          GET /api/files           -> daftar semua file dengan metadata
          GET /api/file?source=X&path=Y -> download file tertentu
        """

        # Semaphore untuk membatasi concurrent scan (agar tidak overlapping)
        _scan_lock = threading.Lock()

        def log_message(self, format_str, *args):
            logger.debug(f"{self.address_string()} - {format_str % args}")

        def log_error(self, format_str, *args):
            logger.error(f"{self.address_string()} - {format_str % args}")

        # ---- Helpers -------------------------------------------------------

        def _send_json(self, status_code: int, data: dict):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_error(self, status_code: int, message: str):
            self._send_json(status_code, {"error": message, "status": "error"})

        def _authenticate(self) -> bool:
            """
            Validasi X-Auth-Token header.
            Juga menerima ?token=... di query string sebagai fallback.
            Jika AuthToken tidak dikonfigurasi, semua request diizinkan.
            """
            if not config.auth_token:
                return True  # Tanpa token, akses terbuka

            token = self.headers.get("X-Auth-Token", "")
            if not token:
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)
                token = params.get("token", [""])[0]

            return token == config.auth_token

        # ---- Router --------------------------------------------------------

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path

            # /health tidak memerlukan autentikasi
            if path != "/health" and not self._authenticate():
                logger.warning(f"Auth gagal dari {self.address_string()}")
                self._send_error(401, "Autentikasi diperlukan. Sertakan X-Auth-Token header.")
                return

            if path == "/health":
                self._handle_health()
            elif path == "/api/files":
                self._handle_files_list()
            elif path == "/api/file":
                params = parse_qs(parsed.query)
                source   = params.get("source", [""])[0]
                rel_path = params.get("path",   [""])[0]
                self._handle_file_download(source, rel_path)
            else:
                self._send_error(404, f"Endpoint '{path}' tidak ditemukan.")

        # ---- Endpoint handlers ---------------------------------------------

        def _handle_health(self):
            """GET /health - health check, tidak perlu autentikasi"""
            self._send_json(200, {
                "status":    "ok",
                "version":   VERSION,
                "timestamp": datetime.now().isoformat(),
                "sources":   list(config.source_dirs.keys()),
            })

        def _handle_files_list(self):
            """
            GET /api/files
            Scan semua source directory dan kembalikan list metadata file.
            """
            client_ip = self.address_string()
            logger.info(f"[{client_ip}] Request daftar file diterima")

            try:
                start = time.time()

                # Gunakan lock agar scan tidak tumpang-tindih jika banyak client
                with BackupRequestHandler._scan_lock:
                    files = scanner.scan_all_sources()

                elapsed = round(time.time() - start, 2)
                logger.info(
                    f"[{client_ip}] Mengirim {len(files)} file ke client "
                    f"(scan {elapsed}s)"
                )

                self._send_json(200, {
                    "files":                files,
                    "total_files":          len(files),
                    "scan_duration_seconds": elapsed,
                    "timestamp":            datetime.now().isoformat(),
                    "version":              VERSION,
                })

            except Exception as e:
                logger.error(f"[{client_ip}] Error saat scan: {e}", exc_info=True)
                self._send_error(500, f"Server error: {str(e)}")

        def _handle_file_download(self, source_name: str, relative_path: str):
            """
            GET /api/file?source=<name>&path=<url_encoded_path>
            Stream konten file ke client.
            """
            if not source_name or not relative_path:
                self._send_error(400, "Parameter 'source' dan 'path' diperlukan.")
                return

            # URL decode path
            relative_path = unquote(relative_path)

            file_path = scanner.resolve_file_path(source_name, relative_path)
            if file_path is None:
                self._send_error(404, "File tidak ditemukan atau akses ditolak.")
                return

            try:
                stat = file_path.stat()
                file_size = stat.st_size
                file_mtime = stat.st_mtime

                self.send_response(200)
                self.send_header("Content-Type",   "application/octet-stream")
                self.send_header("Content-Length", str(file_size))
                self.send_header("X-File-Size",    str(file_size))
                self.send_header("X-File-Mtime",   str(file_mtime))
                self.end_headers()

                bytes_sent = 0
                with open(file_path, "rb") as f:
                    while True:
                        chunk = f.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        bytes_sent += len(chunk)

                logger.info(
                    f"Sent: [{source_name}] {relative_path} "
                    f"({_format_size(bytes_sent)}) -> {self.address_string()}"
                )

            except BrokenPipeError:
                logger.warning(
                    f"Client {self.address_string()} terputus saat download: "
                    f"{source_name}/{relative_path}"
                )
            except Exception as e:
                logger.error(
                    f"Error mengirim file '{source_name}/{relative_path}': {e}",
                    exc_info=True
                )

    return BackupRequestHandler


# ---------------------------------------------------------------------------
# Threaded HTTP Server
# ---------------------------------------------------------------------------

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """
    HTTP Server yang menangani setiap request di thread terpisah
    sehingga download besar tidak mengblokir request lain.
    """
    daemon_threads = True
    allow_reuse_address = True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Ambil path config dari argumen pertama (opsional)
    config_path = sys.argv[1] if len(sys.argv) > 1 else "server_config.ini"

    # Load konfigurasi (akan auto-create & exit jika belum ada)
    config = BackupServerConfig(config_path)

    # Setup logging
    logger = setup_logging(config.log_file)

    # Peringatan keamanan jika token masih default
    if (not config.auth_token
            or "ganti_token" in config.auth_token.lower()):
        logger.warning("=" * 60)
        logger.warning("PERINGATAN KEAMANAN: AuthToken masih default atau kosong!")
        logger.warning("Set AuthToken di server_config.ini sebelum produksi.")
        logger.warning("=" * 60)

    # Validasi ada minimal satu source directory
    if not config.source_dirs:
        logger.error("Tidak ada SourceDirectories yang dikonfigurasi! Edit server_config.ini")
        sys.exit(1)

    # Cek keberadaan source directories
    for name, path in config.source_dirs.items():
        if os.path.exists(path):
            logger.info(f"  Source '{name}': {path}  [OK]")
        else:
            logger.warning(f"  Source '{name}': {path}  [TIDAK DITEMUKAN]")

    # Buat scanner dan handler
    scanner = FileScanner(config, logger)
    handler_class = make_handler(config, logger, scanner)

    # Dapatkan IP lokal untuk ditampilkan
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = "unknown"

    # Start server
    server = ThreadedHTTPServer((config.host, config.port), handler_class)

    print()
    print("╔" + "═" * 58 + "╗")
    print("║" + f"  HTTP BACKUP SERVER  v{VERSION}".center(58) + "║")
    print("╠" + "═" * 58 + "╣")
    print(f"║  Listen : {config.host}:{config.port}".ljust(59) + "║")
    print(f"║  Local IP : {local_ip}".ljust(59) + "║")
    print(f"║  Log    : {config.log_file}".ljust(59) + "║")
    print("╠" + "═" * 58 + "╣")
    print("║  Source Directories:".ljust(59) + "║")
    for name, path in config.source_dirs.items():
        status = "OK" if os.path.exists(path) else "NOT FOUND"
        line = f"    [{status}] {name}: {path}"
        if len(line) > 56:
            line = line[:53] + "..."
        print(f"║  {line.ljust(56)}  ║")
    print("╠" + "═" * 58 + "╣")
    print("║  API Endpoints:".ljust(59) + "║")
    print(f"║    GET /health          -> status server".ljust(59) + "║")
    print(f"║    GET /api/files       -> daftar semua file".ljust(59) + "║")
    print(f"║    GET /api/file?...    -> download file".ljust(59) + "║")
    print("╠" + "═" * 58 + "╣")
    print("║  Server berjalan... Tekan Ctrl+C untuk berhenti.".ljust(59) + "║")
    print("╚" + "═" * 58 + "╝")
    print()

    logger.info(
        f"HTTP Backup Server v{VERSION} dimulai. "
        f"Listen: {config.host}:{config.port}, "
        f"Sources: {list(config.source_dirs.keys())}"
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server dihentikan oleh pengguna (Ctrl+C).")
        print("\nServer dihentikan.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
