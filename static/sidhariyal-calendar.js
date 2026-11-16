// Reveal one day's timing details without making hidden controls focusable.
document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-sid-open], [data-sid-close]');
  if (!button) return;
  const card = button.closest('.sid-calendar-day');
  if (!card) return;
  const front = card.querySelector('[data-sid-front]');
  const back = card.querySelector('[data-sid-back]');
  const opener = card.querySelector('[data-sid-open]');
  if (!front || !back || !opener) return;

  const showDetails = button.hasAttribute('data-sid-open');
  front.hidden = showDetails;
  back.hidden = !showDetails;
  opener.setAttribute('aria-expanded', String(showDetails));
  card.classList.toggle('is-flipped', showDetails);
  (showDetails ? card.querySelector('[data-sid-close]') : opener).focus();
});
