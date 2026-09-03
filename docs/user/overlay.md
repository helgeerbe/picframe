# Touch Overlay & Plugins

Picframe can render a transparent HTML overlay on top of your photos and
videos, driven by **WebKitGTK** and a small **plugin system**. The overlay lets
you control playback with touch, mouse, or keyboard, and display widgets such
as a clock, weather, or the current photo's metadata and GPS map.

This is a frame-local feature (issue #739). The overlay is **off by default**
and is only relevant on a Raspberry Pi / Wayland display session. It degrades
gracefully: if WebKitGTK is not installed, picframe runs unchanged without the
overlay.

## Enabling the overlay

1. Open the web UI (the SPA served by picframe).
2. Go to **Settings**, enable `overlay.enabled`, and save.
   (Or set `overlay.enabled: true` and run `picframe init`.)
3. Make sure the built-in plugins are present in `~/.picframe/overlay-plugins/`
   — `picframe init` copies them there (see *Plugin directory & updates*
   below).
4. Restart picframe (`picframe run`).

When WebKitGTK is available the overlay appears over the photo/video. When it
is not, picframe logs a `webkit_unavailable` system error and continues.

## Overlay settings

Configured from the **Appearance** tab (or the `overlay` config section):

| Setting | Values | Meaning |
|---|---|---|
| `overlay.enabled` | `true` / `false` | Master on/off. |
| `overlay.display_mode` | `auto_hide` / `persistent` | `auto_hide` fades the overlay to transparent after inactivity; `persistent` keeps it visible until you turn it off. |
| `overlay.auto_hide_seconds` | seconds | Inactivity before auto-hide (auto_hide mode only). |
| `overlay.idle_hide_seconds` | seconds | Seconds idle before the overlay fades to transparent (same for photos and videos). |
| `overlay.enabled_input_types` | `touch`, `mouse`, `keyboard` | Which device classes are active. Uncheck one to disable it (e.g. touch on a kiosk). |
| `overlay.transparent` | `true` / `false` | Whether the surface is transparent (recommended). |
| `overlay.visible_plugin` | plugin id or `null` | Which plugin is currently expanded; `null` = dock only. |
| `overlay.enabled_plugins` | list of ids | Which plugins are loaded/active. |
| `overlay.plugin_dir` | path | Directory scanned for plugin sub-directories. |

Any wake event (pointer move, tap, key press, touch) raises the overlay back to
full opacity; after the idle interval it fades to transparent again. The
overlay is **always on top and always the input surface** — "transparent" does
not mean "off", so a tap always brings it back.

### Navigation

The whole overlay area captures input and routes it as playback commands:

- **Left third** → previous photo/video
- **Right third** → next photo/video
- **Center** → play/pause (toggle)
- **Esc** → hide (toggle playback stop)

Mouse, touch, and pen all go through the same Pointer Events path, so the
overlay works identically once a touchscreen is connected.

## Built-in plugins

Three plugins ship with picframe and are copied to
`~/.picframe/overlay-plugins/` by `picframe init`. Enable/disable them from the
**Remote** tab (Touch overlay panel) and configure each plugin's options inline.

### Clock

An analog or digital clock with optional date.

| Option | Type | Default | Notes |
|---|---|---|---|
| `style` | enum `digital`/`analog` | `digital` | Digital text clock or analog clock face. |
| `clock_format` | enum `12h`/`24h` | `24h` | 12-hour (AM/PM) or 24-hour. |
| `show_seconds` | boolean | `false` | Display a seconds indicator (updates every second). |
| `show_date` | boolean | `true` | Display the current date below the time. |

### Weather

Current weather from OpenWeatherMap One Call 3.0. **Requires a network
connection** and an API key.

| Option | Type | Default | Notes |
|---|---|---|---|
| `api_key` | string *(required)* | — | A One Call API 3.0 key from openweathermap.org. |
| `lat` | number *(required)* | — | Decimal degrees, e.g. `52.52`. |
| `lon` | number *(required)* | — | Decimal degrees, e.g. `13.405`. |
| `units` | enum `metric`/`imperial` | `metric` | metric = °C / m/s, imperial = °F / mph. |
| `language` | string | `en` | OpenWeatherMap language code, e.g. `en`, `de`. |
| `refresh_seconds` | integer | `600` | How often to re-fetch weather data. |

### Photo Info (meta)

Shows the current photo's EXIF metadata and a Leaflet map at the photo's GPS
coordinates. It updates automatically whenever the photo changes. The map uses
Leaflet from a CDN with an offline text-coordinate fallback; tap the map to
expand it fullscreen.

| Option | Type | Default | Notes |
|---|---|---|---|
| `show_map` | boolean | `true` | Render a Leaflet map when GPS coordinates are present. |
| `map_zoom` | integer | `13` | Leaflet zoom level (1–19). |
| `show_exif` | boolean | `true` | Display camera/lens/exposure metadata. |
| `date_format` | string | `YYYY-MM-DD HH:mm` | moment-style token format for the capture date. |

## Managing plugins from the web UI

- **Remote → Touch overlay** lists discovered plugins with an enable/disable
  toggle and a "visible plugin" selector ("Dock only" means no plugin is
  expanded — only the icon dock shows). Each enabled plugin exposes its config
  form, rendered from the plugin's `config_schema` (toggles, number fields,
  selects, text inputs). Saving applies the change live (no restart needed).
- **Appearance → Overlay** controls display mode, idle/auto-hide timing,
  enabled input types, and transparency.

Plugin settings persist in `config.db3`; plugin code is stateless, so you can
update a plugin's HTML without losing your config.

## Plugin directory & updates

- Plugins live as sub-directories of `overlay.plugin_dir`
  (`~/.picframe/overlay-plugins/` by default). Each sub-directory needs a
  `plugin.json` manifest and an HTML entry (default `index.html`).
- `picframe init` copies the **built-in** plugins there and **force-overwrites
  built-in dirs** on every init so manifest/code updates propagate. **Your
  own plugin directories are never touched.**
- Per-plugin user config is stored in `config.db3` under
  `overlay.plugin_config.<id>.*`, never inside the plugin directory — so
  replacing a plugin's files never loses your settings.

## Create your own plugin

A plugin is just a folder under `~/.picframe/overlay-plugins/` containing a
`plugin.json` manifest and an HTML file. It is loaded into an iframe and talks
to picframe through `postMessage`. No build step is required — plain HTML, CSS,
and JavaScript.

### 1. Create the plugin directory

```sh
mkdir -p ~/.picframe/overlay-plugins/hello
```

### 2. Write the manifest (`plugin.json`)

```json
{
  "id": "hello",
  "name": "Hello",
  "description": "A minimal example plugin.",
  "icon": "👋",
  "trigger": "icon",
  "position": "top-right",
  "size": { "w": 300, "h": 160 },
  "config_schema": {
    "greeting": {
      "type": "string",
      "default": "Hello, world!",
      "label": "Greeting",
      "help": "Text shown in the plugin."
    },
    "bold": {
      "type": "boolean",
      "default": true,
      "label": "Bold",
      "help": "Render the greeting in bold."
    }
  }
}
```

Manifest fields:

| Field | Required | Description |
|---|---|---|
| `id` | no (defaults to directory name) | Stable plugin identifier. |
| `name` | no | Human-readable display name shown in the web UI. |
| `description` | no | Short description shown in the web UI. |
| `icon` | no | Emoji or short label for the dock icon. |
| `trigger` | no | How the plugin is activated; `"icon"` = dock icon tap (the only supported value). |
| `position` | no | Default screen position, e.g. `"top-right"`. |
| `size` | no | `{"w": int, "h": int}` preferred size in pixels. |
| `requires` | no | Informational capability list, e.g. `["network"]`, `["map"]`. |
| `config_schema` | no | Per-plugin user configuration form (see below). |
| `entry` | no | HTML entry file relative to the plugin directory (default `index.html`). |

### 3. `config_schema` field definitions

Each key in `config_schema` is a field the web UI renders as an input and that
picframe validates before saving. A field definition is an object with:

| Property | Applies to | Description |
|---|---|---|
| `type` | all | One of `string`, `integer`, `number`, `boolean`. Defaults to `string`. |
| `default` | all | Default value (used when the user has not set one). |
| `required` | all | If `true`, the field must have a value (no default fallback). |
| `enum` | `string` | Restrict the value to one of the listed strings (rendered as a select). |
| `label` | all | Human-readable label shown in the web UI. |
| `help` | all | Helper text shown under the field. |

Validation rules: unknown keys are rejected, `required` fields must be present,
declared types are enforced (`integer`/`number` reject booleans), and `enum`
values are checked. Invalid saves return a 422 error.

### 4. Write the entry HTML (`index.html`)

The plugin receives its effective config (manifest defaults ← user overrides)
and, if it is the visible plugin, the current media, via `postMessage`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Hello</title>
  <style>
    body { margin: 0; font-family: system-ui, sans-serif; color: #fff;
           background: rgba(15,23,42,0.78); padding: 1rem; }
    #greeting { font-size: 1.4rem; }
    #media { margin-top: .5rem; opacity: .8; font-size: .85rem; }
  </style>
</head>
<body>
  <div id="greeting">Hello, world!</div>
  <div id="media"></div>
  <script>
    var cfg = { greeting: "Hello, world!", bold: true };
    function render() {
      var el = document.getElementById("greeting");
      el.textContent = cfg.greeting;
      el.style.fontWeight = cfg.bold ? "700" : "400";
    }
    window.addEventListener("message", function (event) {
      var msg = event.data || {};
      if (msg.type === "picframe:config" && msg.config) {
        Object.keys(cfg).forEach(function (k) {
          if (msg.config[k] !== undefined) cfg[k] = msg.config[k];
        });
        render();
      } else if (msg.type === "picframe:media" && msg.media) {
        document.getElementById("media").textContent =
          msg.media.file_path || "";
      }
    });
    render();
  </script>
</body>
</html>
```

### 5. The `postMessage` protocol

Picframe sends messages to the active plugin's iframe via `window.postMessage`.
Listen for `message` events and check `event.data.type`:

| `type` | Payload | When sent |
|---|---|---|
| `picframe:config` | `{ pluginId, config }` | On iframe load and whenever the plugin's effective config changes. `config` is the merged (defaults ← user overrides) object. |
| `picframe:media` | `{ media }` | Whenever the current photo/video changes (only if the plugin is the visible plugin). `media` is a `CurrentMedia` object. |

`CurrentMedia` shape:

```ts
{
  file_path: string,        // path/URL of the current media
  media_type?: string,      // "image" | "video"
  location?: { lat: number, lon: number } | null,  // GPS coords, if present
  exif?: Record<string, any>                       // open-ended EXIF metadata
}
```

Plugins are sandboxed in iframes loaded over `file://`. They do **not** need
their own WebSocket client — the shell forwards media for them. If your plugin
needs network access (like `weather`), it can `fetch()` directly from its own
origin; note `requires: ["network"]` is informational only.

### 6. Reload and use

After adding the plugin, trigger a reload so picframe re-scans the plugin
directory (the web UI does this automatically when you change overlay settings;
or run `picframe init` / restart). Your plugin appears in **Remote → Touch
overlay**, where you can enable it, make it the visible plugin, and edit its
config.

## Troubleshooting

- **Overlay does not appear.** Ensure `overlay.enabled` is on and WebKitGTK is
  installed. The installer installs the WebKitGTK packages by default
  (`gir1.2-webkit-6.0` and `gir1.2-gtk4layershell-1.0`); if you used `--disable-overlay`
  or are on an older OS release that lacks them, add them manually:

  ```bash
  sudo apt install gir1.2-webkit-6.0 gir1.2-gtk4layershell-1.0
  ```

  The renderer probes the GTK4 typelib (`WebKit 6.0`) first, then the GTK3
  fallback (`WebKit2 4.1`). If WebKitGTK is absent, picframe logs a
  `webkit_unavailable` system error and continues without the overlay.
- **Built-in plugins missing.** Run `picframe init` to copy them to
  `~/.picframe/overlay-plugins/`.
- **Plugin not listed.** Check that the directory contains a valid
  `plugin.json`. Malformed manifests are skipped with a warning in the picframe
  log; one bad plugin never breaks discovery of the others.
- **Config save rejected (422).** A field value failed validation against the
  plugin's `config_schema` (wrong type, unknown key, missing required field, or
  value outside `enum`). The web UI shows the validation error inline.
- **Video shows through a fully opaque overlay.** That is expected: during
  video playback the overlay fades to opacity 0 so the video is visible, but it
  stays on top and keeps capturing input — tap anywhere to bring it back.
