# SPDX-License-Identifier: GPL-3.0-or-later
# install_admin.ps1 - puts a mod into the game folder (needs elevation). Called by boucle_test.ps1
# (the "Install and launch game" button). Writes its report to install.log next to tools\.
# Everything is reversible: winmm.dll is renamed (not deleted), mods.config.ini is backed up
# (mods.config.ini.bak, the state before the LAST install only).
param(
    [string]$Game = 'C:\Program Files (x86)\Activision\Spider-Man 3',
    [string]$ModSrc = "$PSScriptRoot\..\mods\Sukuna",
    [string]$ModName = 'Sukuna',
    [string[]]$Disable = @('BlackSuit'),
    [string]$Log = "$PSScriptRoot\..\install.log"
)

$out = New-Object System.Collections.Generic.List[string]
function Say($m) { $out.Add($m); Write-Host $m }

try {
    Say "== installing $ModName into $Game =="

    # SAFETY NET: a badly passed parameter (the -Disable array split into separate tokens) shifts a
    # value onto $Game positionally, and the script then writes into the current folder of the
    # elevated process, that is System32. Any folder without Game.exe is refused.
    if (-not (Test-Path (Join-Path $Game 'Game.exe'))) {
        throw "Invalid game folder: '$Game' does not contain Game.exe. Nothing was written."
    }
    if (-not (Test-Path $ModSrc)) {
        throw "Mod source not found: '$ModSrc'. Nothing was written."
    }

    # 1. disable OUR old winmm.dll proxy, an early experiment of this project (its winmm_real.dll
    #    is gone and it no longer does anything). It is recognised by its SHA-256 only: any other
    #    winmm.dll, such as another mod's proxy, is left untouched. Nothing is ever deleted.
    $ourOldProxy = '46AD82AFACB4113DCEEA90E0AD4E8755F65C05E8D8C94995BF83BA63DC7097F7'
    $winmm = Join-Path $Game 'winmm.dll'
    if (Test-Path $winmm) {
        if ((Get-FileHash -Algorithm SHA256 -Path $winmm).Hash -eq $ourOldProxy) {
            $newName = 'winmm.dll.off'
            if (Test-Path (Join-Path $Game $newName)) {
                $newName = 'winmm.dll.off.' + (Get-Date -Format 'yyyyMMddHHmmss')
            }
            Rename-Item -Path $winmm -NewName $newName
            Say "winmm.dll -> $newName (our old proxy disabled)"
        } else {
            Say "winmm.dll is not ours: left untouched"
        }
    } else {
        Say "no winmm.dll: nothing to disable"
    }

    # 2. old sm3\mods folder of our former loader: renamed, it is no longer read. Only a folder with
    #    that exact layout (sm3\mods) is touched.
    $oldmods = Join-Path $Game 'sm3'
    if (Test-Path (Join-Path $oldmods 'mods')) {
        $dest = Join-Path $Game 'sm3.off'
        if (-not (Test-Path $dest)) {
            Rename-Item -Path $oldmods -NewName 'sm3.off' -Force
            Say "sm3\ -> sm3.off (mods of the old loader)"
        }
    }

    # 3. copy the mod
    $modsDir = Join-Path $Game 'Mods'
    $target = Join-Path $modsDir $ModName
    if (Test-Path $target) { Remove-Item $target -Recurse -Force }
    Copy-Item -Path $ModSrc -Destination $modsDir -Recurse -Force
    $n = (Get-ChildItem $target -Recurse -File | Measure-Object).Count
    Say "copied: $n file(s) -> $target"
    Get-ChildItem $target -Recurse -File | ForEach-Object {
        Say ("   " + $_.FullName.Substring($modsDir.Length + 1) + "  (" + $_.Length + " bytes)")
    }

    # 4. mods.config.ini: <this mod>=100, every other mod =0, everything else unchanged
    $ini = Join-Path $modsDir 'mods.config.ini'
    Copy-Item $ini ($ini + '.bak') -Force
    $lines = Get-Content $ini
    $res = New-Object System.Collections.Generic.List[string]
    $inSection = $false; $seen = $false
    foreach ($l in $lines) {
        $t = $l.Trim()
        if ($t -match '^\[.*\]$') {
            if ($inSection -and -not $seen) { $res.Add("$ModName=100"); $seen = $true }
            $inSection = ($t -ieq '[EnabledMods]')
            $res.Add($l); continue
        }
        if ($inSection -and $t -match '^\s*([^=;#]+?)\s*=') {
            $k = $Matches[1].Trim()
            if ($k -ieq $ModName) { $res.Add("$ModName=100"); $seen = $true; continue }
            # SAFETY NET: EVERYTHING that is not the requested mod is set to 0, whatever list was
            # passed as a parameter. Two mods at 100 fight over the same resources and you no
            # longer know which one you are looking at: it happened, and it invalidated a test in game.
            $res.Add("$k=0"); continue
        }
        $res.Add($l)
    }
    if ($inSection -and -not $seen) { $res.Add("$ModName=100"); $seen = $true }
    if (-not $seen) { $res.Add('[EnabledMods]'); $res.Add("$ModName=100") }
    Set-Content -Path $ini -Value $res -Encoding UTF8
    Say "--- mods.config.ini ---"
    Get-Content $ini | ForEach-Object { Say ("   " + $_) }

    Say "== done =="
} catch {
    # boucle_test.ps1 looks for the first line starting with ERROR in install.log.
    Say ("ERROR: " + $_.Exception.Message)
    Say ($_.ScriptStackTrace)
}

Set-Content -Path $Log -Value $out -Encoding UTF8
