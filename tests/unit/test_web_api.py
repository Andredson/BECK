# SPDX-License-Identifier: GPL-3.0-only
"""Recalbox's web API as a source of what's missing (step 11.2, DEC-79). No real network is used."""

import http.client
import json
from pathlib import Path
from typing import Any, ClassVar

import pytest

from beck import cli
from beck.errors import ReportParseError, TransportError
from beck.frontends.recalbox import RecalboxAdapter
from beck.transports import webapi
from tests.factories import make_bios_file, make_missing, make_report_text, settings_text
from tests.fakes import FakeSMBServer, install_fake_smb

A, B, C = "A" * 32, "B" * 32, "C" * 32


def bios(
    status: str,
    md5s: list[str],
    *,
    mandatory: bool = True,
    hash_mandatory: bool = True,
    current: str = "0" * 32,
) -> dict[str, Any]:
    """One BIOS as Recalbox 10.1.1's ``GET /api/bios`` gives it."""
    return {
        "mandatory": mandatory,
        "hashMatchingMandatory": hash_mandatory,
        "displayFileName": "x",
        "notes": "",
        "currentMd5": current,
        "md5List": md5s,
        "cores": ["libretro/x"],
        "lightStatus": "Red",
        "realStatus": status,
    }


def answer(**systems: dict[str, dict[str, Any]]) -> bytes:
    return json.dumps(
        {
            name: {"fullName": f"System {name}", "scanResult": {}, "biosList": bios_list}
            for name, bios_list in systems.items()
        }
    ).encode()


def parsed(raw: bytes) -> list[tuple[str, bool | None, bool, str | None, list[str]]]:
    entries, _rejected = RecalboxAdapter().parse_api(raw)
    return [
        (e.target.as_posix(), e.required, e.incorrect, e.current_md5, sorted(e.md5s))
        for e in entries
    ]


# Reading the answer


def test_the_answer_gives_what_the_report_would() -> None:
    raw = answer(
        ps1={
            "ps1/scph1001.bin": bios("FileNotFound", [A, B]),
            "ps1/ok.bin": bios("HashMatching", [A], current=A),
        },
        vice={
            "vice/JiffyDOS_C64.bin": bios("FileNotFound", [C], mandatory=False),
            "vice/wrong.bin": bios("HashNotMatching", [A], current=C),
            "vice/loose.bin": bios("HashNotMatching", [A], hash_mandatory=False, current=C),
        },
    )

    assert parsed(raw) == [
        ("ps1/scph1001.bin", True, False, None, ["a" * 32, "b" * 32]),
        ("vice/JiffyDOS_C64.bin", False, False, None, ["c" * 32]),
        ("vice/wrong.bin", True, True, "c" * 32, ["a" * 32]),
    ]


def test_an_entry_names_its_system() -> None:
    entries, _ = RecalboxAdapter().parse_api(answer(ps1={"a.bin": bios("FileNotFound", [A])}))

    assert [(e.name, e.system) for e in entries] == [("a.bin", "System ps1")]


def test_a_file_too_unreadable_to_hash_has_no_current_md5() -> None:
    # A .zip target that isn't a zip archive: Recalbox gives all zeros (DEC-74).
    raw = answer(neo={"neocdz.zip": bios("HashNotMatching", [A])})

    assert parsed(raw) == [("neocdz.zip", True, True, None, ["a" * 32])]


@pytest.mark.parametrize(
    "key", ["neogeo.zip|/recalbox/share/roms/neogeo/neogeo.zip", "/recalbox/share/bios/neogeo.zip"]
)
def test_the_first_of_two_paths_or_a_whole_path_is_used(key: str) -> None:
    assert parsed(answer(neo={key: bios("FileNotFound", [A])}))[0][0] == "neogeo.zip"


@pytest.mark.parametrize(
    "key", ["../outside.bin", "/recalbox/share/roms/x.bin", "a\\b.bin", "evil\x1b[2J.bin"]
)
def test_an_unsafe_path_is_refused_like_in_a_report(key: str) -> None:
    entries, rejected = RecalboxAdapter().parse_api(answer(x={key: bios("FileNotFound", [A])}))

    assert entries == []
    assert [error.code for error in rejected] == ["unsafe_path"]


@pytest.mark.parametrize(
    "raw",
    [
        b"<html>not json</html>",
        b"[]",
        json.dumps({"x": {"fullName": "X"}}).encode(),
        answer(x={"a.bin": bios("Unknown", [A])}),
        answer(x={"a.bin": bios("FileNotFound", ["not an md5"])}),
        answer(x={"a.bin": {"realStatus": "FileNotFound"}}),
        b"\xff\xfe",
    ],
)
def test_an_answer_in_another_form_is_a_parse_error(raw: bytes) -> None:
    with pytest.raises(ReportParseError):
        RecalboxAdapter().parse_api(raw)


# The GET itself


class FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status, self.reason, self.body = status, "Reason", body

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


class FakeConnection:
    made: ClassVar[list["FakeConnection"]] = []
    status: ClassVar[int] = 200
    body: ClassVar[bytes] = b"{}"
    error: ClassVar[Exception | None] = None

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.args = (host, port, timeout)
        self.requests: list[tuple[str, str]] = []
        self.closed = False
        FakeConnection.made.append(self)

    def request(self, method: str, path: str, headers: dict[str, str]) -> None:
        if FakeConnection.error is not None:
            raise FakeConnection.error
        self.requests.append((method, path))

    def getresponse(self) -> FakeResponse:
        return FakeResponse(FakeConnection.status, FakeConnection.body)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def connection(monkeypatch: pytest.MonkeyPatch) -> type[FakeConnection]:
    FakeConnection.made, FakeConnection.status, FakeConnection.body = [], 200, b"{}"
    FakeConnection.error = None
    monkeypatch.setattr(http.client, "HTTPConnection", FakeConnection)
    return FakeConnection


def test_get_returns_the_body_and_closes(connection: type[FakeConnection]) -> None:
    connection.body = b'{"a": 1}'

    assert webapi.get("recalbox.local", 81, "/api/bios", 12) == b'{"a": 1}'

    (made,) = connection.made
    assert made.args == ("recalbox.local", 81, 12)
    assert made.requests == [("GET", "/api/bios")]
    assert made.closed


@pytest.mark.parametrize(
    ("status", "body", "error", "message"),
    [
        (404, b"", None, "http://h:81/api/bios answered 404 Reason"),
        (200, b"", ConnectionRefusedError(111, "Connection refused"), "No answer from http://h:81"),
        (200, b"", TimeoutError("timed out"), "No answer from http://h:81/api/bios: timed out"),
        (200, b"", http.client.BadStatusLine("x"), "No answer from"),
    ],
)
def test_anything_but_a_200_is_a_transport_error_and_closes(
    connection: type[FakeConnection],
    status: int,
    body: bytes,
    error: Exception | None,
    message: str,
) -> None:
    connection.status, connection.body, connection.error = status, body, error

    with pytest.raises(TransportError, match=message.replace("?", r"\?")):
        webapi.get("h", 81, "/api/bios", 5)

    assert connection.made[0].closed


def test_an_answer_too_big_is_refused(
    connection: type[FakeConnection], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(webapi, "MAX_RESPONSE", 10)
    connection.body = b"x" * 11

    with pytest.raises(TransportError, match="more than"):
        webapi.get("h", 81, "/api/bios", 5)


# Through the command line


@pytest.fixture
def device(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeSMBServer:
    """A fake Recalbox, named in the settings file. Its report differs from its API's answer."""
    server = install_fake_smb(monkeypatch)
    settings = tmp_path / "settings.toml"
    text = settings_text("smb://recalbox.test/bios", timeout=17)
    settings.write_text(text, encoding="utf-8")
    settings.chmod(0o600)
    monkeypatch.setenv("BECK_CONFIG", str(settings))
    server.files[("bios", "missing_bios_report.txt")] = make_report_text(
        [make_missing("from-report.bin", "d" * 32)]
    ).encode()
    return server


def missing_targets(capsys: pytest.CaptureFixture[str]) -> tuple[str, list[str]]:
    document = json.loads(capsys.readouterr().out)
    return document["missing_from"], [entry["target"] for entry in document["missing"]]


def test_report_reads_the_api_first(
    device: FakeSMBServer, capsys: pytest.CaptureFixture[str]
) -> None:
    device.api_answer = answer(ps1={"ps1/from-api.bin": bios("FileNotFound", [A])})

    assert cli.main(["--json", "report"]) == 0

    assert missing_targets(capsys) == ("api", ["ps1/from-api.bin"])
    assert device.api_calls == [("recalbox.test", 81, "/api/bios", 17)]


def test_without_an_answer_it_reads_the_report_and_says_so(
    device: FakeSMBServer, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["--json", "report"]) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out)["missing_from"] == "report"
    assert (
        "Recalbox's web API didn't give the list of missing files: No answer from "
        "http://recalbox.test:81/api/bios: connection refused. BECK reads missing_bios_report.txt "
        "instead, which may be out of date."
    ) in captured.err


def test_an_answer_beck_cannot_read_falls_back_to_the_report(
    device: FakeSMBServer, capsys: pytest.CaptureFixture[str]
) -> None:
    device.api_answer = b"<html>a login page</html>"

    assert cli.main(["--json", "report"]) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out)["missing_from"] == "report"
    assert "BECK can't read the web API's answer" in captured.err


def test_no_api_reads_the_report_and_asks_nothing(
    device: FakeSMBServer, capsys: pytest.CaptureFixture[str]
) -> None:
    device.api_answer = answer(ps1={"ps1/from-api.bin": bios("FileNotFound", [A])})

    assert cli.main(["--json", "report", "--no-api"]) == 0

    assert missing_targets(capsys) == ("report", ["from-report.bin"])
    assert device.api_calls == []


def test_check_uploads_what_the_api_lists(
    device: FakeSMBServer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = make_bios_file(tmp_path / "source", "mine.bin")
    device.api_answer = answer(ps1={"ps1/scph1001.bin": bios("FileNotFound", [file.md5.upper()])})

    assert cli.main(["--json", "check", "--source", str(tmp_path / "source")]) == 0

    document = json.loads(capsys.readouterr().out)
    assert document["missing_from"] == "api"
    assert [(u["target"], u["status"]) for u in document["uploads"]] == [
        ("ps1/scph1001.bin", "uploaded")
    ]
    assert device.files[("bios", "ps1/scph1001.bin")] == file.path.read_bytes()


def test_a_local_folder_target_never_asks_the_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server = install_fake_smb(monkeypatch)
    folder = tmp_path / "sdcard"
    folder.mkdir()
    (folder / "missing_bios_report.txt").write_text(make_report_text([]), encoding="utf-8")

    assert cli.main(["--json", "report", "--target-dir", str(folder)]) == 0

    assert json.loads(capsys.readouterr().out)["missing_from"] == "report"
    assert server.api_calls == []


def test_a_report_file_never_asks_the_api(
    device: FakeSMBServer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    copy = tmp_path / "copy.txt"
    copy.write_text(make_report_text([]), encoding="utf-8")

    assert cli.main(["--json", "report", "--report-file", str(copy)]) == 0

    assert json.loads(capsys.readouterr().out)["missing_from"] == "report_file"
    assert device.api_calls == []


def test_no_answer_and_no_report_is_still_exit_4(
    device: FakeSMBServer, capsys: pytest.CaptureFixture[str]
) -> None:
    del device.files[("bios", "missing_bios_report.txt")]

    assert cli.main(["--json", "report"]) == 4

    assert json.loads(capsys.readouterr().out)["missing_from"] is None


# The real pair: a report and the API's answer, from the same 10.1.1 VM minutes apart


def test_the_api_gives_exactly_the_entries_of_the_report_taken_with_it() -> None:
    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    adapter = RecalboxAdapter()
    report = (fixtures / "reports" / "recalbox-10.1.1" / "web-api-pair.txt").read_bytes()
    api = (fixtures / "api" / "recalbox-10.1.1" / "web-api-pair.json").read_bytes()

    from_report = adapter.parse_report(report.decode("utf-8"))
    from_api, refused = adapter.parse_api(api)

    def described(entries: list[Any]) -> list[tuple[Any, ...]]:
        return sorted(
            (
                e.target.as_posix(),
                e.name,
                e.required,
                e.incorrect,
                e.current_md5,
                sorted(e.md5s),
                e.system,
            )
            for e in entries
        )

    assert len(from_api) == 80
    assert refused == adapter.rejected_entries(report.decode("utf-8")) == []
    assert described(from_api) == described(from_report)
