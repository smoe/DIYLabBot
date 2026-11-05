# Execute all offline protocol checks in the caller's PowerShell session.
$ErrorActionPreference = 'Stop'
python (Join-Path $PSScriptRoot 'verify_centrifuge_protocol.py')
if ($LASTEXITCODE -ne 0) { throw 'CF01 native-frame/mock verification failed' }
$validationOutput = & (Join-Path $PSScriptRoot 'validate_centrifuge_fdl.ps1')
$taskRoot = Split-Path -Parent $PSScriptRoot
$context = Get-Content -LiteralPath (Join-Path $taskRoot 'tmp/cf01-animation-context.json') -Raw | ConvertFrom-Json
$validation = [ordered]@{passed=$true; stdout=($validationOutput -join [Environment]::NewLine); runtime_conformance_tested=$false; schema='exports/research/sila2-schema/FeatureDefinition.xsd'}
[System.IO.File]::WriteAllText((Join-Path $context.out 'sila-schema-validation.json'), ($validation | ConvertTo-Json), [System.Text.UTF8Encoding]::new($false))
Write-Output $validationOutput
