try {
  if (localStorage.getItem('karuvottam-language') === 'en') {
    document.documentElement.lang = 'en';
    document.title = 'Offline • Karuvottam';
    document.querySelectorAll('[data-en]').forEach((element) => {
      element.textContent = element.dataset.en;
    });
  }
} catch (_) {
  // The Tamil offline page remains usable if storage is unavailable.
}
