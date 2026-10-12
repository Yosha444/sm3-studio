@echo off
rem SPDX-License-Identifier: GPL-3.0-or-later
rem Remove the experimental Venom draw adapter from the default game folder (add --game "folder" otherwise).
python "%~dp0install.py" --remove %*
pause
