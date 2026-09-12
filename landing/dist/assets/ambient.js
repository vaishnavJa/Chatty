const background = document.querySelector('.ambient video');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
background.loop = true;
background.playsInline = true;

function applyMotionPreference() {
  background.muted = true;
  if (reducedMotion.matches) background.pause();
  else background.play().catch(() => { /* Keep the poster when autoplay is unavailable. */ });
}

reducedMotion.addEventListener('change', applyMotionPreference);
window.addEventListener('pageshow', applyMotionPreference);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) applyMotionPreference();
});
applyMotionPreference();
