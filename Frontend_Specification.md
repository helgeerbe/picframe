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
*   **Trigger:** Conditionally rendered *only* if the current `MediaItem` DTO contains valid `latitude` and `longitude` properties.
*   **Implementation:** Uses Leaflet.js to embed an interactive OpenStreetMap.
*   **Features:** 
    *   Centers the map on the media's coordinates.
    *   Places a custom marker at the exact location.
    *   Displays reverse-geocoded location text (e.g., "Berlin, Germany") fetched from the metadata above the map.

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