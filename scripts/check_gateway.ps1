Start-Sleep -Seconds 3
$listen = netstat -ano | Select-String ':5050.*LISTENING'
if ($listen) { "LISTENING OK" } else { "NOT LISTENING" }
try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:5050/v1/models' -UseBasicParsing -TimeoutSec 10
    "HTTP $($r.StatusCode)"
    $r.Content.Substring(0, [Math]::Min(300, $r.Content.Length))
} catch {
    "REQ-ERR: $($_.Exception.Message)"
}
