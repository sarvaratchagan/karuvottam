# T9.5 — Installable mobile web app

The public Tamil pages can be installed from a supporting browser as a standalone web app. The app remains a responsive website on browsers that do not offer installation. A manifest identifies the app and ships 192/512 px PNG icons; an Apple touch icon is also included. The service worker is served from `/service-worker.js` with root scope and registered only on public pages.

## Install

Deploy over HTTPS and open the site on a phone. Use the browser's **Install app** or **Add to Home Screen** action. Local development on `localhost` also supports service workers in browsers that treat it as a secure context. The manifest and worker are available at `/manifest.webmanifest` and `/service-worker.js`. Rebuild icons after changing `scripts/build_pwa_icons.py` with `python scripts/build_pwa_icons.py` (Pillow is needed only to regenerate the checked-in PNG assets).

## Offline behavior

The worker pre-caches only the offline page, stylesheet, and app icons. Public navigation to `/`, `/calendar`, `/prediction`, `/observations`, `/events`, or `/climate` always attempts a fresh network request without HTTP cache. If the network fails, it displays a clearly labelled Tamil offline page with a retry link. It does **not** cache forecasts, observations, event data, CSV exports, API responses, or account/admin pages. It cannot collect observations or issue weather alerts offline. A server error while online remains a server error, rather than being disguised as an offline response.

The interface uses the viewport meta tag, responsive forecast/observation cards, scrollable wide tables, 44 px controls, and a narrower layout for small phones. The installation shell adds no browser permission request and no background sync.

## Verify on a deployment

1. On a phone over HTTPS, open `/` and install the app from the browser menu. Confirm the Tamil title and icon.
2. Open `/prediction` and `/observations` at a narrow screen width; inspect the cards, controls, focus outline, and horizontal scrolling for other wide tables.
3. Return to `/`, then disconnect the network and navigate to a public page. Confirm the offline page appears and makes no forecast claim. Reconnect and use **மீண்டும் முயற்சி செய்**.
4. While offline, visit `/admin` or `/workspace`; confirm no protected content is served from the worker cache. A browser network error is expected there.
5. After a release changes shell assets, increment `SHELL_CACHE` in `static/service-worker.js`; the new worker deletes old shell caches on activation.

Automated tests verify the manifest, icon dimensions, public-page links, worker response, and offline-shell policy. Service-worker installation and phone-specific browser UI should still be checked on a real device. See [Chrome's manifest guidance](https://developer.chrome.com/docs/lighthouse/pwa/installable-manifest), [MDN's service-worker guide](https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API/Using_Service_Workers), and [MDN's secure-context guidance](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Secure_Contexts).
