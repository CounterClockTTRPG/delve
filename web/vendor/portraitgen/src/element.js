// <portrait-gen> web component: drop a generated portrait into any page.
//
//   <script type="module" src="https://unpkg.com/portraitgen/src/element.js"></script>
//   <portrait-gen seed="aria" theme="fantasy" archetype="elf" portrait-style="realistic" size="256"></portrait-gen>
//
// Attributes mirror generate() options: describe ("a stout old male dwarf"), seed, theme, archetype, presentation, build,
// age, expression, lighting, framing, turn, portrait-style, plus any part (hair="long")
// and `traits` (a JSON traits object, which takes precedence). `size` sets the
// rendered pixel size (default 256). The element re-renders when attributes change
// and fires a `portrait` event with { traits } after each render.
import { generate, render, CATEGORIES } from './index.js';

const OPTION_ATTRS = ['describe', 'seed', 'theme', 'archetype', 'presentation', 'build', 'age', 'expression', 'lighting', 'framing', 'turn', 'portrait-style', 'traits', 'size', 'alt'];

export class PortraitGenElement extends HTMLElement {
  static get observedAttributes() { return [...OPTION_ATTRS, ...CATEGORIES.map((c) => c.toLowerCase())]; }

  connectedCallback() { this.#render(); }
  attributeChangedCallback() { if (this.isConnected) this.#render(); }

  /** The traits of the portrait currently shown. */
  get traits() { return this._traits; }
  set traits(t) { this.setAttribute('traits', JSON.stringify(t)); }

  #options() {
    const o = {};
    for (const a of ['describe', 'seed', 'theme', 'archetype', 'presentation', 'build', 'age', 'expression', 'lighting', 'framing']) {
      const v = this.getAttribute(a);
      if (v) o[a] = v;
    }
    if (this.hasAttribute('turn')) o.turn = Number(this.getAttribute('turn'));
    if (this.hasAttribute('portrait-style')) o.style = this.getAttribute('portrait-style');
    for (const c of CATEGORIES) { const v = this.getAttribute(c.toLowerCase()); if (v) o[c] = v; }
    return o;
  }

  #render() {
    let traits;
    try {
      traits = this.hasAttribute('traits') ? JSON.parse(this.getAttribute('traits')) : generate(this.#options());
    } catch (e) {
      this.textContent = `portrait-gen: ${e.message}`;
      return;
    }
    this._traits = traits;
    const size = Number(this.getAttribute('size')) || 256;
    // Unique ids per element so several portraits can share a page.
    PortraitGenElement.count = (PortraitGenElement.count ?? 0) + 1;
    const svg = render(traits, { size, idPrefix: `pge${PortraitGenElement.count}` });
    this.innerHTML = svg;
    const el = this.firstElementChild;
    el.setAttribute('role', 'img');
    el.setAttribute('aria-label', this.getAttribute('alt') ?? describe(traits));
    if (!this.style.display) this.style.display = 'inline-block';
    this.dispatchEvent(new CustomEvent('portrait', { detail: { traits } }));
  }
}

/** A short plain-language description of a portrait, used as its accessible label. */
export function describe(t) {
  const words = [t.age === 'elder' ? 'elderly' : t.age === 'young' ? 'young' : t.age === 'middle' ? 'middle-aged' : null,
    t.archetype && t.archetype !== 'human' ? t.archetype : null,
    t.presentation === 'feminine' ? 'woman' : t.presentation === 'masculine' ? 'man' : 'person'].filter(Boolean);
  return `Portrait of a${/^[aeiou]/.test(words[0]) ? 'n' : ''} ${words.join(' ')}`;
}

if (typeof customElements !== 'undefined' && !customElements.get('portrait-gen')) customElements.define('portrait-gen', PortraitGenElement);
