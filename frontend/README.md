# Picframe Frontend

This is the Vue 3 Single Page Application (SPA) for the Picframe project. It serves as the web control plane, providing a modern, responsive interface for controlling media playback and managing system configuration.

## Technology Stack

*   **Framework:** Vue 3 (Composition API, `<script setup>`)
*   **Build Tool:** Vite
*   **Language:** TypeScript
*   **Styling:** Tailwind CSS v4
*   **State Management:** Pinia
*   **Routing:** Vue Router
*   **Internationalization:** Vue I18n
*   **Icons:** Heroicons
*   **Maps:** Vue-Leaflet (OpenStreetMap integration)

## Project Structure

*   `src/assets/`: Static assets like images and global CSS.
*   `src/components/`: Reusable Vue components.
*   `src/locales/`: JSON translation files for i18n (e.g., `en.json`, `de.json`).
*   `src/router/`: Vue Router configuration.
*   `src/stores/`: Pinia state management stores (`player.ts`, `config.ts`).
*   `src/views/`: Main application views (`RemoteView.vue`, `SettingsView.vue`).
*   `src/App.vue`: Root component containing the main layout and navigation.
*   `src/main.ts`: Application entry point.

## Development Workflow

### Prerequisites

Ensure you have [Yarn](https://yarnpkg.com/) installed.

### Setup

1.  Navigate to the frontend directory:
    ```bash
    cd frontend
    ```
2.  Install dependencies:
    ```bash
    yarn install
    ```

### Running the Development Server

To start the Vite development server with Hot Module Replacement (HMR):

```bash
yarn dev
```

The application will be available at `http://localhost:5173` (or another port if 5173 is in use).

### Building for Production

To compile the application for production:

```bash
yarn build
```

This command performs the following actions:
1.  Runs `vue-tsc` to perform TypeScript type checking.
2.  Runs `vite build` to bundle the application.

**Important:** The `vite.config.ts` is configured to output the compiled static assets directly into the backend's static directory (`../src/picframe/html`). This allows the FastAPI backend to serve the SPA seamlessly. The output directory is automatically emptied before each build.

### Linting and Formatting

(Add instructions here if ESLint/Prettier are configured in the future)

## Integration with FastAPI

The frontend is designed to communicate with the FastAPI backend via:
*   **REST API:** For fetching and saving configuration (`/api/config`), and triggering system actions (`/api/system/*`).
*   **WebSockets:** For real-time state synchronization (`/ws/state`). The `player` store automatically connects to this WebSocket to receive updates about the current media, playback state, and system status.

When running in production, the FastAPI server serves the compiled `index.html` and associated assets from the `src/picframe/html` directory.
