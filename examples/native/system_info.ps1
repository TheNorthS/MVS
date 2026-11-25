# 管理员维护的固定脚本；不给模型提供任意 -Command 文本。
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[ordered]@{
    os_version = [Environment]::OSVersion.VersionString
    machine_name = [Environment]::MachineName
    process_count = @(Get-Process).Count
} | ConvertTo-Json -Compress
