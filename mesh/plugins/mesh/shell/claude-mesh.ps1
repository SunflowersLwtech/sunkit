# claude-mesh: make plain `claude` join the mesh (cross-account session messaging).
# Adds `--channels plugin:mesh@sunkit` to interactive launches only;
# subcommands, print mode, help/version and explicit --channels pass through.
# Dot-source from $PROFILE. Works in Windows PowerShell 5.1 and PowerShell 7.
function claude {
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
  # Appended, not prepended: --channels is variadic and would swallow a following prompt.
  if ($passThrough) { & $exe @args } else { & $exe @args --channels plugin:mesh@sunkit }
}
