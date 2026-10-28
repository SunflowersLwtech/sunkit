# Offline test of claude-mesh.ps1: a stub claude.cmd prints where a call landed.
#   powershell -NoProfile -File mesh\plugins\mesh\shell\claude-mesh.test.ps1
$here = $PSScriptRoot
$t = Join-Path ([IO.Path]::GetTempPath()) ('claude-mesh-test-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path (Join-Path $t 'bin') | Out-Null
Set-Content -Path (Join-Path $t 'bin\claude.cmd') -Value '@echo claude %*' -Encoding ascii
$fail = 0
$n = 0
# Check <paired> <gateway key file> <command> <expected output>
function Check($paired, $key, $cmd, $want) {
  $script:n++
  $home_ = Join-Path $t "home$script:n"
  New-Item -ItemType Directory -Path (Join-Path $home_ '.claude'), (Join-Path $home_ '.claude-mesh') | Out-Null
  if ($paired) { Set-Content (Join-Path $home_ '.claude-mesh\config.json') '{}' }
  if ($key) { Set-Content (Join-Path $home_ '.claude\magpie-settings.json') '{}' }
  $gw = Join-Path $home_ '.claude\magpie-settings.json'
  $want = $want.Replace('GW', $gw)
  $code = "`$env:PATH = '$t\bin;' + `$env:SystemRoot + '\System32'; . '$here\claude-mesh.ps1'; $cmd"
  $old = $env:USERPROFILE
  $env:USERPROFILE = $home_
  try { $got = (powershell -NoProfile -Command $code 2>&1 | Out-String).Trim() } finally { $env:USERPROFILE = $old }
  if ($got -eq $want) { "ok   paired=$paired key=${key}: $cmd" } else { "FAIL paired=$paired key=${key}: $cmd -> '$got', want '$want'"; $script:fail = 1 }
}
Check $true $true 'claude' 'claude --settings GW --model claude-opus-5-5 --channels plugin:mesh@sunkit'
Check $true $true 'claude -p hi' 'claude --settings GW --model claude-opus-5-5 -p hi'
Check $true $true 'claude --model x' 'claude --settings GW --model x --channels plugin:mesh@sunkit'
Check $true $true 'claude -p hi --model x' 'claude --settings GW -p hi --model x'
Check $true $true 'claude mcp list' 'claude mcp list'
Check $true $true 'claude --version' 'claude --version'
Check $true $true 'claude-degw' 'claude --channels plugin:mesh@sunkit'
Check $true $true 'claude-degw -p hi' 'claude -p hi'
Check $false $true 'claude' 'claude --settings GW --model claude-opus-5-5'
Check $false $true 'claude-degw' 'claude'
Check $true $false 'claude -p hi' 'claude -p hi'
Check $true $false 'claude' 'claude --channels plugin:mesh@sunkit'
Remove-Item -Recurse -Force $t
exit $fail
