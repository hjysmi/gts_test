@echo off
cd /d D:\adb
adb disconnect

@echo off
title ADB Automation
color 07

echo Waiting for device...
adb wait-for-device

echo.
echo [1/5] adb root
adb root
if %ERRORLEVEL%==0 (
    call :PASS "[PASS] adb root success"
) else (
    call :FAIL "[FAIL] adb root failed"
)

timeout /t 3 /nobreak >nul

echo.
echo [2/5] adb remount
adb remount
if %ERRORLEVEL%==0 (
    call :PASS "[PASS] adb remount success"
) else (
    call :FAIL "[FAIL] adb remount failed"
)

echo.
echo [3/5] Disable captive portal
adb shell settings put global captive_portal_mode 0
if %ERRORLEVEL%==0 (
    call :PASS "[PASS] captive_portal_mode set to 0"
) else (
    call :FAIL "[FAIL] captive_portal_mode set failed"
)

echo.
echo [4/5] Push wifi.cfg
adb push "E:\Test data\Wallace\Artura\New folder-CH0&CH1-20260128\CH01\wifi.cfg" /vendor/firmware/
if %ERRORLEVEL%==0 (
    call :PASS "[PASS] wifi.cfg pushed successfully"
) else (
    call :FAIL "[FAIL] wifi.cfg push failed"
)

echo.
echo [5/5] Reboot device
adb reboot
if %ERRORLEVEL%==0 (
    call :PASS "[PASS] reboot command sent"
) else (
    call :FAIL "[FAIL] reboot command failed"
)

echo.
echo ====================================
echo ALL COMMANDS FINISHED
echo ====================================
pause
exit /b

:PASS
powershell -Command "Write-Host '%~1' -ForegroundColor Green"
exit /b

:FAIL
powershell -Command "Write-Host '%~1' -ForegroundColor Red"
exit /b