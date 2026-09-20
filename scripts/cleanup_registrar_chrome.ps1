$procs = Get-CimInstance Win32_Process -Filter "name='chrome.exe'" | Where-Object { $_.CommandLine -like '*qoder_reg_*' }
if ($procs) {
    "found $($procs.Count) leftover registrar chrome processes:"
    $procs | ForEach-Object { "  PID $($_.ProcessId)" }
    $procs | ForEach-Object { taskkill /PID $_.ProcessId /F 2>$null | Out-Null }
    "killed all"
} else {
    "no leftover registrar chrome"
}
$dirs = Get-ChildItem $env:TEMP -Directory -Filter 'qoder_reg_*' -ErrorAction SilentlyContinue
"leftover profile dirs: $($dirs.Count)"
$dirs | ForEach-Object { Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
"cleaned"
