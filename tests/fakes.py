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
