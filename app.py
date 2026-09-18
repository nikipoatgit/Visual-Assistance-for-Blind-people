"""AI Bus Recognition - Gradio entry point.

Run:  python app.py
Then open the printed URL on the phone (same Wi-Fi network).
Set SHARE=1 to get an https tunnel, which phone browsers require for camera
access on anything other than localhost.
"""

import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import gradio as gr

import aggregator
import config
import pipeline
import status as live_status  # aliased: this module has a local `status` var
import tts

SKIP = gr.skip()  # leaves an output untouched instead of clearing it

CSS = """
#scan_btn { min-height: 110px; font-size: 30px; font-weight: 800; }
#flip_btn { min-height: 60px; font-size: 18px; font-weight: 700; }
#result_box textarea { font-size: 26px; font-weight: 700; text-align: center; }
#status_box textarea { font-size: 18px; }
"""

# --------------------------------------------------------------------------
# Camera switching (pure front-end; Python never sees which camera is live)
# --------------------------------------------------------------------------
# Gradio's webcam widget already has a device picker (the small dropdown-arrow
# icon next to the shutter button), but on phones it (a) starts on the
# front/selfie camera and (b) is easy to miss. This app is pointed at the
# street, not the user, so we auto-pick the rear camera on load, and expose a
# "Switch Camera" button that re-opens the picker and cycles to the next
# device (useful on phones with more than one rear lens).
#
# This pokes at Gradio's internal DOM/aria-labels, so it's best-effort: if a
# Gradio update renames things and this silently does nothing, the fallback
# is simply tapping that small dropdown-arrow icon by hand.
_SELECT_CAMERA_JS = """
() => {
    const openPicker = () => {
        const btn = document.querySelector('button[aria-label="select input source"]')
                 || document.querySelector('button[aria-label="select video source"]');
        if (btn) btn.click();
        return btn;
    };
    const btn = openPicker();
    if (!btn) return;
    setTimeout(() => {
        const select = document.querySelector('.wrap select') || document.querySelector('select');
        if (!select) { btn.click(); return; }
        const options = Array.from(select.options);
        const current = select.selectedIndex;
        let target = options.find(o => /back|rear|environment/i.test(o.text));
        if (!target) {
            // No labelled rear camera found (labels are often hidden until
            // permission has been granted once) -> just cycle to the next
            // device so repeated taps step through everything available.
            target = options[(current + 1) % options.length];
        }
        select.value = target.value;
        select.dispatchEvent(new Event('change', { bubbles: true }));
        btn.click();  // close the dropdown again
    }, 350);
}
"""


# --------------------------------------------------------------------------
# Start / stop
# --------------------------------------------------------------------------
def toggle(scanning):
    scanning = not scanning
    if scanning:
        return (
            True, [], None, False,
            gr.update(value="STOP SCANNING", variant="stop"),
            "Scanning. Point the camera at the street.",
            "--",
            tts.cue("start"),
        )
    return (
        False, [], None, False,
        gr.update(value="START SCANNING", variant="primary"),
        "System paused.",
        "--",
        tts.cue("stop"),
    )


def resume_after_audio():
    """Fired when audio_out finishes playing a clip -> unblock on_frame."""
    return False, "Scanning. Point the camera at the street."


# --------------------------------------------------------------------------
# One streamed frame
# --------------------------------------------------------------------------
def on_frame(frame, scanning, buffer, last_key, playing):
    # While a previous announcement's audio is still playing, drop every
    # incoming frame instead of building a new 10-frame burst on top of it.
    if not scanning or frame is None or playing:
        return buffer, last_key, SKIP, SKIP, SKIP, playing

    buffer = list(buffer) + [pipeline.process_frame(frame)]

    if len(buffer) < config.FRAMES_PER_CYCLE:
        status = f"Sampling… frame {len(buffer)} of {config.FRAMES_PER_CYCLE}"
        return buffer, last_key, SKIP, status, SKIP, playing

    verdict = aggregator.aggregate(buffer)
    buffer = []

    if not aggregator.should_announce(verdict, last_key):
        # Nothing new to say -> immediately free to sample another burst.
        live_status.record_cycle(verdict, announced=False)
        return buffer, last_key, verdict["message"], "Same result. Not repeating.", SKIP, playing

    status = (
        f"Announced (confidence {verdict['confidence']})"
        if verdict["status"] == "SUCCESS" else verdict["message"]
    )
    audio = tts.speak(verdict["message"])
    live_status.record_cycle(verdict, announced=True)

    # Block new bursts until audio_out.end() fires resume_after_audio().
    playing = True
    return buffer, verdict["key"], verdict["message"], status, audio, playing


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------
with gr.Blocks(title="AI Bus Recognition") as demo:

    gr.Markdown("# AI Bus Recognition")

    scanning = gr.State(False)
    buffer = gr.State([])
    last_key = gr.State(None)
    playing = gr.State(False)  # True while the last TTS clip is still playing

    camera = gr.Image(
        sources=["webcam"],
        type="numpy",
        streaming=True,
        label="Camera",
        height=340,
        webcam_options=gr.WebcamOptions(mirror=False),
    )

    with gr.Row():
        scan_btn = gr.Button("START SCANNING", variant="primary",
                             size="lg", elem_id="scan_btn", scale=3)
        flip_btn = gr.Button("🔄 Switch Camera", elem_id="flip_btn", scale=1)

    flip_btn.click(fn=None, inputs=None, outputs=None, js=_SELECT_CAMERA_JS)

    result_box = gr.Textbox(value="--", label="Detected bus",
                            elem_id="result_box", interactive=False)
    status_box = gr.Textbox(value="System paused.", label="Status",
                            elem_id="status_box", interactive=False)
    audio_out = gr.Audio(label="Announcement", autoplay=True,
                         interactive=False, buttons=[])

    scan_btn.click(
        toggle,
        inputs=[scanning],
        outputs=[scanning, buffer, last_key, playing, scan_btn,
                 status_box, result_box, audio_out],
    )

    camera.stream(
        on_frame,
        inputs=[camera, scanning, buffer, last_key, playing],
        outputs=[buffer, last_key, result_box, status_box, audio_out, playing],
        stream_every=config.STREAM_EVERY,
        concurrency_limit=1,
    )

    # Audio playback completion -> unblock the next burst.
    audio_out.stop(
        resume_after_audio,
        inputs=None,
        outputs=[playing, status_box],
    )

    # Give the browser a moment to grant camera permission and enumerate
    # devices before trying to pick the rear one.
    demo.load(fn=None, inputs=None, outputs=None, js="""
        () => { setTimeout(() => { (%s)(); }, 1200); }
    """ % _SELECT_CAMERA_JS)


class _RedirectHandler(BaseHTTPRequestHandler):
    """Bounces any plain-http request to the https:// app on SERVER_PORT.

    Reads the Host header the phone actually dialed (LAN IP or hostname) so
    the redirect target always matches how the phone reached us, instead of
    hardcoding an address.
    """

    def _redirect(self):
        host = self.headers.get("Host", "")
        host_only = host.split(":")[0] or self.client_address[0]
        target = f"https://{host_only}:{config.SERVER_PORT}{self.path}"
        self.send_response(301)
        self.send_header("Location", target)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self._redirect()

    def do_HEAD(self):
        self._redirect()

    def log_message(self, format, *args):  # noqa: A002 - silence per-request logs
        pass


def start_http_redirect():
    """Start the plain-http -> https redirect listener in a background thread.

    Tries HTTP_REDIRECT_PORT (80) first so a phone can just type the bare LAN
    IP; on Ubuntu that needs a privilege grant (see note below), so this falls
    back to HTTP_REDIRECT_FALLBACK_PORT and never blocks app startup either way.
    """
    for port in (config.HTTP_REDIRECT_PORT, config.HTTP_REDIRECT_FALLBACK_PORT):
        try:
            server = HTTPServer((config.SERVER_NAME, port), _RedirectHandler)
        except PermissionError:
            print(
                f"No permission to bind port {port} for the http redirect. "
                "On Ubuntu, either run once with sudo, or grant python the "
                "capability so root isn't needed:\n"
                "  sudo setcap 'cap_net_bind_service=+ep' $(readlink -f $(which python3))"
            )
            continue
        except OSError as e:
            print(f"Could not bind port {port} for the http redirect ({e}).")
            continue
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print(f"http://<lan-ip>:{port} now redirects to https://<lan-ip>:{config.SERVER_PORT}")
        return
    print("HTTP->HTTPS redirect disabled: no port could be bound.")


if __name__ == "__main__":
    print("Loading YOLOv8 + EasyOCR…")
    pipeline.warmup()

    launch_kwargs = dict(
        server_name=config.SERVER_NAME,
        server_port=config.SERVER_PORT,
        share=os.getenv("SHARE", "0") == "1",
        css=CSS,
        theme=gr.themes.Base(),
    )

    have_cert = os.path.exists(config.SSL_CERTFILE) and os.path.exists(config.SSL_KEYFILE)
    if have_cert:
        launch_kwargs.update(
            ssl_certfile=config.SSL_CERTFILE,
            ssl_keyfile=config.SSL_KEYFILE,
            ssl_verify=False,  # self-signed: don't verify against a CA
        )
        print(f"HTTPS enabled -> https://<your-lan-ip>:{config.SERVER_PORT}")
        if config.ENABLE_HTTP_REDIRECT:
            start_http_redirect()
    else:
        print(
            f"No cert/key found ({config.SSL_CERTFILE}, {config.SSL_KEYFILE}); "
            "serving http:// with no redirect (nothing to redirect to yet). "
            "Run generate_cert.sh to enable HTTPS, or set SHARE=1."
        )

    # prevent_thread_lock=True: launch() starts the server in the background
    # and returns immediately (instead of blocking) so demo.app already
    # exists and we can attach one more route to it before parking the main
    # thread. This keeps every other launch() behaviour (SSL, share, etc.)
    # exactly as before.
    demo.launch(prevent_thread_lock=True, **launch_kwargs)

    from fastapi.responses import HTMLResponse

    @demo.app.get("/status")
    def _status_page():
        return HTMLResponse(live_status.render_html())

    print(f"Live status page -> {'https' if have_cert else 'http'}://<your-lan-ip>:{config.SERVER_PORT}/status")

    demo.block_thread()
