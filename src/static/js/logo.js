function sarvamMarkSVG(color) {
  color = color || "#2b2b2b";
  const cx = 50, cy = 50, petals = 10;
  let paths = "";
  for (let i = 0; i < petals; i++) {
    const angle = (360 / petals) * i;
    paths += `<path d="M50 50 Q38 28 50 6 Q62 28 50 50 Z" fill="none" stroke="${color}" stroke-width="1.7" transform="rotate(${angle} ${cx} ${cy})" />`;
  }
  return (
    `<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">` +
    paths +
    `<rect x="46" y="46" width="8" height="8" fill="${color}" transform="rotate(45 50 50)" />` +
    `</svg>`
  );
}

function renderSarvamLogo(el, options) {
  options = options || {};
  const color = options.color || "#2b2b2b";
  const wordmarkColor = options.wordmarkColor || color;
  el.innerHTML =
    `<span class="mark">${sarvamMarkSVG(color)}</span>` +
    `<span class="wordmark" style="color:${wordmarkColor}">sarvam</span>`;
}
