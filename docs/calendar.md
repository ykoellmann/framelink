# Calendar sidebar

Framelink can show a sidebar (25 % of the screen, right) with today's date and a timeline of the next 2-4 weeks. Appointments come from public calendar feeds (ICS / `webcal://`), for example shared iCloud calendars. Several calendars can be combined, and each frame chooses its own.

The registry (home server) fetches the feeds every 30 minutes and parses them. The frame only downloads a small JSON from the registry. The sidebar is off by default.

## Share an iCloud calendar publicly

On iPhone / iPad:

1. Open **Calendar**, tap **Calendars** at the bottom.
2. Tap the **ⓘ** next to the calendar.
3. Switch on **Public Calendar**.
4. Tap **Share Link…** and copy the address. It starts with `webcal://`.

On a Mac: right-click the calendar in the sidebar of the Calendar app → **Share Calendar…** → **Public Calendar** → copy the link.

> **Keep the address private.** Everyone who knows the link can read the calendar. The registry never shows the address again after you add it, only its host name.

## Add it to Framelink

Web UI (`http://frame.local:5000`) → **Kalender** → **Kalender hinzufügen**: enter a name, paste the `webcal://` address and pick the type. The registry fetches the address once to check it; an unreachable or invalid address is rejected. Then switch the calendar on in the list and switch **Kalender anzeigen** on.

A calendar belongs to the registry, so it is visible on all frames; deleting it removes it for all frames. Which calendars one frame shows is saved on that frame.

## Types

| Type | Meaning |
|---|---|
| Automatic | All-day entries over several days become vacation, yearly or "Geburtstag" entries become birthdays, everything else is an appointment |
| Appointments | Normal appointments |
| Birthdays | Birthdays |
| Holidays | Public holidays (red day number) |
| Observances | Memorial days etc. |
| Vacation | Spans shown as colored bars and pills |
| School holidays | Spans, tinted background |

Holidays and school holidays are ordinary calendar sources, too: add the public ICS feed of your state and choose the matching type.

## Birthdays

The automatic **Birthdays** calendar of iCloud cannot be shared publicly as far as we know. Instead, create the birthdays as **yearly repeating all-day events** in a normal calendar, share that calendar and set the type to *Birthdays*.

## Time zone

Timed entries are converted to the registry's time zone (`FRAMELINK_TIMEZONE`, default `Europe/Berlin`) and shown on their start day. The frame decides "today" with `calendar.timezone` in its config (the Pi often runs on UTC). Both values should be the same.

## Rollout order

1. Update the **registry** first (`docker compose pull && docker compose up -d`; the migration runs at start). Add a calendar and check `GET /api/calendar/entries?from=…&to=…&ids=…` with your API key.
2. Then update each **frame** with `sudo framelink-update` (see *Upgrading* in the README; it enables `framelink-calendar.timer` when the photo sync timer is enabled), and switch the sidebar on in the web UI.

Rollback: `calendar.enabled: false` on the frame, or `alembic downgrade 0001` on the registry. A new frame with an old registry (no calendar endpoint) shows only the date header.

## Troubleshooting

- **Calendar shows an error in the list:** the feed could not be fetched; old entries stay until the next successful run.
- **Nothing appears on the frame:** check `systemctl status framelink-calendar.timer` and `journalctl -u framelink-calendar`, and that calendars are selected in the web UI.
- **Wrong day around midnight:** the time zones differ, see above.
