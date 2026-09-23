"""Kørende onedrive-processer for en config-mappe (feature 0002)."""

from skyhus.process import find_processes


def add_process(proc, pid, args, cgroup="0::/user.slice/user@1000.service/app.slice/x.scope\n"):
    d = proc / str(pid)
    d.mkdir(parents=True)
    (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in args) + b"\0")
    (d / "cgroup").write_text(cgroup)


def test_finds_process_with_confdir(home, tmp_path):
    proc = tmp_path / "proc"
    confdir = home / ".config" / "onedrive-privat"
    add_process(proc, 100, ["/usr/bin/onedrive", "--monitor", f"--confdir={confdir}"],
                "0::/user.slice/user-1000.slice/user@1000.service/app.slice/onedrive-privat.service\n")
    add_process(proc, 101, ["onedrive", "--confdir", "~/.config/onedrive-privat", "--resync"])
    add_process(proc, 102, ["/usr/bin/onedrive", "--confdir=/andet/sted"])
    add_process(proc, 103, ["/usr/bin/vim", f"--confdir={confdir}"])

    found = find_processes(confdir, home=home, proc_root=proc)

    assert [p.pid for p in found] == [100, 101]
    assert found[0].unit == "onedrive-privat.service"
    assert found[1].unit == ""


def test_process_without_confdir_uses_default(home, tmp_path):
    proc = tmp_path / "proc"
    add_process(proc, 200, ["/usr/bin/onedrive", "--monitor"])

    assert [p.pid for p in find_processes(home / ".config" / "onedrive", home=home, proc_root=proc)] == [200]
    assert find_processes(home / ".config" / "onedrive-privat", home=home, proc_root=proc) == []


def test_ignores_entries_that_are_not_processes(home, tmp_path):
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    (proc / "300").mkdir()

    assert find_processes(home / ".config" / "onedrive", home=home, proc_root=proc) == []
