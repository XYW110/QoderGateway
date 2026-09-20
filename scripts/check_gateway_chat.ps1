$base = 'http://127.0.0.1:5050'
function Post-Chat($body) {
    $json = $body | ConvertTo-Json -Depth 10 -Compress
    try {
        $r = Invoke-WebRequest -Uri "$base/v1/chat/completions" -Method POST -Body $json -ContentType 'application/json' -UseBasicParsing -TimeoutSec 180
        return "HTTP $($r.StatusCode) " + $r.Content
    } catch {
        return "ERR: $($_.Exception.Message)"
    }
}

'--- 1) stream lite ---'
$sw = [Diagnostics.Stopwatch]::StartNew()
$r1 = Post-Chat @{ model = 'lite'; messages = @(@{ role = 'user'; content = 'say hi' }); stream = $true }
"$($sw.Elapsed.TotalSeconds)s len=$($r1.Length) has_data=$($r1 -match 'data:')"
$r1.Substring(0, [Math]::Min(300, $r1.Length))

'--- 2) non-stream qfmodel ---'
$sw = [Diagnostics.Stopwatch]::StartNew()
$r2 = Post-Chat @{ model = 'qfmodel'; messages = @(@{ role = 'user'; content = 'say hi' }); stream = $false }
"$($sw.Elapsed.TotalSeconds)s"
$r2.Substring(0, [Math]::Min(400, $r2.Length))

'--- 3) auto (should fail fast + rotate, no hang) ---'
$sw = [Diagnostics.Stopwatch]::StartNew()
$r3 = Post-Chat @{ model = 'auto'; messages = @(@{ role = 'user'; content = 'hi' }); stream = $false }
"$($sw.Elapsed.TotalSeconds)s"
$r3.Substring(0, [Math]::Min(400, $r3.Length))
