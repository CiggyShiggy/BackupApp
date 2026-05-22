# Script PowerShell untuk Cleanup Folder Incremental Backup Lama
# Usage: .\cleanup_old_backups.ps1 -DaysToKeep 30 -BackupDir "D:\Backup"

param(
    [Parameter(Mandatory=$false)]
    [int]$DaysToKeep = 30,
    
    [Parameter(Mandatory=$false)]
    [string]$BackupDir = "D:\Backup",
    
    [Parameter(Mandatory=$false)]
    [switch]$DryRun,
    
    [Parameter(Mandatory=$false)]
    [switch]$Force
)

Write-Host "╔══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  CLEANUP OLD INCREMENTAL BACKUPS                         ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

Write-Host "📁 Backup Directory : $BackupDir" -ForegroundColor Yellow
Write-Host "📅 Keep Last        : $DaysToKeep days" -ForegroundColor Yellow
Write-Host "🔍 Mode             : $(if ($DryRun) { 'DRY RUN (no deletion)' } else { 'LIVE (will delete)' })" -ForegroundColor Yellow
Write-Host ""

# Cek apakah backup directory ada
if (-not (Test-Path $BackupDir)) {
    Write-Host "❌ Error: Backup directory tidak ditemukan: $BackupDir" -ForegroundColor Red
    exit 1
}

# Hitung cutoff date
$cutoffDate = (Get-Date).AddDays(-$DaysToKeep)
Write-Host "🗓️  Cutoff Date: $($cutoffDate.ToString('yyyy-MM-dd HH:mm:ss'))" -ForegroundColor Cyan
Write-Host "   (Folder sebelum tanggal ini akan dihapus)" -ForegroundColor Gray
Write-Host ""

# Cari folder incremental
$incrementalFolders = Get-ChildItem "$BackupDir\incremental_*" -Directory -ErrorAction SilentlyContinue

if ($incrementalFolders.Count -eq 0) {
    Write-Host "ℹ️  Tidak ada folder incremental ditemukan" -ForegroundColor Cyan
    exit 0
}

Write-Host "📊 Total folder incremental: $($incrementalFolders.Count)" -ForegroundColor Cyan
Write-Host ""

# Filter folder yang akan dihapus
$foldersToDelete = $incrementalFolders | Where-Object { $_.CreationTime -lt $cutoffDate }

if ($foldersToDelete.Count -eq 0) {
    Write-Host "✅ Tidak ada folder yang perlu dihapus" -ForegroundColor Green
    Write-Host "   Semua folder masih dalam periode $DaysToKeep hari" -ForegroundColor Gray
    exit 0
}

# Hitung total size
$totalSize = 0
foreach ($folder in $foldersToDelete) {
    $folderSize = (Get-ChildItem $folder.FullName -Recurse -File -ErrorAction SilentlyContinue | 
        Measure-Object -Property Length -Sum).Sum
    $totalSize += $folderSize
}

$totalSizeGB = $totalSize / 1GB

Write-Host "🗑️  Folder yang akan dihapus: $($foldersToDelete.Count)" -ForegroundColor Yellow
Write-Host "💾 Total size: $("{0:N2}" -f $totalSizeGB) GB" -ForegroundColor Yellow
Write-Host ""

# Tampilkan daftar folder
Write-Host "┌────┬─────────────────────────────────────┬─────────────────────┬────────────┐" -ForegroundColor Gray
Write-Host "│ No │ Folder Name                         │ Creation Date       │ Size       │" -ForegroundColor Gray
Write-Host "├────┼─────────────────────────────────────┼─────────────────────┼────────────┤" -ForegroundColor Gray

$index = 1
foreach ($folder in $foldersToDelete | Sort-Object CreationTime) {
    $folderSize = (Get-ChildItem $folder.FullName -Recurse -File -ErrorAction SilentlyContinue | 
        Measure-Object -Property Length -Sum).Sum
    $sizeStr = "{0:N2} MB" -f ($folderSize / 1MB)
    $dateStr = $folder.CreationTime.ToString("yyyy-MM-dd HH:mm:ss")
    $folderDisplay = $folder.Name.PadRight(35).Substring(0, 35)
    
    Write-Host ("│ {0,2} │ {1} │ {2} │ {3,10} │" -f $index, $folderDisplay, $dateStr, $sizeStr) -ForegroundColor White
    $index++
}

Write-Host "└────┴─────────────────────────────────────┴─────────────────────┴────────────┘" -ForegroundColor Gray
Write-Host ""

# Jika dry run, keluar
if ($DryRun) {
    Write-Host "ℹ️  DRY RUN mode - tidak ada folder yang dihapus" -ForegroundColor Cyan
    Write-Host "   Jalankan tanpa parameter -DryRun untuk menghapus folder" -ForegroundColor Gray
    exit 0
}

# Konfirmasi jika tidak force
if (-not $Force) {
    Write-Host "⚠️  WARNING: Operasi ini akan menghapus $($foldersToDelete.Count) folder ($("{0:N2}" -f $totalSizeGB) GB)" -ForegroundColor Red
    Write-Host ""
    $confirmation = Read-Host "Lanjutkan? (ketik 'YES' untuk konfirmasi)"
    
    if ($confirmation -ne "YES") {
        Write-Host "❌ Operasi dibatalkan" -ForegroundColor Yellow
        exit 0
    }
}

Write-Host ""
Write-Host "🗑️  Menghapus folder..." -ForegroundColor Yellow
Write-Host ""

# Hapus folder
$deletedCount = 0
$deletedSize = 0
$failedCount = 0

foreach ($folder in $foldersToDelete) {
    try {
        $folderSize = (Get-ChildItem $folder.FullName -Recurse -File -ErrorAction SilentlyContinue | 
            Measure-Object -Property Length -Sum).Sum
        
        Write-Host "  🗑️  Menghapus: $($folder.Name)..." -NoNewline
        Remove-Item -Path $folder.FullName -Recurse -Force -ErrorAction Stop
        
        $deletedCount++
        $deletedSize += $folderSize
        
        Write-Host " ✅" -ForegroundColor Green
        
    } catch {
        Write-Host " ❌" -ForegroundColor Red
        Write-Host "     Error: $_" -ForegroundColor Red
        $failedCount++
    }
}

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║  CLEANUP SELESAI                                         ║" -ForegroundColor Green
Write-Host "╠══════════════════════════════════════════════════════════╣" -ForegroundColor Green
Write-Host ("║  Berhasil dihapus : {0,2} folder                          ║" -f $deletedCount) -ForegroundColor Green
Write-Host ("║  Gagal            : {0,2} folder                          ║" -f $failedCount) -ForegroundColor Green
Write-Host ("║  Space freed      : {0,10:N2} GB                      ║" -f ($deletedSize / 1GB)) -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""

if ($failedCount -gt 0) {
    Write-Host "⚠️  Beberapa folder gagal dihapus. Cek permission atau file yang sedang digunakan." -ForegroundColor Yellow
}

# Tampilkan folder yang tersisa
$remainingFolders = Get-ChildItem "$BackupDir\incremental_*" -Directory -ErrorAction SilentlyContinue
Write-Host "📊 Folder incremental tersisa: $($remainingFolders.Count)" -ForegroundColor Cyan

if ($remainingFolders.Count -gt 0) {
    $oldestFolder = $remainingFolders | Sort-Object CreationTime | Select-Object -First 1
    $newestFolder = $remainingFolders | Sort-Object CreationTime -Descending | Select-Object -First 1
    
    Write-Host "   Oldest: $($oldestFolder.Name) ($($oldestFolder.CreationTime.ToString('yyyy-MM-dd')))" -ForegroundColor Gray
    Write-Host "   Newest: $($newestFolder.Name) ($($newestFolder.CreationTime.ToString('yyyy-MM-dd')))" -ForegroundColor Gray
}

Write-Host ""
Write-Host "✅ Cleanup selesai!" -ForegroundColor Green
