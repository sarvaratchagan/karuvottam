try {
  localStorage.setItem('karuvottam-language',
    document.documentElement.lang === 'en' ? 'en' : 'ta');
} catch (_) {
  // The server-side language preference still works without local storage.
}
