param(
  [string]$ConfigPath = (Join-Path $PSScriptRoot "config.yaml"),
  [switch]$Send
)

$ErrorActionPreference = "Stop"

$python = "python"

& $python -m reddit_intent_engine.main --config $ConfigPath @(
  if ($Send) { "--send" }
)

& $python -m reddit_intent_engine.modules.followup --config $ConfigPath @(
  if ($Send) { "--send" }
)

