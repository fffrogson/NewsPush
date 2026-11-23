# 每日 07:00 从本机踢一下 GitHub Actions。
#
# 为什么需要这个：GitHub 自己的 schedule 在这个仓库上会晚几个小时
# （实测 23:33 UTC 的任务 03:29 UTC 才跑，晚了 3 小时 56 分；
#  01:13 UTC 的任务 07:59 UTC 才跑，晚了 6 小时 46 分），
# 靠它没法在北京时间 07:00 投递。这里用 repository_dispatch 主动触发，
# 工作流里那一步会自动跑；如果当天已经投递过，guard 会直接跳过。
#
# 手动用：powershell -NoProfile -ExecutionPolicy Bypass -File tools\trigger.ps1
# 加 -DryRun 只验证通路、不真的投递。

param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }

$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root "output"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "trigger.log"

function Write-Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $log -Value $line -Encoding utf8
    Write-Host $line
}

# 本机 hosts 把 api.github.com 指到了 127.0.0.1，所以先查真实 IP，
# 再用 curl 的 --resolve 绕开 hosts（证书仍按 api.github.com 校验）。
function Get-ApiIp {
    for ($i = 1; $i -le 3; $i++) {
        try {
            $dns = curl.exe -s --max-time 12 "https://223.5.5.5/resolve?name=api.github.com&type=A"
            if ($dns) {
                $ip = ($dns | ConvertFrom-Json).Answer[0].data
                if ($ip -match '^\d+\.\d+\.\d+\.\d+$') { return $ip }
            }
        } catch { }
        Start-Sleep -Seconds 2
    }
    # 兜底：GitHub API 的常见出口 IP
    foreach ($cand in @("20.205.243.168", "20.27.177.113", "140.82.116.6")) {
        try {
            $code = curl.exe -s -o NUL -w "%{http_code}" --max-time 12 --resolve "api.github.com:443:$cand" "https://api.github.com/zen"
            if ($code -eq "200") { return $cand }
        } catch { }
    }
    return $null
}

try {
    $envFile = Join-Path $root ".env"
    if (-not (Test-Path $envFile)) { throw "找不到 $envFile" }

    $tokLine = Get-Content $envFile | Where-Object { $_ -like "GITHUB_TOKEN=*" } | Select-Object -First 1
    if (-not $tokLine) { throw ".env 里没有 GITHUB_TOKEN" }
    $tok = $tokLine.Substring("GITHUB_TOKEN=".Length).Trim()

    $ip = Get-ApiIp
    if (-not $ip) { throw "拿不到 api.github.com 的可用 IP" }

    if ($DryRun) {
        $payload = '{"event_type":"daily","client_payload":{"dry_run":true}}'
    } else {
        $payload = '{"event_type":"daily"}'
    }
    $tmp = Join-Path $env:TEMP ("dispatch-" + [guid]::NewGuid().ToString("N") + ".json")
    Set-Content -Path $tmp -Value $payload -Encoding ascii -NoNewline

    $code = curl.exe -s --max-time 30 --resolve "api.github.com:443:$ip" -o NUL -w "%{http_code}" `
        -X POST `
        -H "Authorization: Bearer $tok" `
        -H "Accept: application/vnd.github+json" `
        -H "Content-Type: application/json" `
        -d "@$tmp" `
        "https://api.github.com/repos/fffrogson/NewsPush/dispatches"
    Remove-Item $tmp -ErrorAction SilentlyContinue

    if ($code -eq "204") {
        Write-Log "已触发（HTTP 204） ip=$ip dry_run=$($DryRun.IsPresent)"
    } else {
        Write-Log "触发失败 HTTP $code ip=$ip"
        exit 1
    }
} catch {
    Write-Log "触发异常：$($_.Exception.Message)"
    exit 1
}
