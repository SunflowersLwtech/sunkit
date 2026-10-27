# claude-mesh: plain `claude` goes through the magpie gateway and joins the mesh
# (cross-account session messaging) when this machine is paired.
# `claude-degw` is the same session straight to Anthropic, no gateway.
# Subcommands and help/version run the claude executable as is.
# Dot-source from $PROFILE. Works in Windows PowerShell 5.1 and PowerShell 7.

# Gateway by default, print mode (-p) included: what claude-gw.cmd does, done here so a prompt
# never goes through cmd.exe quoting. Without ~\.claude\magpie-settings.json it is claude-degw.
function claude {
  $exe = (Get-Command claude -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source
  if (-not $exe) { Write-Error 'claude executable not found on PATH'; return }
  $dir = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME '.claude' }
  $gw = Join-Path $dir 'magpie-settings.json'
  $subcommand = $args.Count -gt 0 -and ($args[0] -is [string]) -and ($args[0] -match '^[A-Za-z][A-Za-z0-9|_-]*$')
  $info = $false
  foreach ($a in $args) { if ($a -in @('-h', '--help', '-v', '--version')) { $info = $true } }
  if ($subcommand -or $info -or -not (Test-Path $gw)) { claude-degw @args; return }
  $model = @('--model', 'claude-opus-5-5')
  $meshHome = if ($env:MESH_HOME) { $env:MESH_HOME } else { Join-Path $HOME '.claude-mesh' }
  $join = Test-Path (Join-Path $meshHome 'config.json')
  foreach ($a in $args) {
    if ("$a" -eq '--model' -or "$a" -like '--model=*') { $model = @() }
    if ($a -in @('-p', '--print', '--channels') -or
        "$a" -like '--channels=*' -or "$a" -like '--dangerously-load-development-channels*') { $join = $false }
  }
  # Appended, not prepended: --channels is variadic and would swallow a following prompt.
  if ($join) { & $exe --settings $gw @model @args --channels plugin:mesh@sunkit } else { & $exe --settings $gw @model @args }
}

# Direct mode: bypass the gateway, keep the mesh channel.
function claude-degw {
  $exe = (Get-Command claude -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source
  if (-not $exe) { Write-Error 'claude executable not found on PATH'; return }
  $meshHome = if ($env:MESH_HOME) { $env:MESH_HOME } else { Join-Path $HOME '.claude-mesh' }
  $paired = Test-Path (Join-Path $meshHome 'config.json')
  $subcommand = $args.Count -gt 0 -and ($args[0] -is [string]) -and ($args[0] -match '^[A-Za-z][A-Za-z0-9|_-]*$')
  $passThrough = -not $paired -or $subcommand
  foreach ($a in $args) {
    if ($a -in @('-p', '--print', '-h', '--help', '-v', '--version', '--channels') -or
        "$a" -like '--channels=*' -or "$a" -like '--dangerously-load-development-channels*') { $passThrough = $true }
  }
  if ($passThrough) { & $exe @args } else { & $exe @args --channels plugin:mesh@sunkit }
}
