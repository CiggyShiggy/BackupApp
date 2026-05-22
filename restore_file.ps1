# Script PowerShell untuk Restore File dari Backup Incremental
# Usage: .\restore_file.ps1 -FileName "Data\dokumen\laporan.xlsx" -RestoreTo "C:\Restore"

param(
    [Parameter(Mandatory=$true)]
    [string]$FileName,
    
    [Parameter(Mandatory=$false)]
    [string]$BackupDir = "D:\Backup",
    
    [Parameter(Mandatory=$false)]
    [string]$RestoreTo = "C:\Restore",
    
    [Parameter(Mandatory=$false)]
    [switch]$ShowHistory,
    
    [Parameter(Mandatory=$false)]
    [string]$RestoreFromDate
)

Write-Host "╔══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  RESTORE FILE FROM INCREMENTAL BACKUP                    ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# Normalize path separator
$FileName = $FileName -replace '/', '\'

Write-Host "📁 Backup Directory : $BackupDir" -ForegroundColor Yellow
Write-Host "📄 File to Restore  : $FileName" -ForegroundColor Yellow
Write-Host "📂 Restore To       : $RestoreTo" -ForegroundColor Yellow
Write-Host ""

# Cek apakah backup directory ada
if (-not (Test-Path $BackupDir)) {
    Write-Host "❌ Error: Backup directory tidak ditemukan: $BackupDir" -ForegroundColor Red
    exit 1
}

# Fungsi untuk format tanggal dari nama folder
function Get-DateFromFolderName {
    param([string]$FolderName)
    
    if ($FolderName -match 'incremental_(\d{8})_(\d{6})') {
        $dateStr = $matches[1]
        $timeStr = $matches[2]
        
        $year = $dateStr.Substring(0, 4)
        $month = $dateStr.Substring(4, 2)
        $day = $dateStr.Substring(6, 2)
        $hour = $timeStr.Substring(0, 2)
        $minute = $timeStr.Substring(2, 2)
        $second = $timeStr.Substring(4, 2)
        
        return [DateTime]::ParseExact("$year-$month-$day $hour:$minute:$second", "yyyy-MM-dd HH:mm:ss", $null)
    }
    return $null
}

# Cari semua versi file
$versions = @()

# Cek di folder incremental
$incrementalFolders = Get-ChildItem "$BackupDir\incremental_*" -Directory -ErrorAction SilentlyContinue | 
    Sort-Object Name -Descending

foreach ($folder in $incrementalFolders) {
    $filePath = Join-Path $folder.FullName $FileName
    if (Test-Path $filePath) {
        $fileInfo = Get-Item $filePath
        $folderDate = Get-DateFromFolderName $folder.Name
        
        $versions += [PSCustomObject]@{
            Path = $filePath
            FolderName = $folder.Name
            BackupDate = $folderDate
            FileSize = $fileInfo.Length
            ModifiedDate = $fileInfo.LastWriteTime
        }
    }
}

# Cek di folder utama (initial backup)
$mainFilePath = Join-Path $BackupDir $FileName
if (Test-Path $mainFilePath) {
    $fileInfo = Get-Item $mainFilePath
    
    $versions += [PSCustomObject]@{
        Path = $mainFilePath
        FolderName = "Main (Initial Backup)"
        BackupDate = $fileInfo.CreationTime
        FileSize = $fileInfo.Length
        ModifiedDate = $fileInfo.LastWriteTime
    }
}

# Tampilkan hasil
if ($versions.Count -eq 0) {
    Write-Host "❌ File tidak ditemukan di backup: $FileName" -ForegroundColor Red
    exit 1
}

Write-Host "✅ Ditemukan $($versions.Count) versi file:" -ForegroundColor Green
Write-Host ""
Write-Host "┌────┬─────────────────────────────────────┬─────────────────────┬────────────┐" -ForegroundColor Gray
Write-Host "│ No │ Backup Folder                       │ Backup Date         │ Size       │" -ForegroundColor Gray
Write-Host "├────┼─────────────────────────────────────┼─────────────────────┼────────────┤" -ForegroundColor Gray

$index = 1
foreach ($version in $versions) {
    $sizeStr = "{0:N2} MB" -f ($version.FileSize / 1MB)
    $dateStr = if ($version.BackupDate) { $version.BackupDate.ToString("yyyy-MM-dd HH:mm:ss") } else { "N/A" }
    $folderDisplay = $version.FolderName.PadRight(35).Substring(0, 35)
    
    Write-Host ("│ {0,2} │ {1} │ {2} │ {3,10} │" -f $index, $folderDisplay, $dateStr, $sizeStr) -ForegroundColor White
    $index++
}

Write-Host "└────┴─────────────────────────────────────┴─────────────────────┴────────────┘" -ForegroundColor Gray
Write-Host ""

# Jika hanya show history, keluar
if ($ShowHistory) {
    Write-Host "ℹ️  Gunakan tanpa parameter -ShowHistory untuk restore file" -ForegroundColor Cyan
    exit 0
}

# Tentukan file mana yang akan di-restore
$selectedVersion = $null

if ($RestoreFromDate) {
    # Restore dari tanggal tertentu
    $targetDate = [DateTime]::ParseExact($RestoreFromDate, "yyyyMMdd", $null)
    $selectedVersion = $versions | Where-Object { 
        $_.BackupDate -and $_.BackupDate.Date -eq $targetDate.Date 
    } | Select-Object -First 1
    
    if (-not $selectedVersion) {
        Write-Host "❌ Tidak ada backup dari tanggal: $RestoreFromDate" -ForegroundColor Red
        exit 1
    }
} else {
    # Restore versi terbaru (default)
    $selectedVersion = $versions[0]
}

Write-Host "📦 Restore dari: $($selectedVersion.FolderName)" -ForegroundColor Cyan
Write-Host "📅 Backup date : $($selectedVersion.BackupDate)" -ForegroundColor Cyan
Write-Host ""

# Buat direktori restore jika belum ada
if (-not (Test-Path $RestoreTo)) {
    New-Item -ItemType Directory -Path $RestoreTo -Force | Out-Null
    Write-Host "✅ Direktori restore dibuat: $RestoreTo" -ForegroundColor Green
}

# Tentukan nama file tujuan
$destFileName = Split-Path $FileName -Leaf
$destFilePath = Join-Path $RestoreTo $destFileName

# Copy file
try {
    Copy-Item -Path $selectedVersion.Path -Destination $destFilePath -Force
    
    $copiedFile = Get-Item $destFilePath
    $sizeStr = "{0:N2} MB" -f ($copiedFile.Length / 1MB)
    
    Write-Host "✅ File berhasil di-restore!" -ForegroundColor Green
    Write-Host "   Source: $($selectedVersion.Path)" -ForegroundColor Gray
    Write-Host "   Dest  : $destFilePath" -ForegroundColor Gray
    Write-Host "   Size  : $sizeStr" -ForegroundColor Gray
    Write-Host ""
    Write-Host "🎉 Restore selesai!" -ForegroundColor Green
    
} catch {
    Write-Host "❌ Error saat restore file: $_" -ForegroundColor Red
    exit 1
}
