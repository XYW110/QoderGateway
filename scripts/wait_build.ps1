for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 20
    if (-not (Get-Process -Id 31636 -ErrorAction SilentlyContinue)) {
        "BUILD PROCESS EXITED"
        break
    }
    "building ($($i * 20)s)..."
}
Get-Content logs\pyinstaller_build.log -Tail 15
