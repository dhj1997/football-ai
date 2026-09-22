$ErrorActionPreference = "Stop"

$remoteBefore = (git rev-parse origin/main).Trim()
$localBefore = (git rev-parse HEAD).Trim()
$credential = @("protocol=https", "host=github.com", "") | git credential fill
$fields = @{}
foreach ($line in $credential) {
    $index = $line.IndexOf("=")
    if ($index -gt 0) {
        $fields[$line.Substring(0, $index)] = $line.Substring($index + 1)
    }
}
if (-not $fields.password) {
    throw "GitHub credential helper returned no token"
}

$headers = @{
    Authorization          = "Bearer $($fields.password)"
    Accept                 = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent"           = "football-ai-deployer"
}
$base = "https://api.github.com/repos/dhj1997/football-ai/git"

function Git-Text([string[]] $GitArgs) {
    $output = & git @GitArgs
    if ($LASTEXITCODE -ne 0) {
        throw "git failed: $($GitArgs -join ' ')"
    }
    return (($output -join "`n").TrimEnd("`r", "`n"))
}

function Api-Post([string] $Path, $Body) {
    return Invoke-RestMethod -Method Post -Uri "$base/$Path" -Headers $headers `
        -ContentType "application/json" -Body ($Body | ConvertTo-Json -Depth 10 -Compress) `
        -TimeoutSec 30
}

function Write-LocalApiCommit(
    [string] $Source,
    [string] $Tree,
    [string] $Parent,
    [string] $Message
) {
    $authorName = Git-Text @("show", "-s", "--format=%an", $Source)
    $authorEmail = Git-Text @("show", "-s", "--format=%ae", $Source)
    $authorTime = Git-Text @("show", "-s", "--format=%at", $Source)
    $authorZone = (Git-Text @("show", "-s", "--format=%ai", $Source)).Split(" ")[-1]
    $committerName = Git-Text @("show", "-s", "--format=%cn", $Source)
    $committerEmail = Git-Text @("show", "-s", "--format=%ce", $Source)
    $committerTime = Git-Text @("show", "-s", "--format=%ct", $Source)
    $committerZone = (Git-Text @("show", "-s", "--format=%ci", $Source)).Split(" ")[-1]
    $raw = "tree $Tree`nparent $Parent`nauthor $authorName <$authorEmail> $authorTime $authorZone`n" +
        "committer $committerName <$committerEmail> $committerTime $committerZone`n`n$Message"

    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = "git"
    $startInfo.WorkingDirectory = (Get-Location).Path
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.UseShellExecute = $false
    $startInfo.StandardInputEncoding = [Text.UTF8Encoding]::new($false)
    foreach ($argument in @("hash-object", "-t", "commit", "-w", "--stdin")) {
        $startInfo.ArgumentList.Add($argument)
    }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    [void] $process.Start()
    $process.StandardInput.Write($raw)
    $process.StandardInput.Close()
    $sha = $process.StandardOutput.ReadToEnd().Trim()
    $errorText = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) {
        throw "hash-object failed: $errorText"
    }
    return $sha
}

function Publish-Commit([string] $Source, [string] $Parent) {
    $paths = @(
        (Git-Text @("diff-tree", "--no-commit-id", "--name-only", "-r", $Source)) -split "`n" |
            Where-Object { $_ }
    )
    $entries = @()
    foreach ($path in $paths) {
        $expectedBlob = Git-Text @("rev-parse", "$Source`:$path")
        $bytes = [IO.File]::ReadAllBytes((Join-Path (Get-Location) $path))
        $blob = Api-Post "blobs" @{
            content  = [Convert]::ToBase64String($bytes)
            encoding = "base64"
        }
        if ($blob.sha -ne $expectedBlob) {
            throw "blob mismatch for $path"
        }
        $mode = (Git-Text @("ls-tree", $Source, "--", $path)).Split(" ")[0]
        $entries += @{ path = $path; mode = $mode; type = "blob"; sha = $blob.sha }
    }

    $baseTree = Git-Text @("rev-parse", "$Parent^{tree}")
    $tree = Api-Post "trees" @{ base_tree = $baseTree; tree = $entries }
    $expectedTree = Git-Text @("rev-parse", "$Source^{tree}")
    if ($tree.sha -ne $expectedTree) {
        throw "tree mismatch for $Source"
    }

    $author = @{
        name  = Git-Text @("show", "-s", "--format=%an", $Source)
        email = Git-Text @("show", "-s", "--format=%ae", $Source)
        date  = Git-Text @("show", "-s", "--format=%aI", $Source)
    }
    $committer = @{
        name  = Git-Text @("show", "-s", "--format=%cn", $Source)
        email = Git-Text @("show", "-s", "--format=%ce", $Source)
        date  = Git-Text @("show", "-s", "--format=%cI", $Source)
    }
    $message = Git-Text @("show", "-s", "--format=%B", $Source)
    $commit = Api-Post "commits" @{
        message   = $message
        tree      = $tree.sha
        parents   = @($Parent)
        author    = $author
        committer = $committer
    }
    $localApiSha = Write-LocalApiCommit $Source $tree.sha $Parent $message
    if ($commit.sha -ne $localApiSha) {
        throw "commit serialization mismatch for $Source"
    }
    return [pscustomobject]@{
        Source = $Source
        Sha    = $commit.sha
        Tree   = $tree.sha
        Files  = $paths.Count
    }
}

$remote = Invoke-RestMethod -Uri "$base/ref/heads/main" -Headers $headers -TimeoutSec 20
if ($remote.object.sha -ne $remoteBefore) {
    throw "remote main moved to $($remote.object.sha)"
}

$first = Publish-Commit "4726721cdb614f746fe0ebefbc965d9bbb336e97" $remoteBefore
$second = Publish-Commit "d266e9a2fd8419abfed0653578153754f660f629" $first.Sha

$remoteCheck = Invoke-RestMethod -Uri "$base/ref/heads/main" -Headers $headers -TimeoutSec 20
if ($remoteCheck.object.sha -ne $remoteBefore) {
    throw "remote main moved before update"
}
$updated = Invoke-RestMethod -Method Patch -Uri "$base/refs/heads/main" -Headers $headers `
    -ContentType "application/json" -Body (@{ sha = $second.Sha; force = $false } | ConvertTo-Json -Compress) `
    -TimeoutSec 30
$fields.password = $null

git update-ref refs/heads/main $second.Sha $localBefore
if ($LASTEXITCODE -ne 0) {
    throw "failed to align local main"
}
git update-ref refs/remotes/origin/main $second.Sha $remoteBefore
if ($LASTEXITCODE -ne 0) {
    throw "failed to align origin/main"
}

[pscustomobject]@{
    Design         = $first.Sha
    Implementation = $second.Sha
    Remote         = $updated.object.sha
    Tree           = (git rev-parse "HEAD^{tree}")
} | ConvertTo-Json -Compress
