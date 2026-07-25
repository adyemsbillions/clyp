$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $root '.env'
$examplePath = Join-Path $root '.env.example'

if (-not (Test-Path $envPath)) {
    Copy-Item $examplePath $envPath
}

$secureKey = Read-Host 'Paste your Gemini API key' -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
    $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
}

if ([string]::IsNullOrWhiteSpace($key)) {
    Write-Host '[FAIL] No API key was entered.'
    exit 1
}

$lines = [System.Collections.Generic.List[string]]::new()
Get-Content $envPath | ForEach-Object { [void]$lines.Add($_) }

function Set-EnvValue([string]$name, [string]$value) {
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match ('^' + [regex]::Escape($name) + '=')) {
            $lines[$i] = "$name=$value"
            return
        }
    }
    [void]$lines.Add("$name=$value")
}

Set-EnvValue 'GEMINI_API_KEY' $key.Trim()
Set-EnvValue 'GEMINI_MODEL' 'gemini-3.5-flash'
Set-EnvValue 'GEMINI_LANGUAGE' 'auto'
Set-EnvValue 'GEMINI_API_BASE' 'https://generativelanguage.googleapis.com/v1beta'

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($envPath, $lines, $utf8NoBom)
$key = $null
Write-Host '[OK] Gemini has been configured in .env.'
Write-Host 'Run .\test-gemini.bat to verify the key, then restart Clyp with .\start.bat.'
