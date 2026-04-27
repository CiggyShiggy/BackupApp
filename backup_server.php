<?php
/**
 * HTTP Backup Server - PHP Edition for Apache
 * =============================================
 * Drop-in replacement untuk http_backup_server.py.
 * Berjalan di bawah Apache yang sudah ada — tidak perlu server tambahan.
 *
 * Persyaratan:
 *   - Apache dengan mod_rewrite aktif
 *   - PHP 7.2+ (tidak perlu extension tambahan)
 *
 * Cara deploy:
 *   1. Copy file ini dan backup_server_config.ini ke subdirektori di web root.
 *      Contoh: C:\Apache24\htdocs\backup\
 *   2. Pastikan .htaccess juga ikut dicopy (untuk routing dan proteksi).
 *   3. Edit backup_server_config.ini (token, folder sumber).
 *   4. Di client_config.ini ubah ServerUrl ke:
 *      http://IP_SERVER/backup   (sesuai nama subdirektori)
 *
 * API Endpoints (sama persis dengan http_backup_server.py):
 *   GET /backup/health              -> status server (tanpa autentikasi)
 *   GET /backup/api/files           -> daftar semua file + metadata
 *   GET /backup/api/file?source=X&path=Y -> download file (streaming)
 *
 * Autentikasi: header X-Auth-Token atau query string ?token=...
 */

define('VERSION', '1.0.0');
define('CHUNK_SIZE', 65536); // 64 KB per chunk saat streaming file


// ============================================================
// Fungsi Pembantu (Helper)
// ============================================================

/**
 * Kirim response JSON dan hentikan eksekusi script.
 */
function send_json($code, $data)
{
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    // Hapus output buffer agar tidak ada karakter ekstra sebelum JSON
    if (ob_get_level()) {
        ob_end_clean();
    }
    echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

/**
 * Kirim response error JSON.
 */
function send_error($code, $message)
{
    send_json($code, ['error' => $message, 'status' => 'error']);
}

/**
 * Format byte count menjadi string mudah dibaca (KB, MB, GB, ...).
 */
function format_size($bytes)
{
    $units = ['B', 'KB', 'MB', 'GB', 'TB'];
    $i = 0;
    $size = (float) $bytes;
    while ($size >= 1024.0 && $i < count($units) - 1) {
        $size /= 1024.0;
        $i++;
    }
    return round($size, 1) . ' ' . $units[$i];
}

/**
 * Tulis baris log ke file. Tidak melempar exception jika gagal.
 */
function log_message($log_file, $level, $message)
{
    if ($log_file === '') {
        return;
    }
    $line = date('Y-m-d H:i:s') . " [{$level}] {$message}" . PHP_EOL;
    @file_put_contents($log_file, $line, FILE_APPEND | LOCK_EX);
}

/**
 * Parse format "Nama1=path1;Nama2=path2" menjadi array asosiatif.
 */
function parse_source_dirs($raw)
{
    $dirs = [];
    foreach (explode(';', $raw) as $item) {
        $item = trim($item);
        if (strpos($item, '=') !== false) {
            list($name, $path) = explode('=', $item, 2);
            $name = trim($name);
            $path = trim($path);
            if ($name !== '' && $path !== '') {
                $dirs[$name] = $path;
            }
        }
    }
    return $dirs;
}

/**
 * Pecah string yang dipisahkan titik koma menjadi array bersih.
 */
function parse_list($raw)
{
    $result = [];
    foreach (explode(';', $raw) as $item) {
        $item = trim($item);
        if ($item !== '') {
            $result[] = $item;
        }
    }
    return $result;
}

/**
 * Validasi token autentikasi dari header atau query string.
 * Menggunakan hash_equals() untuk mencegah timing attack.
 */
function authenticate($expected_token)
{
    // Prioritas: header X-Auth-Token
    $token = isset($_SERVER['HTTP_X_AUTH_TOKEN']) ? $_SERVER['HTTP_X_AUTH_TOKEN'] : '';

    // Fallback ke query string ?token=
    if ($token === '' && isset($_GET['token'])) {
        $token = $_GET['token'];
    }

    return hash_equals($expected_token, $token);
}

/**
 * Kembalikan true jika file harus dikecualikan berdasarkan ekstensi atau nama folder.
 *
 * @param string $abs_path   Path absolut file
 * @param array  $exc_ext    Daftar ekstensi dikecualikan, e.g. ['.tmp', '.bak']
 * @param array  $exc_folders Daftar nama folder dikecualikan
 */
function should_exclude($abs_path, $exc_ext, $exc_folders)
{
    // Cek ekstensi (normalisasi ke lowercase dengan dot prefix)
    $ext_raw  = strtolower(pathinfo($abs_path, PATHINFO_EXTENSION));
    $ext_dot  = '.' . $ext_raw;
    foreach ($exc_ext as $ex) {
        $ex_lower = strtolower(trim($ex));
        if ($ex_lower === $ext_dot || $ex_lower === $ext_raw) {
            return true;
        }
    }

    // Cek folder — normalisasi separator agar konsisten
    $normalized = str_replace('\\', '/', $abs_path);
    $parts      = array_map('strtolower', explode('/', $normalized));
    foreach ($exc_folders as $folder) {
        if (in_array(strtolower(trim($folder)), $parts, true)) {
            return true;
        }
    }

    return false;
}

/**
 * Resolve dan validasi path file yang diminta client.
 *
 * Mencegah path traversal attack dengan:
 *   1. Menolak komponen '..' secara eksplisit.
 *   2. Memverifikasi hasil realpath() masih berada di dalam source_base.
 *
 * @return string|null  Path absolut tervalidasi, atau null jika tidak valid.
 */
function resolve_file_path($source_name, $relative_path, $source_dirs)
{
    if (!isset($source_dirs[$source_name])) {
        return null;
    }

    $source_base = realpath($source_dirs[$source_name]);
    if ($source_base === false || !is_dir($source_base)) {
        return null;
    }

    // Tolak secara eksplisit komponen '..' dalam path
    $clean_rel = str_replace(['\\', '/'], DIRECTORY_SEPARATOR, $relative_path);
    $clean_rel = ltrim($clean_rel, DIRECTORY_SEPARATOR);
    $parts     = explode(DIRECTORY_SEPARATOR, $clean_rel);
    if (in_array('..', $parts, true) || in_array('.', $parts, true)) {
        return null;
    }

    $target      = $source_base . DIRECTORY_SEPARATOR . $clean_rel;
    $target_real = realpath($target);

    if ($target_real === false || !is_file($target_real)) {
        return null;
    }

    // Double-check: target harus berada DI DALAM source_base
    // Gunakan perbandingan case-insensitive di Windows
    $base_prefix = $source_base . DIRECTORY_SEPARATOR;
    if (DIRECTORY_SEPARATOR === '\\') {
        // Windows — case-insensitive
        if (stripos($target_real, $base_prefix) !== 0) {
            return null;
        }
    } else {
        if (strpos($target_real, $base_prefix) !== 0) {
            return null;
        }
    }

    return $target_real;
}

/**
 * Buat file konfigurasi default jika belum ada.
 */
function create_default_config($config_path)
{
    $content = <<<'INI'
[SERVER]
; ============================================================
;  HTTP Backup Server - Konfigurasi
; ============================================================

; Token rahasia untuk autentikasi. WAJIB diganti.
; Generate contoh: php -r "echo bin2hex(random_bytes(32));"
; Token ini harus SAMA dengan AuthToken di client_config.ini
AuthToken = ganti_token_ini_dengan_string_rahasia_minimal_32_karakter

; Path file log. Bisa path absolut atau relatif terhadap script ini.
LogFile = backup_server.log

; Daftar direktori yang di-expose via HTTP.
; Format: NamaSumber=D:\PathFolder
; Pisahkan dengan titik koma (;). Nama tidak boleh mengandung spasi.
SourceDirectories = Data=D:\Data;Documents=D:\Documents

[FILTERS]
; Ekstensi file yang dikecualikan dari backup.
ExcludeExtensions = .tmp;.bak;.log;.temp;.swp;.lock

; Nama folder yang dikecualikan (berlaku rekursif di semua level).
ExcludeFolders = temp;cache;node_modules;.git;$RECYCLE.BIN;System Volume Information;__pycache__
INI;

    file_put_contents($config_path, $content);
}


// ============================================================
// Endpoint Handlers
// ============================================================

/**
 * GET /health — Cek status server (tidak memerlukan autentikasi).
 */
function handle_health($source_dirs)
{
    $sources_status = [];
    foreach ($source_dirs as $name => $path) {
        $sources_status[] = $name . '(' . (is_dir($path) ? 'OK' : 'NOT FOUND') . ')';
    }

    send_json(200, [
        'status'    => 'ok',
        'version'   => VERSION,
        'engine'    => 'PHP/' . PHP_VERSION,
        'timestamp' => date('c'),
        'sources'   => array_keys($source_dirs),
    ]);
}

/**
 * GET /api/files — Scan semua source directory dan kembalikan list metadata file.
 */
function handle_files($source_dirs, $exc_ext, $exc_folders, $log_file)
{
    $all_files = [];
    $start     = microtime(true);

    foreach ($source_dirs as $source_name => $source_path) {
        $source_base = realpath($source_path);

        if ($source_base === false || !is_dir($source_base)) {
            log_message(
                $log_file, 'WARN',
                "Source directory tidak ditemukan: '{$source_path}' (source: {$source_name})"
            );
            continue;
        }

        $count      = 0;
        $total_size = 0;

        try {
            $dir_iter = new RecursiveDirectoryIterator(
                $source_base,
                RecursiveDirectoryIterator::SKIP_DOTS
            );
            $iterator = new RecursiveIteratorIterator(
                $dir_iter,
                RecursiveIteratorIterator::SELF_FIRST
            );

            foreach ($iterator as $file) {
                /** @var SplFileInfo $file */
                if (!$file->isFile()) {
                    continue;
                }

                $abs_path = $file->getRealPath();
                if ($abs_path === false) {
                    continue;
                }

                if (should_exclude($abs_path, $exc_ext, $exc_folders)) {
                    continue;
                }

                // Relative path dengan separator '/' (kompatibel lintas platform)
                $rel = substr($abs_path, strlen($source_base) + 1);
                $rel = str_replace('\\', '/', $rel);

                $size  = $file->getSize();
                $mtime = $file->getMTime();

                $all_files[] = [
                    'source'        => $source_name,
                    'relative_path' => $rel,
                    'size'          => $size,
                    'mtime'         => (float) $mtime,
                ];

                $count++;
                $total_size += $size;
            }
        } catch (Exception $e) {
            log_message($log_file, 'ERROR',
                "Error scanning '{$source_path}': " . $e->getMessage()
            );
        }

        log_message(
            $log_file, 'INFO',
            "Scanned source '{$source_name}': {$count} files, " . format_size($total_size)
        );
    }

    $elapsed = round(microtime(true) - $start, 2);
    log_message(
        $log_file, 'INFO',
        "Request daftar file dari {$_SERVER['REMOTE_ADDR']}: "
        . count($all_files) . " file, scan {$elapsed}s"
    );

    send_json(200, [
        'files'                  => $all_files,
        'total_files'            => count($all_files),
        'scan_duration_seconds'  => $elapsed,
        'timestamp'              => date('c'),
        'version'                => VERSION,
    ]);
}

/**
 * GET /api/file?source=X&path=Y — Stream file ke client.
 */
function handle_file_download($source_name, $relative_path, $source_dirs, $log_file)
{
    if ($source_name === '' || $relative_path === '') {
        send_error(400, "Parameter 'source' dan 'path' diperlukan.");
    }

    // URL decode path yang dikirim client
    $relative_path = urldecode($relative_path);

    $file_path = resolve_file_path($source_name, $relative_path, $source_dirs);
    if ($file_path === null) {
        log_message(
            $log_file, 'WARN',
            "File tidak ditemukan atau akses ditolak: [{$source_name}] {$relative_path}"
            . " <- {$_SERVER['REMOTE_ADDR']}"
        );
        send_error(404, 'File tidak ditemukan atau akses ditolak.');
    }

    $file_size  = filesize($file_path);
    $file_mtime = filemtime($file_path);

    // Hapus output buffer agar tidak ada overhead saat streaming
    while (ob_get_level()) {
        ob_end_clean();
    }

    // Set header response (kompatibel dengan Python client)
    header('Content-Type: application/octet-stream');
    header('Content-Length: ' . $file_size);
    header('X-File-Size: '    . $file_size);
    header('X-File-Mtime: '   . $file_mtime);
    header('Cache-Control: no-cache, no-store, must-revalidate');

    http_response_code(200);

    // Stream file ke client dalam chunk
    $handle    = fopen($file_path, 'rb');
    $bytes_sent = 0;

    if ($handle === false) {
        log_message($log_file, 'ERROR', "Tidak dapat membuka file: {$file_path}");
        http_response_code(500);
        exit;
    }

    while (!feof($handle)) {
        $chunk = fread($handle, CHUNK_SIZE);
        if ($chunk === false) {
            break;
        }
        echo $chunk;
        $bytes_sent += strlen($chunk);
        flush();
    }

    fclose($handle);

    log_message(
        $log_file, 'INFO',
        "Sent: [{$source_name}] {$relative_path} ("
        . format_size($bytes_sent) . ") -> {$_SERVER['REMOTE_ADDR']}"
    );

    exit;
}


// ============================================================
// Bootstrap — Load Config
// ============================================================

// Cari config di direktori yang sama dengan script ini
$config_file = __DIR__ . DIRECTORY_SEPARATOR . 'backup_server_config.ini';

if (!file_exists($config_file)) {
    create_default_config($config_file);
    send_error(503,
        'File konfigurasi default telah dibuat (backup_server_config.ini). '
        . 'Edit AuthToken dan SourceDirectories, kemudian akses kembali.'
    );
}

// INI_SCANNER_RAW agar backslash pada path Windows tidak diinterpretasi
$ini = parse_ini_file($config_file, true, INI_SCANNER_RAW);
if ($ini === false) {
    http_response_code(500);
    echo json_encode(['error' => 'Gagal membaca backup_server_config.ini. Periksa syntax file.']);
    exit;
}

$auth_token  = isset($ini['SERVER']['AuthToken'])          ? trim($ini['SERVER']['AuthToken'])          : '';
$log_file    = isset($ini['SERVER']['LogFile'])             ? trim($ini['SERVER']['LogFile'])             : 'backup_server.log';
$source_dirs = parse_source_dirs(isset($ini['SERVER']['SourceDirectories']) ? $ini['SERVER']['SourceDirectories'] : '');
$exc_ext     = parse_list(isset($ini['FILTERS']['ExcludeExtensions']) ? $ini['FILTERS']['ExcludeExtensions'] : '.tmp;.bak');
$exc_folders = parse_list(isset($ini['FILTERS']['ExcludeFolders'])    ? $ini['FILTERS']['ExcludeFolders']    : 'temp;cache');

// Resolve log_file relatif terhadap direktori script
if ($log_file !== '' && !is_absolute_path($log_file)) {
    $log_file = __DIR__ . DIRECTORY_SEPARATOR . $log_file;
}

function is_absolute_path($path)
{
    // Windows: C:\... atau \\server\...
    if (DIRECTORY_SEPARATOR === '\\') {
        return (strlen($path) >= 3 && $path[1] === ':') || substr($path, 0, 2) === '\\\\';
    }
    return $path[0] === '/';
}

// Peringatan jika token masih default
if ($auth_token === '' || stripos($auth_token, 'ganti_token') !== false) {
    log_message($log_file, 'WARN',
        'AuthToken masih default atau kosong! Ganti segera di backup_server_config.ini'
    );
}


// ============================================================
// Routing
// ============================================================

// Dapatkan path request relatif terhadap subdirektori script ini
$script_dir  = rtrim(dirname($_SERVER['SCRIPT_NAME']), '/');  // e.g. /backup
$request_uri = $_SERVER['REQUEST_URI'];
$req_path    = parse_url($request_uri, PHP_URL_PATH);         // Buang query string

// Hapus prefix subdirektori agar route bersih
if ($script_dir !== '' && strncmp($req_path, $script_dir, strlen($script_dir)) === 0) {
    $req_path = substr($req_path, strlen($script_dir));
}
$req_path = '/' . ltrim($req_path, '/');

// Autentikasi — semua endpoint kecuali /health memerlukan token
if ($req_path !== '/health') {
    if ($auth_token !== '' && !authenticate($auth_token)) {
        log_message($log_file, 'WARN',
            "Autentikasi gagal dari {$_SERVER['REMOTE_ADDR']}, path: {$req_path}"
        );
        send_error(401, 'Autentikasi diperlukan. Sertakan header X-Auth-Token.');
    }
}

// Dispatch ke handler yang sesuai
switch ($req_path) {
    case '/health':
        handle_health($source_dirs);
        break;

    case '/api/files':
        handle_files($source_dirs, $exc_ext, $exc_folders, $log_file);
        break;

    case '/api/file':
        handle_file_download(
            isset($_GET['source']) ? $_GET['source'] : '',
            isset($_GET['path'])   ? $_GET['path']   : '',
            $source_dirs,
            $log_file
        );
        break;

    default:
        send_error(404, "Endpoint '{$req_path}' tidak tersedia.");
}
