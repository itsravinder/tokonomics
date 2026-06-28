# startup/

Launchers that start the Tokonomics backend (dashboard `:8765` + proxy `:8788`),
wait until it is ready, then open the dashboard in your browser.

| File | Use |
| --- | --- |
| `start-tokonomics.bat` | Double-click, or run from cmd/PowerShell. The canonical launcher. |
| `start-tokonomics.ps1` | Same, for PowerShell: `powershell -ExecutionPolicy Bypass -File startup\start-tokonomics.ps1` |

## Auto-start on login (Windows)

Windows auto-runs whatever is in your **Startup folder**
(`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`, also reachable by
running `shell:startup`). A small entry there, `Tokonomics.bat`, simply calls
`startup\start-tokonomics.bat` in this project — so on every login the backend
starts and the dashboard opens automatically.

`.bat` is what actually auto-runs; Windows does **not** execute `.ps1` files from
the Startup folder (it opens them in an editor), so the `.ps1` is for manual use.

### Re-install the auto-start entry (e.g. after moving the project)

Run this once in PowerShell:

```powershell
$startup = [Environment]::GetFolderPath('Startup')
$target  = "$PWD\startup\start-tokonomics.bat"
"@echo off`r`ncall ""$target""" | Set-Content -Encoding ascii (Join-Path $startup 'Tokonomics.bat')
```

### Remove the auto-start

Delete `Tokonomics.bat` from the Startup folder (`shell:startup`).
