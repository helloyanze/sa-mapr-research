param(
    [Parameter(Mandatory = $true)]
    [string]$SourceDirectory
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$source = (Resolve-Path -LiteralPath $SourceDirectory).Path
$destination = Join-Path $repoRoot 'artifacts\cache'
New-Item -ItemType Directory -Path $destination -Force | Out-Null

$expected = @{
    'defects4j-master.zip' = 'ba1e6bc011d4290a84d4df625cfd3e366c8062722bf6a4648586bff185d13c56'
    'defects4j-gradle-dists-v3.zip' = '2ac17f3a57e47bf05e0f2e01aecb0d1b9147033554eeb7998480eb1b7fa6d4fd'
    'defects4j-gradle-deps-v3.zip' = 'd94100d316e56ef510c44050706a2bea7594d12cc4c7357d36b35e6bb1536545'
    'spotbugs-4.10.3.zip' = 'e814ee5bf9665412658c4d684e45eae3cf993148a71bc8bc93fb343e92288151'
}

foreach ($name in $expected.Keys) {
    $sourcePath = Join-Path $source $name
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Missing artifact: $sourcePath"
    }
    $actual = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected[$name]) {
        throw "SHA-256 mismatch: $sourcePath"
    }
    Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $destination $name) -Force
    Write-Output "Staged $name"
}

Write-Output "Artifacts are ready in $destination (ignored by Git)."
