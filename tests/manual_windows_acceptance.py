"""Interactive, non-destructive Windows acceptance test; writes a JSON report."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis_windows import InputController, WindowsUIAgent  # noqa: E402
from jarvis_windows.windows import NativeWindowBackend  # noqa: E402
from jarvis_voice.health import probe_audio_input, probe_audio_output  # noqa: E402


def wait_new_window(backend, previous, text, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        candidates = [w for w in backend.list_windows() if w.handle not in previous]
        match = next((w for w in candidates if text.casefold() in w.title.casefold()), None)
        if match:
            return match
        time.sleep(0.1)
    return None


def result(name, status, detail="", **evidence):
    return {"gate": name, "status": status, "detail": detail, "evidence": evidence}


def audio_sample_test(duration=2.0, sample_rate=16_000):
    """Capture a short volatile sample and retain metrics only, never audio."""
    try:
        import numpy as np
        import sounddevice as sd

        frames = int(max(1.0, min(float(duration), 5.0)) * sample_rate)
        recording = sd.rec(frames, samplerate=sample_rate, channels=1, dtype="float32")
        sd.wait()
        samples = np.asarray(recording, dtype=np.float32).reshape(-1)
        absolute = np.abs(samples)
        rms = float(np.sqrt(np.mean(np.square(samples))))
        peak = float(np.max(absolute))
        noise_floor = float(np.percentile(absolute, 20))
        clipping_ratio = float(np.mean(absolute >= 0.99))
        samples.fill(0)
        captured = peak > 0.00001 and clipping_ratio < 0.01
        return result(
            "audio_sample",
            "PASS" if captured else "FAIL",
            "Campione volatile analizzato e azzerato" if captured else "Segnale assente o in clipping",
            duration_seconds=duration,
            sample_rate=sample_rate,
            rms=round(rms, 7),
            peak=round(peak, 7),
            noise_floor=round(noise_floor, 7),
            clipping_ratio=round(clipping_ratio, 7),
            persisted=False,
        )
    except Exception as exc:
        return result("audio_sample", "FAIL", f"{type(exc).__name__}: {exc}", persisted=False)


def desktop_test(output_dir):
    allowed_dir = (ROOT / "data" / "acceptance").resolve()
    output_dir = Path(output_dir).resolve()
    if output_dir != allowed_dir:
        raise ValueError("Acceptance output must remain inside data/acceptance")
    output_dir.mkdir(parents=True, exist_ok=True)
    backend = NativeWindowBackend()
    before = {w.handle for w in backend.list_windows()}
    token = f"jarvis-acceptance-{int(time.time())}"
    target = output_dir / f"{token}.txt"
    target.write_text("initial", encoding="utf-8")
    subprocess.Popen(["notepad.exe", str(target)], shell=False)
    window = wait_new_window(backend, before, token)
    if not window:
        return result("desktop_uia", "SKIP", "Nessuna finestra interattiva visibile al test")
    agent = WindowsUIAgent()
    try:
        snapshot = agent._snapshot(window.handle)
        editor = next((e for e in snapshot.get("elements", []) if e.get("value") and not e.get("offscreen")), None)
        editor = editor or next(
            (
                e
                for e in snapshot.get("elements", [])
                if e.get("type") in {"Document", "Edit"} and not e.get("offscreen")
            ),
            None,
        )
        # Lowercase avoids keyboard-layout/shift differences in the fallback;
        # the gate verifies persistence, not casing semantics.
        payload = "1234567890"
        selector = (editor or {}).get("automation_id") or (editor or {}).get("name")
        if editor and editor.get("value"):
            action = agent.set_text(selector, payload, window_handle=window.handle)
            # ValuePattern changes the control but does not commit the document.
            # Commit and verify the persisted artifact as a separate postcondition.
            if action.get("success", action.get("successo", False)):
                backend.focus(window.handle)
                InputController().hotkey(["ctrl", "s"])
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and target.read_text(encoding="utf-8") != payload:
                    time.sleep(0.05)
                # Some Notepad builds expose ValuePattern but delay or omit the
                # document commit. Retry once through the focused editor and
                # require the persisted file as the authoritative postcondition.
                if target.read_text(encoding="utf-8") != payload:
                    controls = InputController()
                    backend.focus(window.handle)
                    x = editor["x"] + editor["width"] // 2 if editor else window.x + window.width // 2
                    y = editor["y"] + editor["height"] // 2 if editor else window.y + window.height // 2
                    controls.click(x, y)
                    controls.hotkey(["ctrl", "a"])
                    action = controls.write(payload)
                    controls.hotkey(["ctrl", "s"])
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline and target.read_text(encoding="utf-8") != payload:
                        time.sleep(0.05)
        else:
            controls = InputController()
            x = editor["x"] + editor["width"] // 2 if editor else window.x + window.width // 2
            y = editor["y"] + editor["height"] // 2 if editor else window.y + window.height // 2
            action = {"success": False, "message": "Inserimento non tentato"}
            for _attempt in range(2):
                backend.focus(window.handle)
                controls.click(x, y)
                controls.hotkey(["ctrl", "a"])
                action = controls.write(payload)
                controls.hotkey(["ctrl", "s"])
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and target.read_text(encoding="utf-8") != payload:
                    time.sleep(0.05)
                if target.read_text(encoding="utf-8") == payload:
                    break
        passed = action.get("successo", action.get("success", False))
        deadline = time.monotonic() + 3
        while passed and time.monotonic() < deadline and target.read_text(encoding="utf-8") != payload:
            time.sleep(0.05)
        passed = passed and target.read_text(encoding="utf-8") == payload
        return result(
            "desktop_uia",
            "PASS" if passed else "FAIL",
            action.get("messaggio", action.get("message", "")),
            hwnd=window.handle,
        )
    except Exception as exc:
        return result("desktop_uia", "FAIL", f"{type(exc).__name__}: {exc}", hwnd=window.handle)
    finally:
        backend.close(window.handle)
        agent.close()


def inspect_safe_application(backend, command, title_hint, gate):
    before = {w.handle for w in backend.list_windows()}
    subprocess.Popen(command, shell=False)
    window = wait_new_window(backend, before, title_hint)
    if not window:
        return result(gate, "SKIP", f"Finestra {title_hint!r} non visibile al test")
    agent = WindowsUIAgent()
    try:
        snapshot = agent._snapshot(window.handle)
        passed = bool(snapshot.get("window")) and bool(snapshot.get("elements"))
        return result(
            gate,
            "PASS" if passed else "FAIL",
            f"{len(snapshot.get('elements', []))} controlli UIA",
            hwnd=window.handle,
        )
    except Exception as exc:
        return result(gate, "FAIL", f"{type(exc).__name__}: {exc}", hwnd=window.handle)
    finally:
        backend.close(window.handle)
        agent.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--broker", action="store_true", help="include the separate UAC broker smoke test")
    parser.add_argument("--audio-sample", action="store_true", help="capture two volatile seconds from the microphone")
    args = parser.parse_args()
    output_dir = ROOT / "data" / "acceptance"
    output_dir.mkdir(parents=True, exist_ok=True)
    checks = []
    for gate, probe in (("audio_input", probe_audio_input), ("audio_output", probe_audio_output)):
        try:
            checks.append(result(gate, "PASS" if probe() else "FAIL", "Dispositivo enumerato"))
        except Exception as exc:
            checks.append(result(gate, "FAIL", f"{type(exc).__name__}: {exc}"))
    checks.append(
        audio_sample_test() if args.audio_sample else result("audio_sample", "SKIP", "Consenso non richiesto")
    )
    try:
        backend = NativeWindowBackend()
        areas = backend.work_areas()
        checks.append(result("display", "PASS", f"{len(areas)} monitor rilevati", work_areas=areas))
        checks.append(desktop_test(output_dir))
        checks.append(inspect_safe_application(backend, ["calc.exe"], "Calcolatrice", "calculator_uia"))
        checks.append(
            inspect_safe_application(
                backend,
                ["explorer.exe", str(output_dir)],
                "acceptance",
                "file_explorer_uia",
            )
        )
        checks.append(
            result(
                "multi_monitor",
                "PASS" if len(areas) > 1 else "SKIP",
                "Verifica disponibile" if len(areas) > 1 else "Un solo monitor",
            )
        )
    except Exception as exc:
        checks.append(result("windows_session", "FAIL", f"{type(exc).__name__}: {exc}"))
    if args.broker:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "tests" / "manual_broker_smoke.py")],
            timeout=240,
            check=False,
            capture_output=True,
            text=True,
        )
        output = (completed.stdout or completed.stderr or "").strip()[-2000:]
        try:
            broker_evidence = json.loads(output) if output else {}
        except json.JSONDecodeError:
            broker_evidence = {"output": output}
        checks.append(
            result(
                "admin_broker",
                "PASS" if completed.returncode == 0 else "FAIL",
                f"exit={completed.returncode}",
                broker=broker_evidence,
            )
        )
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "interactive": True, "checks": checks}
    path = output_dir / f"acceptance-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"Report: {path}")
    return 1 if any(row["status"] == "FAIL" for row in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
