@echo off
rem SPDX-License-Identifier: GPL-3.0-or-later
rem Build the experimental Venom draw adapter (see README.md).
rem Run it from an "x86 Native Tools Command Prompt for VS" (Visual Studio Build Tools, C++),
rem after make_shaders_h.py and make_atlas.py have written shaders.h and atlas_signature.h here.
cd /d "%~dp0"
if not exist shaders.h (echo shaders.h missing: run  python make_shaders_h.py "path\to\Game.exe"  first & exit /b 1)
if not exist atlas_signature.h (echo atlas_signature.h missing: run  python make_atlas.py "SM3 Studio\build\<mod>"  first & exit /b 1)
rem 1. validate_direct.exe: creates a Direct3D 9 device, checks that the 4 modified shaders are
rem    accepted and recognised, that the atlas loads, and that a draw swaps then restores the state.
rem    It links the REAL winmm.lib of the Windows SDK (a local winmm.lib would be the proxy).
cl /nologo /std:c++17 /EHsc /O2 /DVALIDATE_ONLY direct_runtime.cpp /Fe:validate_direct.exe /link d3d9.lib user32.lib "%WindowsSdkDir%Lib\%WindowsSDKLibVersion%um\x86\winmm.lib"
if errorlevel 1 exit /b 1
rem 2. winmm.dll: the proxy itself.
cl /nologo /std:c++17 /EHsc /O2 /LD direct_runtime.cpp /Fe:winmm.dll /link user32.lib
exit /b %errorlevel%
