'--- build log hits ---'
Select-String -Path logs\pyinstaller_build.log -Pattern 'DrissionPage|DownloadKit|tldextract' | Select-Object -First 12 | ForEach-Object { $_.Line.Trim() }

'--- exe info ---'
$f = Get-Item dist\QoderGateway.exe
"name=$($f.Name) MB=$([math]::Round($f.Length/1MB,1)) time=$($f.LastWriteTime)"

'--- warnings about missing modules ---'
Get-ChildItem build -Filter 'warn-*.txt' -ErrorAction SilentlyContinue | ForEach-Object {
    $hits = Select-String -Path $_.FullName -Pattern 'DrissionPage|DownloadKit|tldextract|win32|lxml'
    if ($hits) { $hits | Select-Object -First 10 | ForEach-Object { '  ' + $_.Line } } else { '  (no browser-stack warnings)' }
}
