import json
import os
import subprocess
import time

from audit_log import record
from jarvis_core.logging import redact

_HEADER = r"""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$ErrorActionPreference = 'Stop'
"""

_INSPECT = _HEADER + r"""
$windowHandle = $env:JARVIS_UI_WINDOW_HANDLE
$root = if ($windowHandle) {
  [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr][Int64]::Parse($windowHandle))
} else {
  [System.Windows.Automation.AutomationElement]::FocusedElement
}
if ($null -eq $root) { $root = [System.Windows.Automation.AutomationElement]::RootElement }
$items = @($root) + @($root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition))
$result = foreach ($element in $items | Select-Object -First 300) {
  try {
    $r = $element.Current.BoundingRectangle
    [pscustomobject]@{
      name = $element.Current.Name
      automation_id = $element.Current.AutomationId
      type = $element.Current.ControlType.ProgrammaticName.Replace('ControlType.','')
      enabled = $element.Current.IsEnabled
      offscreen = $element.Current.IsOffscreen
      x = [int]$r.X; y = [int]$r.Y; width = [int]$r.Width; height = [int]$r.Height
      invoke = $element.Current.IsInvokePatternAvailable
      value = $element.Current.IsValuePatternAvailable
      select = $element.Current.IsSelectionItemPatternAvailable
      toggle = $element.Current.IsTogglePatternAvailable
    }
  } catch {}
}
[pscustomobject]@{ window = $root.Current.Name; elements = @($result) } | ConvertTo-Json -Depth 5 -Compress
"""

_ACTION = _HEADER + r"""
$target = $env:JARVIS_UI_TARGET
$operation = $env:JARVIS_UI_OPERATION
$newValue = $env:JARVIS_UI_VALUE
$windowHandle = $env:JARVIS_UI_WINDOW_HANDLE
$root = if ($windowHandle) {
  [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr][Int64]::Parse($windowHandle))
} else {
  [System.Windows.Automation.AutomationElement]::FocusedElement
}
if ($null -eq $root) { throw 'Nessun elemento attivo' }
$items = @($root) + @($root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition))
$element = $items | Where-Object {
  $_.Current.AutomationId -eq $target -or $_.Current.Name -eq $target
} | Select-Object -First 1
if ($null -eq $element) {
  $element = $items | Where-Object {
    $_.Current.Name -and $_.Current.Name.IndexOf($target, [StringComparison]::OrdinalIgnoreCase) -ge 0
  } | Select-Object -First 1
}
if ($null -eq $element) { throw "Controllo non trovato: $target" }
$pattern = $null
switch ($operation) {
  'invoke' {
    if ($element.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) { ([System.Windows.Automation.InvokePattern]$pattern).Invoke() }
    elseif ($element.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$pattern)) { ([System.Windows.Automation.SelectionItemPattern]$pattern).Select() }
    elseif ($element.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern, [ref]$pattern)) { ([System.Windows.Automation.TogglePattern]$pattern).Toggle() }
    else { $element.SetFocus() }
  }
  'set_value' {
    if (-not $element.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$pattern)) { throw 'Il controllo non supporta ValuePattern' }
    ([System.Windows.Automation.ValuePattern]$pattern).SetValue($newValue)
  }
  'focus' { $element.SetFocus() }
  default { throw "Operazione non supportata: $operation" }
}
[pscustomobject]@{ success=$true; name=$element.Current.Name; automation_id=$element.Current.AutomationId; operation=$operation } | ConvertTo-Json -Compress
"""


def _record_safe(event, **data):
    try:
        record(event, **data)
    except OSError:
        pass


def _run(script, env=None, timeout=12):
    custom_env = os.environ.copy()
    custom_env.update(env or {})
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
        env=custom_env,
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip()[-1200:])
    return json.loads(result.stdout.strip())


def inspect_ui(window_handle=None):
    started = time.perf_counter()
    try:
        env = {"JARVIS_UI_WINDOW_HANDLE": str(int(window_handle))} if window_handle is not None else None
        data = _run(_INSPECT, env)
        visible = [row for row in data.get("elements", []) if not row.get("offscreen")]
        data["elements"] = visible
        _record_safe(
            "structured_ui_inspected",
            window=data.get("window"),
            count=len(visible),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return {"successo": True, "messaggio": f"Rilevati {len(visible)} controlli strutturati.", "dati": data}
    except Exception as exc:
        return {
            "successo": False,
            "messaggio": "L'accessibilità strutturata non è disponibile per questa finestra.",
            "errore": redact(repr(exc)),
        }


def ui_invoke(target, window_handle=None):
    return _ui_action(target, "invoke", window_handle=window_handle)


def ui_focus(target, window_handle=None):
    return _ui_action(target, "focus", window_handle=window_handle)


def ui_set_value(target, value, window_handle=None):
    return _ui_action(target, "set_value", value, window_handle=window_handle)


def _ui_action(target, operation, value="", window_handle=None):
    try:
        data = _run(
            _ACTION,
            {
                "JARVIS_UI_TARGET": str(target),
                "JARVIS_UI_OPERATION": str(operation),
                "JARVIS_UI_VALUE": str(value),
                "JARVIS_UI_WINDOW_HANDLE": "" if window_handle is None else str(int(window_handle)),
            },
        )
        _record_safe("structured_ui_action", target=target, operation=operation, success=True)
        return {
            "successo": True,
            "messaggio": f"Controllo {data.get('name') or target} gestito tramite accessibilità.",
            "dati": data,
        }
    except Exception as exc:
        safe_error = redact(repr(exc))
        _record_safe("structured_ui_action", target=target, operation=operation, success=False, error=safe_error)
        return {
            "successo": False,
            "messaggio": f"Non riesco a gestire il controllo strutturato {target}.",
            "errore": safe_error,
        }
