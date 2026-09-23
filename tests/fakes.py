"""Fakes for the onedrive process and the clock."""

from pathlib import Path


class FakeProcess:
    """The same as a Popen process. The test itself plays the role of the client."""

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
            # As onedrive 2.5: --reauth deletes refresh_token before the client asks for a sign-in.
            confdir = next(a.split("=", 1)[1] for a in self.args if a.startswith("--confdir="))
            (Path(confdir) / "refresh_token").unlink(missing_ok=True)

    # The Popen interface
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

    def receive(self, sig):
        """A signal from ``FakeSignals``."""
        import signal
        if sig == signal.SIGKILL:
            self.kill()
        else:
            self.terminate()

    def wait(self, timeout=None):
        return self.returncode

    # The actions of the client
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
    """A replacement for ``urllib.request.urlopen`` with recorded responses from Microsoft.

    ``pages`` uses the full URL or only the path as key. A response is a
    ``dict`` that becomes JSON, or an ``Exception`` that the call raises.
    """

    TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

    def __init__(self, pages=None, token=None):
        import json
        self._json = json
        self.pages = dict(pages or {})
        self.token = token if token is not None else {
            "access_token": "access", "refresh_token": "NEW", "expires_in": 3600}
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
            raise AssertionError(f"No recorded response for {url}")
        if isinstance(answer, Exception):
            raise answer
        return io.BytesIO(self._json.dumps(answer).encode())

    def graph_requests(self):
        return [r for r in self.requests if r.full_url != self.TOKEN_URL]


def http_error(url, code, body):
    """An ``HTTPError`` with a JSON body, as Microsoft sends it."""
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
    """A replacement for subprocess.run. The calls are in ``calls`` and in ``log``.

    ``outputs`` gives stdout for a call, for example ``{"cat": "..."}``. ``fail``
    gives exit code 1 for a call if the word is in the command.
    ``on_call`` is called with the command before the response, so the test can see the state.
    """

    def __init__(self, outputs=None, fail=(), stderr="error", log=None, on_call=None):
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
    """The same as ``onedrive --upload-only`` started with ``Popen(stdout=PIPE, text=True)``.

    ``lines`` is the stdout of the client. ``returncode`` is the exit code when stdout is read.
    ``on_line`` is called before each line, so the test can see the state while it runs.
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
    """A replacement for ``sideeffects.popen`` for the upload in ``apply.execute``.

    The calls are in ``calls`` and in ``log``, so the test can see the sequence together with ``ScriptedRun``.
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
    """The same as ``onedrive --upload-only`` that runs until it gets a signal (feature 0010).

    The process writes ``lines`` and then waits. A signal in ``stops_on`` stops it.
    The exit code is ``exit_code`` or ``-signal``. ``signals`` are the signals that the process got.
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
        # Safety net: a failed test must not hang.
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
    """A replacement for ``sideeffects.popen`` with ``FakeStoppableUpload``. ``processes`` are the started ones."""

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
    """A replacement for ``sideeffects.signal_process``. ``sent`` is (signal, time) for each call."""

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
    """A fake clock. ``sleep`` moves the clock forward without waiting."""

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
