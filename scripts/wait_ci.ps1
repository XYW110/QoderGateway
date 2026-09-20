for ($i = 0; $i -lt 24; $i++) {
    Start-Sleep -Seconds 30
    $r = gh run list --limit 1 --json status,conclusion | ConvertFrom-Json
    if ($r.status -eq 'completed') {
        "CI DONE: $($r.conclusion)"
        break
    }
    "still running ($($i * 30)s)..."
}
