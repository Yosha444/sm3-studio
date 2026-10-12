# SPDX-License-Identifier: GPL-3.0-or-later
# boucle_test.ps1 - the "Install and launch game" button of SM3 Studio (run as administrator).
# Installs the built mod (mods\<name>, made the only enabled mod in mods.config.ini), then starts
# the game. ("boucle" is French for "loop": this started as a test loop. Parameter names stay
# French because SM3 Studio passes them: Jeu = game folder, Attente = wait in seconds, Captures =
# number of screenshots, Simuler = simulate.)
#
# 2026-10-06: the game folder is no longer hard-coded (C:\Program Files (x86)\Activision\... does
# not exist on every machine: the button could neither install nor launch). It is looked for, in
# this order: -Jeu, SM3 Studio's "Game folder" (sm3_studio.json, key "jeu"), the install registry
# key (HKLM\...\Activision\Spider-Man 3\InstallPath), then the usual locations. A folder is only
# accepted if it contains Game.exe.
# The game is closed BEFORE copying (so the mod's files are not locked), and the automatic NVIDIA
# screenshots (Alt+F1, a test tool) are off by default: -Captures 3 turns them back on.
# -Simuler: show what would be done, without writing or starting anything.
# WARNING: the .exe passes "-Mod <name>" through Start-Process -ArgumentList, which does NOT add
# quotes: a name with a space ("sm3 remake") arrives in two pieces. So no parameter is positional,
# and the extra pieces are glued back onto the mod name.
[CmdletBinding(PositionalBinding = $false)]
param(
  [string]$Mod = 'Sukuna',
  [string]$Jeu = '',
  [int]$Attente = 60,
  [int]$Captures = 0,
  [switch]$Simuler,
  [string]$Log = '',
  [Parameter(ValueFromRemainingArguments = $true)][string[]]$Reste
)
if ($Reste) { $Mod = ((@($Mod) + $Reste) -join ' ').Trim() }
# WARNING: no $PSScriptRoot in a parameter default value: with [CmdletBinding()] it is empty there
# under Windows PowerShell 5.1 (the log went to C:\boucle.log, and writing it was refused).
if (-not $Log) { $Log = Join-Path $PSScriptRoot '..\boucle.log' }
$out = New-Object System.Collections.Generic.List[string]
function Say($m) { $out.Add($m); Write-Host $m }

# Trouver-Jeu = "find the game": returns @(folder, where it was found) or $null.
function Trouver-Jeu([string]$explicite) {
  $candidats = New-Object System.Collections.Generic.List[object]
  if (-not [string]::IsNullOrWhiteSpace($explicite)) { $candidats.Add(@($explicite, '-Jeu parameter')) }
  $json = Join-Path $PSScriptRoot '..\sm3_studio.json'
  if (Test-Path $json) {
    try {
      $j = Get-Content $json -Raw -Encoding UTF8 | ConvertFrom-Json
      if ($j.jeu) { $candidats.Add(@([string]$j.jeu, 'Game folder setting of SM3 Studio')) }
    } catch { }
  }
  foreach ($cle in 'HKLM:\SOFTWARE\WOW6432Node\Activision\Spider-Man 3', 'HKLM:\SOFTWARE\Activision\Spider-Man 3') {
    try {
      $p = (Get-ItemProperty -Path $cle -ErrorAction Stop).InstallPath
      if ($p) { $candidats.Add(@([string]$p, 'registry (InstallPath)')) }
    } catch { }
  }
  foreach ($p in 'C:\Games\Spider-man 3', 'C:\Program Files (x86)\Activision\Spider-Man 3',
                 'C:\Program Files\Activision\Spider-Man 3') {
    $candidats.Add(@($p, 'usual location'))
  }
  foreach ($c in $candidats) {
    $d = ([string]$c[0]).Trim().TrimEnd('\')
    $ok = $false
    # [IO.Path]::Combine and not Join-Path: Join-Path fails on a drive that does not exist
    try { $ok = $d -and (Test-Path -LiteralPath ([System.IO.Path]::Combine($d, 'Game.exe'))) } catch { $ok = $false }
    if ($ok) {
      return @($d, [string]$c[1])
    }
    if ($d) { Say ("  (skipped: '" + $d + "' does not contain Game.exe - " + $c[1] + ")") }
  }
  return $null
}

try {
  $trouve = Trouver-Jeu $Jeu
  if (-not $trouve) {
    throw "Game folder not found (no candidate contains Game.exe). Set it in the Paths tab of SM3 Studio."
  }
  $dossier = $trouve[0]
  $exe = Join-Path $dossier 'Game.exe'
  Say ("== game folder: " + $dossier + " (" + $trouve[1] + ") ==")
  $src = Join-Path $PSScriptRoot ("..\mods\" + $Mod)
  if (-not (Test-Path -LiteralPath $src)) {
    throw ("Mod '" + $Mod + "' not found in " + (Join-Path $PSScriptRoot '..\mods') + ": convert it first.")
  }
  # WARNING: disable ALL the other mods, not a fixed list: two enabled mods fight over the same
  # resources, and you no longer know which one you are looking at.
  $modsDir = Join-Path $dossier 'Mods'
  $autres = @()
  if (Test-Path -LiteralPath $modsDir) {
    $autres = @(Get-ChildItem -LiteralPath $modsDir -Directory | Select-Object -ExpandProperty Name |
                Where-Object { $_ -ne $Mod })
  }
  Say ("installing " + $Mod + " (disabled: " + ($autres -join ', ') + ")")
  if ($Simuler) {
    Say ("SIMULATION: would copy " + $src + " -> " + (Join-Path $modsDir $Mod) + ", enable " + $Mod + "=100, start " + $exe)
  } else {
    $jeuOuvert = Get-Process -Name 'Game' -ErrorAction SilentlyContinue |
                 Where-Object { -not $_.Path -or $_.Path -ieq $exe }
    if ($jeuOuvert) {
      Say "the game is running: closing it before copying"
      $jeuOuvert | Stop-Process -Force -ErrorAction SilentlyContinue
      for ($i = 0; $i -lt 20 -and (Get-Process -Id $jeuOuvert.Id -ErrorAction SilentlyContinue); $i++) { Start-Sleep -Milliseconds 500 }
    }
    # Paths relative to the script: the tool's folder moves (copied next to a model, stand-alone
    # folder), and hard-coded paths installed the wrong mod.
    & "$PSScriptRoot\install_admin.ps1" -Game $dossier -ModSrc $src -ModName $Mod -Disable $autres | Out-Null
    $journal = Join-Path $PSScriptRoot '..\install.log'
    if (-not (Test-Path -LiteralPath (Join-Path $modsDir $Mod))) {
      $err = ''
      if (Test-Path $journal) { $err = (Get-Content $journal | Where-Object { $_ -like 'ERROR*' } | Select-Object -First 1) }
      throw ("installation failed: " + $err)
    }
    if (Test-Path $journal) { Get-Content $journal | ForEach-Object { Say ("   " + $_) } }
    Say "mod installed"
    $dir = Join-Path $env:USERPROFILE 'Videos\NVIDIA\Spider-Man 3'
    $avant = @(Get-ChildItem $dir -Filter *.png -ErrorAction SilentlyContinue).Count
    Start-Process -FilePath $exe -WorkingDirectory $dossier
    $p = $null
    for ($i = 0; $i -lt [Math]::Max(1, [int]($Attente / 2)); $i++) {
      Start-Sleep -Seconds 2
      $p = Get-Process -Name 'Game' -ErrorAction SilentlyContinue | Select-Object -First 1
      if ($p) { break }
    }
    if (-not $p) { throw "the game did not start" }
    Say ("game started (PID " + $p.Id + ")")
    if ($Captures -gt 0) {
      # Test tool: the NVIDIA overlay is the only way found to capture SM3's exclusive full
      # screen (GDI, Print Screen and PrintWindow give a black image).
      Start-Sleep -Seconds 30
      Add-Type @"
using System;using System.Runtime.InteropServices;
public class KB { [DllImport("user32.dll")] public static extern void keybd_event(byte b,byte s,uint f,IntPtr e);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h); }
"@
      $p.Refresh()
      [KB]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
      Start-Sleep -Seconds 2
      for ($i = 1; $i -le $Captures; $i++) {
        [KB]::keybd_event(0x12,0,0,[IntPtr]::Zero)          # Alt down
        [KB]::keybd_event(0x70,0,0,[IntPtr]::Zero)          # F1
        Start-Sleep -Milliseconds 150
        [KB]::keybd_event(0x70,0,2,[IntPtr]::Zero)
        [KB]::keybd_event(0x12,0,2,[IntPtr]::Zero)
        Start-Sleep -Seconds 3
      }
      $apres = @(Get-ChildItem $dir -Filter *.png -ErrorAction SilentlyContinue)
      Say ("screenshots: " + ($apres.Count - $avant) + " new in " + $dir)
    }
  }
} catch { Say ("ERROR: " + $_.Exception.Message) }
Set-Content -Path $Log -Value $out -Encoding UTF8
