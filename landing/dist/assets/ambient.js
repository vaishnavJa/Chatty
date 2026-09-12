const background = document.querySelector('.ambient video');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
const toggle = document.querySelector('.motion-toggle');

function updateToggle() {
  toggle.textContent = background.paused ? 'Play ▷' : 'Pause Ⅱ';
  toggle.setAttribute('aria-label', background.paused ? 'Play introduction' : 'Pause introduction');
}

function applyMotionPreference() {
  background.muted = true;
  if (reducedMotion.matches) background.pause();
  else background.play().catch(updateToggle);
  updateToggle();
}

background.addEventListener('play', updateToggle);
background.addEventListener('pause', updateToggle);
toggle.addEventListener('click', () => {
  if (background.paused) background.play().catch(updateToggle);
  else background.pause();
});
reducedMotion.addEventListener('change', applyMotionPreference);
applyMotionPreference();
