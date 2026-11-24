import httpx
import respx
from sqlalchemy import select

from framelink_registry.database import AsyncSessionLocal
from framelink_registry.main import app
from framelink_registry.jobs import refresh_all_calendars
from framelink_registry.models import CalendarSource

from .test_ics import ics

URL = "webcal://p01.example.com/secret-token"
HTTPS = "https://p01.example.com/secret-token"
FAR = "from=2026-01-01&to=2026-12-31"


def feed(*events: str) -> httpx.Response:
    return httpx.Response(200, content=ics(*events))


def day(d: str, title: str, uid: str | None = None, extra: str = "") -> str:
    return f"UID:{uid or title}\nDTSTART;VALUE=DATE:{d}\n{extra}\nSUMMARY:{title}"


async def add(client, url=URL, **body):
    return await client.post("/api/calendar/sources", json={"name": "Familie", "url": url, **body})


# --- auth / validation -------------------------------------------------------

async def test_auth_required(client):
    assert (await client.get("/api/calendar/sources", headers={"X-API-Key": "wrong"})).status_code == 401
    assert (await client.get(f"/api/calendar/entries?ids=a&{FAR}", headers={"X-API-Key": "wrong"})).status_code == 401
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as anon:
        # missing header: 422 (same behaviour as the albums router)
        assert (await anon.get(f"/api/calendar/entries?ids=a&{FAR}")).status_code == 422


async def test_entries_param_validation(client):
    assert (await client.get("/api/calendar/entries?from=2026-01-01&to=2026-12-31")).status_code == 422  # ids missing
    assert (await client.get(f"/api/calendar/entries?ids=&{FAR}")).status_code == 422  # empty ids
    assert (await client.get("/api/calendar/entries?ids=a&from=2026-01-01")).status_code == 422
    assert (await client.get("/api/calendar/entries?ids=a&from=nope&to=2026-01-02")).status_code == 422
    assert (await client.get("/api/calendar/entries?ids=a&from=2026-02-01&to=2026-01-01")).status_code == 422
    assert (await client.get("/api/calendar/entries?ids=a&from=2026-01-01&to=2027-02-06")).status_code == 422  # 401 days
    assert (await client.get("/api/calendar/entries?ids=a&from=2026-01-01&to=2027-02-05")).status_code == 200  # exactly 400


async def test_unknown_ids_ignored(client):
    r = await client.get(f"/api/calendar/entries?ids=nope,also-nope&{FAR}")
    assert r.status_code == 200
    assert r.json()["calendars"] == [] and r.json()["entries"] == []


# --- CRUD ---------------------------------------------------------------------

@respx.mock
async def test_crud_and_url_never_leaks(client):
    respx.get(HTTPS).mock(return_value=feed(day("20261121", "Test")))
    r = await add(client, color="#ff0000", kind="holiday")
    assert r.status_code == 201
    src = r.json()
    assert src["url_host"] == "p01.example.com" and src["kind"] == "holiday" and src["last_ok"]
    assert "url" not in src

    assert (await add(client)).status_code == 409                      # duplicate (webcal == https)
    assert (await add(client, url=HTTPS)).status_code == 409

    listing = (await client.get("/api/calendar/sources")).json()
    assert [s["id"] for s in listing] == [src["id"]]
    assert "secret-token" not in (await client.get("/api/calendar/sources")).text

    r = await client.patch(f"/api/calendar/sources/{src['id']}", json={"name": "Neu", "color": None, "kind": "auto"})
    assert r.status_code == 200 and r.json()["name"] == "Neu" and r.json()["color"] is None
    assert "secret-token" not in r.text
    assert (await client.patch(f"/api/calendar/sources/{src['id']}", json={"color": "red"})).status_code == 422
    assert (await client.patch("/api/calendar/sources/nope", json={"name": "x"})).status_code == 404

    assert (await client.delete(f"/api/calendar/sources/{src['id']}")).status_code == 204
    assert (await client.delete(f"/api/calendar/sources/{src['id']}")).status_code == 404
    assert (await client.get("/api/calendar/sources")).json() == []


@respx.mock
async def test_post_rejections(client):
    for body in (
        {"name": "x", "url": "file:///etc/passwd"},
        {"name": "x", "url": "ftp://h/x.ics"},
        {"name": "", "url": URL},
        {"name": "x", "url": URL, "kind": "bogus"},
        {"name": "x", "url": URL, "color": "#12"},
    ):
        assert (await client.post("/api/calendar/sources", json=body)).status_code == 422, body

    respx.get(HTTPS).mock(return_value=httpx.Response(404))
    assert (await add(client)).status_code == 502
    respx.get(HTTPS).mock(return_value=httpx.Response(200, content=b"<html>not ics</html>"))
    assert (await add(client)).status_code == 502
    respx.get(HTTPS).mock(return_value=httpx.Response(200, content=b"x" * (5 * 1024 * 1024 + 1)))
    assert (await add(client)).status_code == 502
    assert (await client.get("/api/calendar/sources")).json() == []  # nothing persisted


# --- entries ------------------------------------------------------------------

@respx.mock
async def test_entries_contract_sort_alias_and_classification(client):
    respx.get(HTTPS).mock(return_value=feed(
        "UID:t\nDTSTART;TZID=Europe/Berlin:20261125T100000\nDTEND;TZID=Europe/Berlin:20261125T110000\nSUMMARY:Zahnarzt",
        day("20261125", "Opa Geburtstag"),
        day("20261125", "Aaa Termin"),
        day("20261123", "Urlaub", extra="DTEND;VALUE=DATE:20261126"),
        day("20260101", "Jubiläum", extra="RRULE:FREQ=YEARLY"),
    ))
    cal = (await add(client, color="#00ff00")).json()
    other = {"name": "Feiertage", "url": "https://other.example.com/h.ics", "kind": "holiday"}
    respx.get("https://other.example.com/h.ics").mock(return_value=feed(day("20261125", "Feiertag")))
    hol = (await client.post("/api/calendar/sources", json=other)).json()

    r = await client.get(f"/api/calendar/entries?from=2026-11-20&to=2026-11-30&ids={cal['id']},{hol['id']}")
    assert r.status_code == 200
    j = r.json()
    assert (j["from"], j["to"], j["tz"]) == ("2026-11-20", "2026-11-30", "Europe/Berlin")
    assert j["generated_at"]
    assert {c["id"] for c in j["calendars"]} == {cal["id"], hol["id"]}
    assert j["calendars"][0].keys() == {"id", "name", "kind", "color", "last_ok", "error"}

    got = [(e["start"], e["kind"], e["title"]) for e in j["entries"]]
    assert got == [  # (start, kind, title); kind order: holiday, birthday, appointment, ... vacation
        ("2026-11-23", "vacation", "Urlaub"),
        ("2026-11-25", "holiday", "Feiertag"),
        ("2026-11-25", "birthday", "Opa Geburtstag"),
        ("2026-11-25", "appointment", "Aaa Termin"),
        ("2026-11-25", "appointment", "Zahnarzt"),
    ]
    urlaub = j["entries"][0]
    assert (urlaub["end"], urlaub["all_day"], urlaub["color"], urlaub["cal"]) == ("2026-11-25", True, "#00ff00", cal["id"])
    zahn = j["entries"][-1]
    assert (zahn["time"], zahn["end_time"], zahn["all_day"]) == ("10:00", "11:00", False)
    assert set(zahn) == {"id", "cal", "title", "kind", "start", "end", "all_day", "time", "end_time", "color"}

    # only the requested range and ids; kind is re-classified without refetching
    r = await client.get(f"/api/calendar/entries?from=2026-11-24&to=2026-11-24&ids={cal['id']}")
    assert [e["title"] for e in r.json()["entries"]] == ["Urlaub"]
    await client.patch(f"/api/calendar/sources/{cal['id']}", json={"kind": "observance"})
    r = await client.get(f"/api/calendar/entries?from=2026-11-24&to=2026-11-24&ids={cal['id']}")
    assert r.json()["entries"][0]["kind"] == "observance"


# --- refresh ------------------------------------------------------------------

@respx.mock
async def test_failed_refresh_keeps_old_entries(client):
    route = respx.get(HTTPS).mock(return_value=feed(day("20261125", "Bleibt")))
    src = (await add(client)).json()

    route.mock(return_value=httpx.Response(500))
    r = await client.post(f"/api/calendar/sources/{src['id']}/refresh")
    assert r.status_code == 502

    j = (await client.get(f"/api/calendar/entries?ids={src['id']}&{FAR}")).json()
    assert [e["title"] for e in j["entries"]] == ["Bleibt"]
    assert j["calendars"][0]["error"] == "HTTP 500" and j["calendars"][0]["last_ok"]

    route.mock(return_value=feed(day("20261125", "Neu")))
    assert (await client.post(f"/api/calendar/sources/{src['id']}/refresh")).status_code == 200
    j = (await client.get(f"/api/calendar/entries?ids={src['id']}&{FAR}")).json()
    assert [e["title"] for e in j["entries"]] == ["Neu"] and j["calendars"][0]["error"] is None

    assert (await client.post("/api/calendar/sources/nope/refresh")).status_code == 404


@respx.mock
async def test_refresh_all_isolates_failures(client):
    respx.get(HTTPS).mock(return_value=feed(day("20261125", "A")))
    respx.get("https://b.example.com/b.ics").mock(return_value=feed(day("20261125", "B")))
    await add(client)
    await client.post("/api/calendar/sources", json={"name": "B", "url": "https://b.example.com/b.ics"})

    respx.get(HTTPS).mock(return_value=httpx.Response(503))
    respx.get("https://b.example.com/b.ics").mock(return_value=feed(day("20261125", "B2")))
    assert await refresh_all_calendars() == (1, 1)
    r = await client.post("/api/calendar/refresh")
    assert r.json() == {"updated": 1, "failed": 1}

    async with AsyncSessionLocal() as db:
        rows = {s.name: s for s in await db.scalars(select(CalendarSource))}
    assert rows["Familie"].last_error == "HTTP 503" and rows["Familie"].entries[0]["title"] == "A"
    assert rows["B"].last_error is None and rows["B"].entries[0]["title"] == "B2"
