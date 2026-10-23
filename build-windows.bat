@echo off
setlocal EnableExtensions
rem ===========================================================================
rem Data Monitor - build, install and uninstall for Windows.
rem
rem Usage (from cmd.exe, or from an MSYS2 MINGW64 shell via "cmd //c ..."):
rem   build-windows.bat              build dist\DataMonitor\DataMonitor.exe
rem                                  (+ DataMonitor-Setup-<version>.exe when
rem                                  Inno Setup 6 is installed)
rem   build-windows.bat install      copy to "%LOCALAPPDATA%\Data Monitor" and
rem                                  start hidden at login (HKCU Run key)
rem   build-windows.bat uninstall    remove both again (keeps your data)
rem
rem Requirements - MSYS2 with the mingw-w64 toolchain (https://www.msys2.org),
rem run once in the "MSYS2 MINGW64" shell:
rem   pacman -S --needed mingw-w64-x86_64-python mingw-w64-x86_64-python-gobject ^
rem                      mingw-w64-x86_64-python-cairo mingw-w64-x86_64-gtk4 ^
rem                      mingw-w64-x86_64-libadwaita mingw-w64-x86_64-python-psutil ^
rem                      mingw-w64-x86_64-pyinstaller mingw-w64-x86_64-dbus
rem ===========================================================================

set "ROOT=%~dp0"
set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=build"
set "APPDIR=%LOCALAPPDATA%\Data Monitor"

if /i "%ACTION%"=="install"   goto install
if /i "%ACTION%"=="uninstall" goto uninstall
if /i "%ACTION%"=="build"     goto build
echo build-windows.bat: unknown action "%ACTION%" (use build, install or uninstall) >&2
exit /b 2

:build
call :find_python
if errorlevel 1 exit /b 1

echo.
echo Building with "%PY%" ...
"%PY%" -m PyInstaller --noconfirm --clean "%ROOT%packaging\datamonitor.spec"
if errorlevel 1 (
    echo error: PyInstaller failed.
    exit /b 1
)

rem GLib needs a compiled schema cache inside the bundle.
where glib-compile-schemas >nul 2>nul
if not errorlevel 1 (
    glib-compile-schemas "%ROOT%dist\DataMonitor\_internal\share\glib-2.0\schemas" >nul 2>nul
)

rem Version for the installer name (from datamonitor\__init__.py).
set "VERSION="
for /f "delims=" %%V in ('"%PY%" -c "import os; os.chdir(r"%ROOT:~0,-1%"); import datamonitor; print(datamonitor.__version__)"') do set "VERSION=%%V"
if not defined VERSION set "VERSION=dev"

set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
echo.
if exist "%ISCC%" (
    echo Inno Setup found - building the installer...
    "%ISCC%" /DMyAppVersion=%VERSION% "%ROOT%packaging\datamonitor.iss"
    if errorlevel 1 (
        echo warning: installer build failed; the portable folder still works.
    )
) else (
    echo Inno Setup 6 not found - skipping the installer.
    echo The portable app is in dist\DataMonitor ^(run DataMonitor.exe there^).
    echo Install Inno Setup 6 from https://jrsoftware.org/isinfo.php for one.
)

echo.
echo Done. Version %VERSION%.
echo   Portable app : %ROOT%dist\DataMonitor\DataMonitor.exe
echo   Install it   : build-windows.bat install
exit /b 0

:install
if not exist "%ROOT%dist\DataMonitor\DataMonitor.exe" (
    echo error: no build found - run build-windows.bat first.
    exit /b 1
)
taskkill /f /im DataMonitor.exe >nul 2>nul
echo Installing to "%APPDIR%" ...
xcopy /e /i /q /y "%ROOT%dist\DataMonitor" "%APPDIR%" >nul
if errorlevel 1 (
    echo error: copy failed.
    exit /b 1
)
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v DataMonitor /t REG_SZ /d "\"%APPDIR%\DataMonitor.exe\" --hidden" /f >nul
echo   app       -^> %APPDIR%
echo   autostart -^> HKCU Run "DataMonitor" ^(starts hidden at login^)
echo.
echo Start it now with:  "%APPDIR%\DataMonitor.exe"
echo Open a tab with:    "%APPDIR%\DataMonitor.exe" --page history
exit /b 0

:uninstall
taskkill /f /im DataMonitor.exe >nul 2>nul
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v DataMonitor /f >nul 2>nul
if exist "%APPDIR%" rmdir /s /q "%APPDIR%"
echo Removed the autostart entry and "%APPDIR%".
echo.
echo Your data stays in "%LOCALAPPDATA%\datamonitor" and "%APPDATA%\datamonitor".
echo Delete those folders by hand for a full reset.
exit /b 0

rem ===========================================================================
:find_python
set "PY="
if exist "C:\msys64\mingw64\python.exe" set "PY=C:\msys64\mingw64\python.exe"
if exist "D:\msys64\mingw64\python.exe" set "PY=D:\msys64\mingw64\python.exe"
if defined PY goto check_deps
where python >nul 2>nul
if errorlevel 1 goto no_python
for /f "delims=" %%P in ('where python') do (
    if not defined PY set "PY=%%P"
)

:check_deps
"%PY%" -c "import gi" >nul 2>nul
if errorlevel 1 goto no_gtk
"%PY%" -c "import cairo" >nul 2>nul
if errorlevel 1 goto no_gtk
"%PY%" -c "import psutil" >nul 2>nul
if errorlevel 1 (
    echo psutil not found - installing it with pip...
    "%PY%" -m pip install psutil
    if errorlevel 1 goto no_gtk
)
"%PY%" -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo PyInstaller not found - installing it with pip...
    "%PY%" -m pip install pyinstaller
    if errorlevel 1 (
        echo error: pip could not install pyinstaller.
        echo Try instead, in the MSYS2 MINGW64 shell:
        echo   pacman -S mingw-w64-x86_64-pyinstaller
        exit /b 1
    )
)
exit /b 0

:no_python
echo error: no python.exe found.
echo.
echo Data Monitor is built with the MSYS2 mingw-w64 toolchain:
echo   1. install MSYS2 from https://www.msys2.org
echo   2. in the "MSYS2 MINGW64" shell run:
echo      pacman -S --needed mingw-w64-x86_64-python mingw-w64-x86_64-python-gobject mingw-w64-x86_64-python-cairo mingw-w64-x86_64-gtk4 mingw-w64-x86_64-libadwaita mingw-w64-x86_64-python-psutil mingw-w64-x86_64-pyinstaller mingw-w64-x86_64-dbus
echo   3. re-run this script.
exit /b 1

:no_gtk
echo error: the GTK 4 / libadwaita Python bindings are missing for:
echo   "%PY%"
echo.
echo Install them in the MSYS2 MINGW64 shell:
echo   pacman -S --needed mingw-w64-x86_64-python-gobject mingw-w64-x86_64-python-cairo mingw-w64-x86_64-gtk4 mingw-w64-x86_64-libadwaita
exit /b 1
