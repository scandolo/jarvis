# Jarvis

Local, push-to-talk macOS voice control. Hold right Option, speak one command,
then release. Microphone capture exists only while the key is held; command
evaluation and actuation happen after release.
Deepgram uses Nova-3 multilingual transcription (`language=multi`) so English,
Italian, and mixed-language commands can be transcribed. Distinctive app names
are supplied as per-request recognition keyterms; nothing needs to be changed
in the Deepgram console.

## One-click app

Install or refresh the launcher:

```bash
./scripts/install_app.sh
```

Then open `~/Applications/Jarvis.app` from Finder or Spotlight. The voice path
runs in-process and does not require the FastAPI server. Runtime output is in
`~/Library/Logs/Jarvis/jarvis.log`.

macOS may request Microphone and Accessibility permissions for Jarvis on first
use. The bottom-center status pill stays visible while Jarvis is listening,
thinking, waiting for more speech, requesting confirmation, or reporting a
result. The microphone stream is created on right-Option down and closed on
right-Option up.
The status panel is configured to join other apps' full-screen Spaces. Its
current design is deliberately left unchanged while three smaller visual
directions in `design/mockups/` are reviewed.

Development builds use a stable local code-signing requirement, so rebuilding
Jarvis no longer creates a new Accessibility identity. When migrating from an
older hash-signed build, turn Jarvis off and back on once in Privacy & Security
→ Accessibility. The app waits for that change and starts automatically.

## How decisions work

Jev receives the exact finalized microphone transcript, the frontmost app,
bounded Accessibility-derived screen context, and a deterministic list of safe capabilities. It
selects one next step. Common apps and controls are direct choices; complete
installed-app and settings inventories, visible UI, and open-ended text are
separate branches.

Control-level adapters support selecting an existing visible note in Apple
Notes, a visible Arc sidebar tab, or a visible Calendar event. The native
launcher re-enumerates targets immediately before acting. A window-layout
branch inventories actual application windows (or launchable main apps) and
can place two windows side by side, exiting native full screen first if needed.
The current window also has direct left-half, right-half, and fill-screen
actions when it is available in the fresh inventory.
If a window ignores Accessibility sizing, Jarvis tries macOS's own Move &
Resize command and verifies the resulting geometry.

Calendar event creation has Jev select a spoken title, a date in the next 90
days, a half-hour start slot, and a duration. The user confirms the details
before Jarvis requests write-only Calendar access and saves via EventKit.

Notion offers two explicit workflows when a page is frontmost: insert a text
block or an inline database through its slash menu. Notion's current Electron
window exposes no usable content tree even after requesting accessibility, so
this adapter uses local screen OCR and rechecks an OCR title before clicking.
It only types into a freshly recognized empty block; if none is visible, it
asks you to open one rather than risk overwriting existing content.
On first use, macOS will ask for Screen & System Audio Recording access; grant
it to Jarvis and restart the app. Screenshots are not stored or sent to Jev:
only bounded visible text is supplied as context. Other arbitrary OCR clicks
remain blocked.

Jev can also choose a spoken search subject and open Google results in Arc.
It cannot invent a query; the query must be an exact span of the transcript.
Search results may open in a Little Arc window, depending on Arc's settings.
Selecting an exact visible Google result now opens its freshly verified HTTPS
destination through Arc instead of relying on an unreliable AX link press.

Playful social replies render a brief, click-through emoji shower across the
display: hearts for appreciation, angry faces for teasing, or sad faces for a
lighthearted sad remark.

Python never routes language with aliases, keywords, or regular expressions.
It owns the capability registry and executors. Disruptive effects—deletion,
external communication, financial actions, credential access, security
changes, code execution, power controls, and software installation/removal—
are not executable and are checked again at the actuation boundary.

Brightness, volume, app opening, settings navigation, and on-screen feedback
are explicitly safe capabilities.

## Developer logs

Developer mode is on by default. Its structured JSONL trace includes speech
provider events, partial/final transcripts, desktop context, the exact payload
sent to Jev, Jev's raw response, the selected capability, execution results,
and UI states.

    tail -f ~/Library/Logs/Jarvis/developer.jsonl

The conventional combined runtime log is:

    tail -f ~/Library/Logs/Jarvis/jarvis.log

Audio and API keys are never logged. The developer trace does contain spoken
text and screen context. Set JARVIS_DEVELOPER_MODE=0 before launching to
disable it.

## Development

```bash
python3 -m pytest -q
python3 -m jarvis.live
```
