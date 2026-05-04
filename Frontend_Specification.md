# Frontend Specification: Picframe 2.0 (Vue.js SPA)

## 1. Executive Summary
This document outlines the frontend architecture and user interface specification for the Picframe 2.0 Single Page Application (SPA). Built with Vue.js 3, the SPA serves as the primary control plane for the digital picture frame, communicating with the FastAPI backend via REST APIs for configuration and WebSockets for real-time playback state.

## 2. Technology Stack
*   **Framework:** Vue.js 3 (Composition API, `<script setup>`)
*   **Build Tool:** Vite (for fast HMR and optimized production builds)
*   **State Management:** Pinia (replaces Vuex for modular, type-safe state)
*   **Routing:** Vue Router 4
*   **Styling:** Tailwind CSS (for responsive, utility-first design) + Headless UI components (e.g., modals, toggles)
*   **Map Integration:** Leaflet.js (`leaflet` and `@vue-leaflet/vue-leaflet`) for OpenStreetMap rendering.
*   **Network:** `axios` (REST API) and native browser `WebSocket` API.

## 3. Core Architecture & Data Flow

### 3.1 State Management (Pinia Stores)
*   **`usePlayerStore`:** Manages the WebSocket connection to `ws://<ip>/ws/state`. It holds the current `MediaItem` DTO, playback status (playing/paused), and current brightness. It automatically updates the UI when the backend broadcasts a `MediaChangedEvent` or `StateEvent`.
*   **`useConfigStore`:** Manages REST API interactions (`GET /api/config`, `PUT /api/config`) for the Administrative Dashboard.
*   **`useSystemStore`:** Handles maintenance operations and system state commands (Reboot, Shutdown).

### 3.2 Responsive Design Strategy
The UI follows a mobile-first approach. On mobile devices, the layout stacks vertically (Media Player on top, Metadata below). On desktop/tablet, it utilizes a multi-column grid (Media Player on the left, Metadata/Map on the right).

---

## 4. View 1: Media Player Interface ("The Remote")

This view acts as the real-time remote control and information display for the currently playing media.

### 4.1 Media Display & Playback Controls
*   **Current Media Preview:** A responsive image/video container displaying a low-resolution thumbnail or the actual image currently rendered on the Pi.
*   **Transport Controls:** A sticky or prominent control bar featuring:
    *   `Previous` (Skip to previous media)
    *   `Play/Pause` (Toggle playback state, icon changes dynamically based on WebSocket state)
    *   `Next` (Skip to next media)
*   **Display Brightness:** A horizontal slider component bound to the backend brightness state. Dragging the slider emits a `CommandEvent(SET_BRIGHTNESS)` via WebSocket or REST.

### 4.2 Metadata Panel
A dedicated panel surfacing the `MediaItem` DTO properties:
*   **File Info:** Filename, directory, resolution, file size, and media type.
*   **EXIF Data:** Camera Make/Model, Aperture, Shutter Speed, ISO, Focal Length, and original capture Date/Time.
*   **Caption/Tags:** Any associated IPTC tags or user-defined captions.

### 4.3 Dynamic OpenStreetMap Component

The `MapComponent` is a standalone Vue component responsible for rendering an interactive map using Leaflet.js (`@vue-leaflet/vue-leaflet`). It is a distinct UI element in the Remote UI, completely separate from the text overlay controls.

*   **Conditional Rendering:** The component is conditionally rendered *only* if the current `MediaItem` DTO contains valid `latitude` and `longitude` properties.
*   **Implementation:** Utilizes Leaflet.js to embed an interactive OpenStreetMap.
*   **Features:**
    *   Centers the map on the media's exact coordinates with a custom marker.
    *   Displays reverse-geocoded location text fetched from the metadata directly above the map.
*   **Separation of Concerns:** This component operates entirely independently of the backend pi3d rendering pipeline and text overlay features. It is a purely frontend UI element.

### 4.4 Text Overlay Controls
A dedicated panel (`TextOverlayControls.vue`) to manage text overlays on the currently playing media.
*   **Separation of Concerns:** These controls strictly toggle the text overlays within the backend pi3d render pipeline. They do not affect, hide, or toggle any text elements within the frontend UI itself.
*   **Configuration Payload:** All settings are collected and transmitted as a unified configuration payload using a `SET_CONFIG` command over the WebSocket connection.
    *   Example Payload: `{ "command": "SET_CONFIG", "payload": { "viewer": { "show_clock": true, "show_text": "title caption name date folder location" } } }`
*   **Helper Text System (`HelperText.vue`):** A generalized, reusable helper text system is implemented for all UI elements.
    *   **Presentation Format:** The UI dynamically decides the presentation format based on the length and complexity of the helper text.
        *   **Hover Tooltip:** Used for short, simple descriptions.
        *   **Circled "i" Icon:** Used for longer, more complex descriptions. Clicking the icon opens a pop-up dialog containing the helper text and a close button.
    *   **Internationalization:** All helper texts are defined in the language JSON files (e.g., `en.json`, `de.json`).

---

## 5. View 2: Administrative Dashboard ("Settings")

This view provides robust configuration and system management, protected by basic authentication if configured.

### 5.1 Configuration Management
A comprehensive form interface mapping to the `config.db3` schema.
*   **Sections:** Grouped logically (e.g., Directories, Playback Settings, MQTT, Display).
*   **Actions:**
    *   `Save Changes`: Sends a `PUT /api/config` request.
    *   `Export Configuration`: Triggers a download of the current configuration as a JSON or YAML file.
    *   `Import Configuration`: A file upload component that accepts a JSON/YAML file, parses it, and overwrites the current settings via `POST /api/config/import`.

### 5.2 Advanced Maintenance Operations
A dedicated "Danger Zone" or Maintenance tab for system-level operations. All actions here require a confirmation modal to prevent accidental clicks.
*   **Database Management:**
    *   `Purge Media Database`: Sends a command to drop all tables in `media_cache.db3` and triggers a full background rescan. Useful if the database is corrupted or out of sync.
*   **Cache Management:**
    *   `Clear Image Cache`: Deletes all pre-processed matting images and resized thumbnails from the disk cache, freeing up space.
*   **System Power States:**
    *   `Reboot System`: Sends a `CommandEvent(REBOOT)` to the `SystemManager`.
    *   `Shutdown System`: Sends a `CommandEvent(SHUTDOWN)` to the `SystemManager`.

## 6. API Integration Contract

### 6.1 WebSockets (`/ws/state`)
*   **Incoming (from Backend):** `{ "type": "MediaChangedEvent", "media": { "file_path": "...", "exif": {...}, "location": {"lat": 52.5, "lon": 13.4} } }`
*   **Outgoing (from UI):** `{ "command": "NEXT" }`, `{ "command": "PAUSE" }`, `{ "command": "SET_BRIGHTNESS", "value": 0.8 }`

### 6.2 REST Endpoints
*   `GET /api/config` -> Returns full configuration JSON.
*   `PUT /api/config` -> Updates configuration.
*   `POST /api/maintenance/purge-db` -> Triggers database rebuild.
*   `POST /api/maintenance/clear-cache` -> Clears image cache.
*   `POST /api/system/reboot` -> Reboots host OS.

## 7. UI/UX Design Principles & Consistency

To ensure a cohesive, professional, and highly polished user experience across the entire application, all frontend development must adhere to the following design principles:

### 7.1 Design Language & Styling
*   **Tailwind Utility-First:** All styling should be implemented using Tailwind CSS utility classes. Avoid custom CSS unless absolutely necessary (e.g., complex range slider thumb styling).
*   **Modern Aesthetics:** Utilize modern UI trends such as subtle glassmorphism (`backdrop-blur-xl`, `bg-white/90`), soft shadows (`shadow-xl`, `shadow-2xl`), and generous border radii (`rounded-2xl`, `rounded-3xl`) for card components.
*   **Color Palette:**
    *   Primary Actions: Indigo (`indigo-600` for buttons, `indigo-500` for hover states).
    *   Destructive Actions: Red (`red-600`).
    *   Warnings/Status: Amber (`amber-500`).
    *   Backgrounds: Soft grays (`gray-50` for light mode, `gray-900` for dark mode).
*   **Dark Mode Support:** All components must include explicit dark mode variants using Tailwind's `dark:` modifier to ensure accessibility and visual comfort in low-light environments.

### 7.2 Iconography Standardization
*   **Primary Set (Heroicons):** Use `@heroicons/vue` (Outline for standard UI elements, Solid for active states or primary transport controls) for all general navigation, layout, and control interface icons.
*   **Secondary Set (Material Design Icons):** Use `@mdi/js` strictly for specialized data representation (e.g., specific EXIF metadata fields like Aperture, Focal Length) where Heroicons lacks the necessary technical metaphors.
*   **Consistent Rendering:** When mixing icon sets, ensure consistent sizing (e.g., `w-5 h-5`), alignment, and color application (`text-gray-400 group-hover:text-indigo-500`). MDI SVG paths should be wrapped in a standard `<svg>` tag matching the Heroicon dimensions.

### 7.3 Localization (i18n) Synchronization
*   **Comprehensive Coverage:** Hardcoded text strings are strictly prohibited in Vue templates. All user-facing text must be routed through `vue-i18n` (`$t()` or `t()`).
*   **File Synchronization:** Any key added to `en.json` must be simultaneously added to `de.json` (and any other supported languages) with an accurate translation.
*   **Logical Grouping:** Translation keys must be hierarchically structured by view and component (e.g., `remote.metadata.exposureTime`, `settings.sections.viewer`).

### 7.4 Empty States & Graceful Degradation
*   **Conditional Rendering:** UI elements representing data (like metadata rows) should only render if the underlying data is valid and present. Avoid displaying "N/A", "null", or "Unknown".
*   **Polished Fallbacks:** When primary content is missing (e.g., no media playing, no metadata available), display a visually distinct empty state featuring a muted icon, a clear descriptive message, and a soft background to maintain layout integrity.