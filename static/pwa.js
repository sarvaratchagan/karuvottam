// Installation is a progressive enhancement on HTTPS and localhost.
if ('serviceWorker' in navigator && window.isSecureContext) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/service-worker.js', { scope: '/' }).catch(() => {
      // The ordinary online site remains usable when registration fails.
    });
  });
}
