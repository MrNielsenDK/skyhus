"""Attrapper for onedrive-processen og uret."""

from pathlib import Path


class FakeProcess:
    """Svarer til en Popen-proces. Testen spiller selv klientens rolle."""

    def __init__(self, args, **kwargs):
        self.args = list(args)
        self.kwargs = kwargs
        self.returncode = None
        self.terminated = False
        self.killed = False
        auth, response = self.args[self.args.index("--auth-files") + 1].split(":")
        self.auth_url_path = Path(auth)
        self.response_path = Path(response)
        if "--reauth" in self.args:
            # Som onedrive 2.5: --reauth sletter refresh_token, før klienten beder om login.
            confdir = next(a.split("=", 1)[1] for a in self.args if a.startswith("--confdir="))
            (Path(confdir) / "refresh_token").unlink(missing_ok=True)

    # Popen-grænsefladen
    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        if self.returncode is None:
            self.returncode = -15

    def kill(self):
        self.killed = True
        if self.returncode is None:
            self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode

    # Klientens handlinger
    def write_auth_url(self, url):
        self.auth_url_path.write_text(url + "\n")

    def log(self, text):
        out = self.kwargs.get("stdout")
        if out is not None and hasattr(out, "write"):
            out.write(text.encode() if "b" in getattr(out, "mode", "") else text)
            out.flush()

    def exit(self, code):
        self.returncode = code


class FakePopen:
    def __init__(self):
        self.processes: list[FakeProcess] = []

    def __call__(self, args, **kwargs):
        process = FakeProcess(args, **kwargs)
        self.processes.append(process)
        return process

    @property
    def last(self) -> FakeProcess:
        return self.processes[-1]


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeGraph:
    """Erstatning for ``urllib.request.urlopen`` med optagne svar fra Microsoft.

    ``pages`` bruger den fulde URL eller kun stien som nøgle. Et svar er et
    ``dict``, der bliver til JSON, eller en ``Exception``, som kaldet kaster.
    """

    TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

    def __init__(self, pages=None, token=None):
        import json
        self._json = json
        self.pages = dict(pages or {})
        self.token = token if token is not None else {
            "access_token": "adgang", "refresh_token": "NYT", "expires_in": 3600}
        self.requests = []

    def __call__(self, request, timeout=None):
        import io
        from urllib.parse import urlsplit
        self.requests.append(request)
        url = request.full_url
        if url == self.TOKEN_URL:
            answer = self.token
        elif url in self.pages:
            answer = self.pages[url]
        else:
            answer = self.pages.get(urlsplit(url).path)
        if answer is None:
            raise AssertionError(f"Intet optaget svar for {url}")
        if isinstance(answer, Exception):
            raise answer
        return io.BytesIO(self._json.dumps(answer).encode())

    def graph_requests(self):
        return [r for r in self.requests if r.full_url != self.TOKEN_URL]


def http_error(url, code, body):
    """En ``HTTPError`` med et JSON-svar, som Microsoft sender det."""
    import io
    import json
    from email.message import Message
    from urllib.error import HTTPError
    return HTTPError(url, code, "Bad Request", Message(), io.BytesIO(json.dumps(body).encode()))


def folder(name, item_id=None, child_count=0):
    return {"id": item_id or f"id-{name}", "name": name, "folder": {"childCount": child_count}}


def file_item(name):
    return {"id": f"id-{name}", "name": name, "file": {"mimeType": "text/plain"}}


class ScriptedRun:
    """Erstatning for subprocess.run. Kaldene står i ``calls`` og i ``log``.

    ``outputs`` giver stdout for et kald, fx ``{"cat": "..."}``. ``fail``
    giver exit-kode 1 for et kald, hvis ordet findes i kommandoen.
    ``on_call`` kaldes med kommandoen, før svaret, så testen kan se tilstanden.
    """

    def __init__(self, outputs=None, fail=(), stderr="fejl", log=None, on_call=None):
        import subprocess
        self._cp = subprocess.CompletedProcess
        self.outputs = dict(outputs or {})
        self.fail = set(fail)
        self.stderr = stderr
        self.calls = []
        self.log = log if log is not None else []
        self.on_call = on_call

    def __call__(self, args, **kwargs):
        args = list(args)
        self.calls.append(args)
        self.log.append(("run", args))
        if self.on_call is not None:
            self.on_call(args)
        failed = any(word in args for word in self.fail)
        stdout = ""
        for word, text in self.outputs.items():
            if word in args:
                stdout = text
        return self._cp(args, 1 if failed else 0, stdout=stdout, stderr=self.stderr if failed else "")


class FakeUploadProcess:
    """Svarer til ``onedrive --upload-only`` startet med ``Popen(stdout=PIPE, text=True)``.

    ``lines`` er klientens stdout. ``returncode`` er exit-koden, når stdout er læst.
    ``on_line`` kaldes før hver linje, så testen kan se tilstanden undervejs.
    """

    def __init__(self, args, lines, returncode, on_line=None, **kwargs):
        self.args = list(args)
        self.kwargs = kwargs
        self.pid = 4711
        self._lines = list(lines)
        self._final = returncode
        self._on_line = on_line
        self.returncode = None
        self.terminated = False
        self.stdout = self._read()

    def _read(self):
        for line in self._lines:
            if self._on_line is not None:
                self._on_line(line)
            yield line + "\n"
        self.returncode = self._final

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        for _ in self.stdout:
            pass
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.terminated = True


class FakeUploadPopen:
    """Erstatning for ``sideeffects.popen`` til uploaden i ``apply.execute``.

    Kaldene står i ``calls`` og i ``log``, så testen kan se rækkefølgen sammen med ``ScriptedRun``.
    """

    def __init__(self, lines=(), returncode=0, log=None, on_line=None):
        self.lines = list(lines)
        self.returncode = returncode
        self.calls = []
        self.kwargs = []
        self.log = log if log is not None else []
        self.on_line = on_line

    def __call__(self, args, **kwargs):
        args = list(args)
        self.calls.append(args)
        self.kwargs.append(kwargs)
        self.log.append(("popen", args))
        return FakeUploadProcess(args, self.lines, self.returncode, self.on_line, **kwargs)


class FakeStoppableUpload:
    """Svarer til ``onedrive --upload-only``, der kører, til den får et signal (feature 0010).

    Processen skriver ``lines`` og venter derefter. Et signal i ``stops_on`` stopper den.
    Exit-koden er ``exit_code`` eller ``-signal``. ``signals`` er de signaler, processen fik.
    """

    def __init__(self, args, lines, stops_on, exit_code=None, on_line=None, **kwargs):
        import threading
        self.args = list(args)
        self.kwargs = kwargs
        self.pid = 4712
        self.signals = []
        self.returncode = None
        self._lines = list(lines)
        self._stops_on = set(stops_on)
        self._exit_code = exit_code
        self._on_line = on_line
        self._stopped = threading.Event()
        self.stdout = self._read()

    def _read(self):
        for line in self._lines:
            if self._on_line is not None:
                self._on_line(line)
            yield line + "\n"
        # Sikkerhedsnet: en fejlet test må ikke hænge.
        if not self._stopped.wait(10) and self.returncode is None:
            self.returncode = 1

    def receive(self, sig):
        self.signals.append(sig)
        if sig in self._stops_on and self.returncode is None:
            self.returncode = self._exit_code if self._exit_code is not None else -sig
            self._stopped.set()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        for _ in self.stdout:
            pass
        return self.returncode


class FakeStoppablePopen:
    """Erstatning for ``sideeffects.popen`` med ``FakeStoppableUpload``. ``processes`` er de startede."""

    def __init__(self, lines=(), stops_on=(15,), exit_code=None, on_line=None):
        self.lines = list(lines)
        self.stops_on = stops_on
        self.exit_code = exit_code
        self.on_line = on_line
        self.processes = []

    def __call__(self, args, **kwargs):
        process = FakeStoppableUpload(args, self.lines, self.stops_on, self.exit_code, self.on_line, **kwargs)
        self.processes.append(process)
        return process


class FakeSignals:
    """Erstatning for ``sideeffects.signal_process``. ``sent`` er (signal, tidspunkt) for hvert kald."""

    def __init__(self, clock=None):
        self.clock = clock
        self.sent = []

    def __call__(self, process, sig):
        self.sent.append((sig, self.clock() if self.clock is not None else None))
        receive = getattr(process, "receive", None)
        if receive is not None:
            receive(sig)

    @property
    def signals(self):
        return [sig for sig, _ in self.sent]


class SteppingClock:
    """Et falsk ur. ``sleep`` flytter uret frem uden at vente."""

    def __init__(self, now=1000.0):
        import threading
        self.now = now
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            return self.now

    def sleep(self, seconds):
        with self._lock:
            self.now += seconds
