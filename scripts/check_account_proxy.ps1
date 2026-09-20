$base = 'http://127.0.0.1:5050'
$h = @{ 'X-Gateway-Token' = 'flatware7558' }

Start-Sleep -Seconds 4
'--- listening ---'
$listen = netstat -ano | Select-String ':5050.*LISTENING'
if ($listen) { 'OK' } else { 'NOT LISTENING' }

'--- /ui/accounts proxy fields ---'
$r = Invoke-WebRequest -Uri "$base/ui/accounts" -Headers $h -UseBasicParsing -TimeoutSec 15
$data = $r.Content | ConvertFrom-Json
$acc = $data.accounts[0]
"account=$($acc.name) proxy_enabled=$($acc.proxy_enabled) proxy_url='$($acc.proxy_url)' proxy_username='$($acc.proxy_username)' proxy_password_set=$($acc.proxy_password_set) has_password_field=$($acc.PSObject.Properties.Name -contains 'proxy_password')"

'--- POST /ui/accounts/proxy (set then restore) ---'
$body = @{ uid = $acc.uid; proxy_enabled = $true; proxy_url = 'http://127.0.0.1:7890'; proxy_username = 'u'; proxy_password = 'p' } | ConvertTo-Json
$r2 = Invoke-WebRequest -Uri "$base/ui/accounts/proxy" -Method POST -Headers $h -Body $body -ContentType 'application/json' -UseBasicParsing -TimeoutSec 15
"set: $($r2.Content)"
$body2 = @{ uid = $acc.uid; proxy_enabled = $false; proxy_url = ''; proxy_username = '' } | ConvertTo-Json
$r3 = Invoke-WebRequest -Uri "$base/ui/accounts/proxy" -Method POST -Headers $h -Body $body2 -ContentType 'application/json' -UseBasicParsing -TimeoutSec 15
"restore: $($r3.Content)"

'--- 400 on missing uid ---'
try {
    Invoke-WebRequest -Uri "$base/ui/accounts/proxy" -Method POST -Headers $h -Body '{"proxy_enabled":true}' -ContentType 'application/json' -UseBasicParsing -TimeoutSec 15 | Out-Null
    'no error (unexpected)'
} catch {
    "status=$($_.Exception.Response.StatusCode.value__) (expect 400)"
}
