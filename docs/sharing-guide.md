# Sharing Photos with Framelink

This guide explains how to add your iCloud albums to the photo frame.

> **Important:** Framelink uses iCloud **Shared Albums** with the **Public Website** option enabled. This is different from the standard sharing invitation link.
>
> | Link type | URL format | Compatible? |
> |---|---|---|
> | Public Website | `www.icloud.com/photos/#A…` or `#B…` | **Yes** |
> | Invitation link (Share button) | `share.icloud.com/photos/…` | No — requires Apple ID login |

---

## iOS

### Step 1 — Enable Public Website on your album

1. Open the **Photos** app
2. Go to **Albums** → tap your Shared Album
3. Tap the **People** icon (top right)
4. Scroll down and enable **Public Website**
5. Tap **Share Link** under "Public Website"
6. You'll see a link starting with `www.icloud.com/photos/#…` — this is the URL Framelink needs

### Step 2 — Set up the iOS Shortcut (one time)

1. Open the **Shortcuts** app
2. Tap **+** to create a new shortcut
3. Add the action **"Receive input from Share Sheet"** → set type to **URLs**
4. Add the action **"Get Contents of URL"**:
   - URL: `https://<your-registry-host>/api/albums`
   - Method: **POST**
   - Headers: add `X-API-Key` → `<your-api-key>`
   - Request body: **JSON** → add key `url`, value: **Shortcut Input**
5. Name the shortcut **"Add to Framelink"**
6. Tap the shortcut icon → **Share** → send it to other family members via iMessage

### Step 3 — Add an album (every new album)

1. Open the album in the Photos app
2. Enable **Public Website** (see Step 1)
3. Tap **Share Link** → select **"Add to Framelink"**

Done. The frame will pick up the new album on its next sync.

---

## Android

Android cannot natively access iCloud albums. There are two options:

### Option A — Use iCloud.com in a browser

1. Open [icloud.com](https://www.icloud.com) in Chrome on your Android phone
2. Sign in with your Apple ID
3. Go to **Photos** → find your Shared Album
4. Tap the **People** icon → enable **Public Website**
5. Copy the `www.icloud.com/photos/#…` link
6. Send it to Framelink manually via the HTTP shortcut below

### Option B — HTTP Shortcut app (one-time setup)

Install [HTTP Shortcuts](https://play.google.com/store/apps/details?id=ch.rmy.android.http_shortcuts) from the Play Store:

1. Create a new shortcut:
   - Method: **POST**
   - URL: `https://<your-registry-host>/api/albums`
   - Header: `X-API-Key: <your-api-key>`
   - Request body (JSON): `{"url": "{text_input}"}`
   - Input: **"Ask for text input before executing"**
2. Name it **"Add to Framelink"**
3. To add an album: get the `www.icloud.com/photos/#…` URL, run the shortcut, paste the URL

---

## Troubleshooting

**Album was added but photos don't appear on the frame**
- The frame syncs every ~2 hours. Wait or trigger a manual sync in the web UI under **System**.

**I only see a `share.icloud.com/…` link**
- That's an invitation link, not a public website link. Go back to **People** in the album and look for the **Public Website** toggle — it must be turned on separately.

**The album shows in the web UI but is disabled**
- Open the web UI at `http://frame.local:5000` → **Albums** tab → toggle the album on.
