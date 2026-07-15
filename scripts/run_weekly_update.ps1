$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

python .\scripts\sync_vlaams_parlement.py
python .\scripts\generate_member_ai_overviews.py
