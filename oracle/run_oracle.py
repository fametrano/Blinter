"""Run the samples in oracle/samples*.txt under cmd.exe and record what it does.

Each sample runs in its own batch file, called from a wrapper that applies
the sample's setup, saves the environment, prints a begin marker, calls the
sample, prints an end marker with the errorlevel, and saves the environment
again. The record of each sample holds its stdout and stderr between the
markers, a second run with stderr merged into stdout, the exit code, and the
variables the sample changed. The formats of the sample files are described
at the top of oracle/samples.txt.
"""

from __future__ import annotations

import argparse
import html
import json
import pathlib
import subprocess
import sys

BEGIN = "===ORACLE-BEGIN==="
END = "===ORACLE-END==="
DIRECTIVES = ("source", "setup", "args", "line")
# cmd.exe reads batch files and writes redirected output in the OEM code page.
ENCODING = "oem" if sys.platform == "win32" else "ascii"
TIMEOUT = 60
LABELS = [
    "goto :eof",
    ":x",
    "echo [:x] %*",
    "goto :eof",
    ":probe",
    "echo [:probe] %*",
    "goto :eof",
]


def parse(paths: list[pathlib.Path]) -> list[dict]:
    """Read the sample files into sample records."""
    samples = []
    for path in paths:
        if path.suffix == ".psv":
            samples.extend(parse_psv(path))
            continue
        source = ""
        setup: list[str] = []
        args = ""
        lines: list[str] = []
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            if line.startswith("#"):
                for name in DIRECTIVES:
                    prefix = f"# {name}: "
                    if line.startswith(prefix):
                        value = line[len(prefix) :]
                        if name == "source":
                            source = value
                        elif name == "setup":
                            setup.append(value)
                        elif name == "args":
                            args = value
                        else:
                            lines.append(value)
                continue
            samples.append(
                {
                    "id": f"{path.name}:{number}",
                    "source": source,
                    "setup": setup,
                    "args": args,
                    "lines": [*lines, line],
                    "sample": line,
                }
            )
            setup, args, lines = [], "", []
    return samples


def parse_psv(path: pathlib.Path) -> list[dict]:
    """Read a file of `BRANCH | ID | PROBE -> EXPECTED | SCRIPT` lines.

    In SCRIPT a literal \\n separates the lines of the batch file, and \\\\
    stands for one backslash, as in C:\\\\no_such_dir.
    """
    samples = []
    text = path.read_text(encoding="utf-8")
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        branch, ident, probe, script = line.split(" | ", 3)
        lines = split_script(script)
        samples.append(
            {
                "id": f"{path.name}:{number} {ident}",
                "source": f"{branch} {ident}: {probe}",
                "setup": [],
                "args": "",
                "lines": lines,
                "sample": lines[-1],
            }
        )
    return samples


def split_script(script: str) -> list[str]:
    """Split SCRIPT at each \\n, reading \\\\ as one backslash."""
    lines, current, index = [], "", 0
    while index < len(script):
        pair = script[index : index + 2]
        if pair == "\\n":
            lines.append(current)
            current = ""
        elif pair == "\\\\":
            current += "\\"
        else:
            current += script[index]
            index += 1
            continue
        index += 2
    return [*lines, current]


def write_batch(path: pathlib.Path, lines: list[str]) -> None:
    """Write a batch file with CRLF line ends, refusing non-OEM text."""
    path.write_bytes("".join(f"{line}\r\n" for line in lines).encode(ENCODING))


def read_env(path: pathlib.Path) -> dict[str, tuple[str, str]]:
    """Read the output of SET into {NAME: (name, value)}."""
    env = {}
    if path.exists():
        for line in path.read_text(encoding=ENCODING, errors="replace").splitlines():
            name, sep, value = line.partition("=")
            if sep:
                env[name.upper()] = (name, value)
    return env


def run_once(sample: dict, rundir: pathlib.Path, merged: bool) -> dict:
    """Run one sample once in a fresh directory and return what it did."""
    files = rundir / "files"
    cwd = rundir / "cwd"
    files.mkdir(parents=True)
    cwd.mkdir()
    before, after = files / "before.env", files / "after.env"
    body = files / "sample.bat"
    wrapper = files / "wrapper.cmd"
    write_batch(body, [*sample["lines"], *LABELS])
    call = f'call "{body}"' + (f" {sample['args']}" if sample["args"] else "")
    write_batch(
        wrapper,
        [
            "@echo off",
            *sample["setup"],
            f'set >"{before}"',
            f"echo {BEGIN}",
            call,
            f"echo {END} errorlevel=%errorlevel%",
            f'set >"{after}"',
        ],
    )
    out_path, err_path = files / "stdout.txt", files / "stderr.txt"
    timed_out = False
    with open(out_path, "wb") as out, open(err_path, "wb") as err:
        try:
            proc = subprocess.run(
                ["cmd", "/d", "/c", str(wrapper)],
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=subprocess.STDOUT if merged else err,
                timeout=TIMEOUT,
                check=False,
            )
            code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out, code = True, None
    stdout = out_path.read_bytes().decode(ENCODING, errors="replace")
    stderr = err_path.read_bytes().decode(ENCODING, errors="replace")
    start = stdout.find(BEGIN)
    end = stdout.find(END)
    result = {
        "exit_code": code,
        "timed_out": timed_out,
        "reached_begin": start >= 0,
        "reached_end": end >= 0,
        "setup_output": stdout[:start] if start >= 0 else stdout,
    }
    if start >= 0:
        tail = stdout[start + len(BEGIN) :].removeprefix("\r\n")
        result["output"] = tail[: tail.find(END)] if end >= 0 else tail
    else:
        result["output"] = ""
    if end >= 0:
        result["errorlevel"] = stdout[end + len(END) :].split("\r\n")[0].strip()
    if not merged:
        result["stderr"] = stderr
        old, new = read_env(before), read_env(after)
        result["env_changes"] = (
            {
                (new.get(key) or old.get(key))[0]: {
                    "before": old[key][1] if key in old else None,
                    "after": new[key][1] if key in new else None,
                }
                for key in sorted(old.keys() | new.keys())
                if old.get(key, (None, None))[1] != new.get(key, (None, None))[1]
            }
            if after.exists()
            else None
        )
    return result


def cell(text: str, limit: int = 12) -> str:
    """Escape text for a Markdown table cell, keeping at most limit lines."""
    lines = text.replace("\r\n", "\n").rstrip("\n").split("\n") if text else []
    if len(lines) > limit:
        lines = [*lines[:limit], f"... ({len(lines) - limit} more lines)"]
    return "<br>".join(
        f"<code>{html.escape(line).replace('|', '&#124;')}</code>" if line else ""
        for line in lines
    )


def env_cell(changes: dict | None) -> str:
    """Describe the variable changes of a sample."""
    if changes is None:
        return "(not recorded: the wrapper did not finish)"
    return "<br>".join(
        f"<code>{html.escape(name)}</code>: "
        + " &rarr; ".join(
            "undefined" if value is None else cell(value or " ")
            for value in (change["before"], change["after"])
        )
        for name, change in changes.items()
    )


def table(ver: str, records: list[dict]) -> str:
    """Render the records as a Markdown table."""
    rows = [
        "# cmd.exe oracle",
        "",
        f"`{ver}`, run as `cmd /d /c wrapper.cmd`, which calls each sample.",
        "",
        "| # | Source | Setup and args | Sample | Output | Stderr | Variables changed | End |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for index, rec in enumerate(records, 1):
        run = rec["run"]
        setup = cell("\n".join(rec["setup"]))
        if rec["args"]:
            setup += f"<br>args: {cell(rec['args'])}"
        if run["setup_output"].strip():
            setup += f"<br>setup printed: {cell(run['setup_output'])}"
        end = (
            f"errorlevel {html.escape(run['errorlevel'])}"
            if run["reached_end"]
            else "**aborted**"
        )
        if run["timed_out"]:
            end = "**timed out**"
        rows.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    html.escape(rec["source"]),
                    setup,
                    cell("\n".join(rec["lines"]), limit=40),
                    cell(run["output"]),
                    cell(run["stderr"]),
                    env_cell(run["env_changes"]),
                    end,
                ]
            )
            + " |"
        )
    return "\n".join(rows) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--samples-dir", type=pathlib.Path, default=pathlib.Path(__file__).parent
    )
    parser.add_argument("--workdir", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--summary", type=pathlib.Path)
    opts = parser.parse_args()
    samples = parse(
        [
            *sorted(opts.samples_dir.glob("samples*.txt")),
            *sorted(opts.samples_dir.glob("samples*.psv")),
        ]
    )
    ver = (
        subprocess.run(["cmd", "/d", "/c", "ver"], capture_output=True, check=True)
        .stdout.decode(ENCODING)
        .strip()
    )
    records = []
    for index, sample in enumerate(samples, 1):
        rundir = opts.workdir / f"{index:03d}"
        records.append(
            {
                **sample,
                "run": run_once(sample, rundir / "separate", merged=False),
                "run_merged": run_once(sample, rundir / "merged", merged=True),
            }
        )
    opts.out.write_text(
        json.dumps({"ver": ver, "samples": records}, indent=2), encoding="utf-8"
    )
    text = table(ver, records)
    print(text)
    if opts.summary:
        with open(opts.summary, "a", encoding="utf-8") as summary:
            summary.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
