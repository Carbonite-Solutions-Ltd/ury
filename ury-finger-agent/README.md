# URY Finger Agent

A small local HTTP service that lets the URY POS web app capture
fingerprints from a ZK reader (ZK9500 / ZK7500 / Digital Persona U.are.U)
on Windows, by wrapping the official ZKFinger Java SDK in a clean REST
API the browser can talk to.

## Why this exists

ZKBioOnline and ISSOnline (the vendor's bundled web drivers) don't
work cleanly with modern browsers on the hardware we ship with.
ZKBioOnline.exe (Oct 2020 build) crashes when its DLLs are mixed with
the newer ZKFinger 5.3 set, and ISSOnline's HTTP API only accepts
ActiveX-bound commands (IE-only). This agent owns the wire format so
the React POS doesn't have to fight with proprietary driver protocols.

## Install on each cashier PC (one-time, ~30 seconds)

1. **Make sure QZ Tray is installed.** It bundles a Java runtime that
   the agent uses. Most URY cashier PCs already have QZ Tray for
   printing — you do not need to install Java separately.

2. **Make sure the ZKFinger driver is installed.** Download from the
   URY Biometric Settings page (or use the ISSOnline 2.0.66 installer
   shipped with the ZKFinger 5.3 SDK). You should end up with
   `C:\Program Files (x86)\FPOnline\bin\ZKFinger\*.dll` plus
   `C:\Windows\System32\libzkfp.dll`.

3. **Plug in your ZK fingerprint reader** (ZK9500, ZK7500, etc).
   Confirm it shows up in **Device Manager → Biometric Devices**.

4. **Extract this folder** anywhere — typical location is
   `C:\Users\<you>\URYFingerAgent\`. Keep all 4 files together
   (`ury-finger-agent.jar`, `start.bat`, `install.bat`, `uninstall.bat`).

5. **Run `install.bat`.** It does two things:
   - Creates a shortcut in your Windows Startup folder so the agent
     auto-starts on every login (window starts minimised — you won't
     see it).
   - Launches the agent immediately so you can use it now.

6. **Verify.** Open <http://127.0.0.1:9994/> in your browser. You
   should see JSON like `{"agent":"URY Finger Agent","version":"1.0.0",...}`.
   If yes — done.

To stop auto-launching, run `uninstall.bat`. The agent files stay put;
only the Startup shortcut is removed.

## Manual launch (without auto-start)

Just double-click `start.bat`. A console window opens and stays open
until you close it. While it's open, the URY POS can capture
fingerprints. When you close it, the URY POS falls back to PIN +
password.

## API surface

All endpoints are JSON. Default URL is `http://127.0.0.1:9994/`.

| Method | Path              | Body                                                     | Returns |
| ------ | ----------------- | -------------------------------------------------------- | ------- |
| GET    | `/`               | —                                                        | Agent name + version + Java version |
| GET    | `/status`         | —                                                        | Device + session state |
| POST   | `/open`           | —                                                        | Initialise SDK + open device |
| POST   | `/close`          | —                                                        | Close device + free SDK |
| POST   | `/enroll/start`   | —                                                        | Begin a 3-scan enrollment session |
| POST   | `/enroll/poll`    | `{"session_id":"…"}`                                     | Progress + master template when done |
| POST   | `/enroll/cancel`  | —                                                        | Cancel current enrollment |
| POST   | `/capture/start`  | —                                                        | Begin a single-scan capture |
| POST   | `/capture/poll`   | —                                                        | Capture result when finger is placed |
| POST   | `/capture/cancel` | —                                                        | Cancel current capture |
| POST   | `/verify`         | `{"template1":"<b64>","template2":"<b64>"}`             | `{"score":N,"matched":true|false}` |

### Error envelope

Errors return non-2xx status codes plus a JSON body:

```json
{ "error": "no_device", "message": "No fingerprint reader connected ..." }
```

Codes:

- `bad_request` (400) — missing/invalid input
- `not_open` (409) — call `/open` first
- `busy` (409) — another session is running
- `no_session` (404) — polling a session that doesn't exist
- `no_device` (503) — no reader plugged in
- `init_failed` / `open_failed` / `dbinit_failed` (503) — SDK lifecycle errors

## Troubleshooting

**Agent won't start**: check the console window for a stack trace.
Common causes:

- **QZ Tray not installed**: install QZ Tray, then run `start.bat` again.
- **`no libzkfp in java.library.path`**: the ZKFinger driver isn't
  installed (or `libzkfp.dll` isn't in `C:\Windows\System32`).
  Download + install the ISSOnline driver from the URY Biometric
  Settings page.
- **Port 9994 already in use**: another agent is already running, OR
  another app is squatting the port. Edit `start.bat` and change the
  last line to `... -jar "%AGENT_JAR%" --port 9995`.

**Agent runs but `POST /open` returns "No fingerprint reader connected"**:
the reader is unplugged or Windows hasn't bound the driver yet.
Plug + replug, then retry. Confirm the reader appears in Device
Manager → Biometric Devices.

**`POST /open` returns "load fpcapLib failed"**: the ZKFinger DLL set
in `C:\Program Files (x86)\FPOnline\bin\ZKFinger\` is incomplete or
corrupt. Reinstall the ISSOnline driver.

## License notes

- This wrapper code (`com.ury.fingeragent.*`): same license as URY.
- ZKFingerReader.jar (bundled): ZKTeco's redistributable as part of
  their SDK. Not modified.
