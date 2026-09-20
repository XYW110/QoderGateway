$line = (netstat -ano | Select-String ':5050.*LISTENING').Line
if ($line) {
    $pid_ = ($line -split '\s+')[-1]
    taskkill /PID $pid_ /F
    Start-Sleep -Seconds 2
    "killed $pid_"
} else {
    "not running"
}
