import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const CARD_PATH = "custom_components/justsmart_peak_manager/frontend/justsmart-peak-manager-card.js";

function loadCard() {
  const registry = new Map();
  class FakeShadowRoot {
    constructor() { this.innerHTML = ""; }
    querySelector() { return null; }
    querySelectorAll() { return []; }
  }
  class FakeHTMLElement {
    attachShadow() { this.shadowRoot = new FakeShadowRoot(); return this.shadowRoot; }
    dispatchEvent(event) { this.lastEvent = event; return true; }
  }
  const context = {
    console,
    HTMLElement: FakeHTMLElement,
    CustomEvent: class {
      constructor(type, options = {}) { this.type = type; Object.assign(this, options); }
    },
    window: { customCards: [] },
    customElements: {
      define(name, constructor) {
        if (registry.has(name)) throw new Error(`duplicate ${name}`);
        registry.set(name, constructor);
      },
      get(name) { return registry.get(name); },
    },
  };
  context.document = {
    createElement(name) {
      const Constructor = registry.get(name);
      return Constructor ? new Constructor() : { localName: name };
    },
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(CARD_PATH, "utf8"), context, { filename: CARD_PATH });
  return { context, registry };
}

function entity(state, unit = "kW", attributes = {}) {
  return { state: String(state), attributes: { unit_of_measurement: unit, ...attributes } };
}

test("registers one canonical Peak Manager card and picker metadata", () => {
  const { context, registry } = loadCard();
  assert.ok(registry.get("justsmart-peak-manager-card"));
  assert.equal(context.window.customCards.filter((item) => item.type === "justsmart-peak-manager-card").length, 1);
  assert.match(context.window.customCards[0].name, /JustSmart Peak Manager/);
});

test("renders live interval forecast, target, headroom, monthly peak and action", () => {
  const { registry } = loadCard();
  const Card = registry.get("justsmart-peak-manager-card");
  const card = new Card();
  card.setConfig({
    title: "Netzspitzen Manager",
    projected_entity: "sensor.peak_projected_power",
    average_entity: "sensor.peak_interval_average_power",
    target_entity: "number.peak_limit",
    headroom_entity: "sensor.peak_headroom",
    monthly_peak_entity: "sensor.peak_monthly_peak",
    remaining_entity: "sensor.peak_interval_remaining",
    status_entity: "sensor.peak_status",
    action_entity: "sensor.peak_active_action",
  });
  card.hass = { states: {
    "sensor.peak_projected_power": entity(4.7),
    "sensor.peak_interval_average_power": entity(3.9),
    "number.peak_limit": entity(4.5),
    "sensor.peak_headroom": entity(-0.2),
    "sensor.peak_monthly_peak": entity(4.3),
    "sensor.peak_interval_remaining": entity(522, "s"),
    "sensor.peak_status": entity("limiting", "", { translation_key: "limiting" }),
    "sensor.peak_active_action": entity("Wallbox wird reduziert", ""),
  } };

  const html = card.shadowRoot.innerHTML;
  assert.match(html, /Netzspitzen Manager/);
  assert.match(html, /4,7/);
  assert.match(html, /Ziel/);
  assert.match(html, /Monatsspitze/);
  assert.match(html, /Wallbox wird reduziert/);
  assert.match(html, /8:42/);
  assert.match(html, /aria-label=/);
});

test("updates changing values without rebuilding the whole shadow DOM", () => {
  const { registry } = loadCard();
  const Card = registry.get("justsmart-peak-manager-card");
  const card = new Card();
  card.setConfig({ projected_entity: "sensor.projected", status_entity: "sensor.status" });
  card.hass = { states: { "sensor.projected": entity(3.1), "sensor.status": entity("normal", "") } };
  const originalHtml = card.shadowRoot.innerHTML;
  let updateCalled = false;
  card._updateValues = () => { updateCalled = true; };
  card.hass = { states: { "sensor.projected": entity(3.2), "sensor.status": entity("warning", "") } };

  assert.equal(card.shadowRoot.innerHTML, originalHtml);
  assert.equal(updateCalled, true);
});

test("uses a compact customer-facing label inside the status metric", () => {
  const { registry } = loadCard();
  const Card = registry.get("justsmart-peak-manager-card");
  const card = new Card();
  card.setConfig({ status_entity: "sensor.status" });
  card.hass = { states: { "sensor.status": entity("limiting", "") } };

  assert.equal(card._statusMetricText(), "Aktiv");
  assert.match(card.shadowRoot.innerHTML, /Aktiv/);
  assert.doesNotMatch(card.shadowRoot.innerHTML, /JustSmart reduziert geeignete Verbraucher automatisch<\/strong>/);
});

test("offers Sections sizing and an integration-oriented stub", () => {
  const { registry } = loadCard();
  const Card = registry.get("justsmart-peak-manager-card");
  const stub = Card.getStubConfig();
  const card = new Card();
  card.setConfig(stub);

  assert.equal(stub.type, "custom:justsmart-peak-manager-card");
  assert.match(stub.projected_entity, /^sensor\./);
  assert.equal(
    JSON.stringify(card.getGridOptions()),
    JSON.stringify({ columns: 12, rows: 5, min_columns: 6, min_rows: 4 }),
  );
});

test("ships a real Lovelace editor that emits updated card configuration", () => {
  const { registry } = loadCard();
  const Card = registry.get("justsmart-peak-manager-card");
  const Editor = registry.get("justsmart-peak-manager-card-editor");
  const editor = Card.getConfigElement();

  assert.ok(Editor);
  assert.ok(editor instanceof Editor);
  editor.setConfig({ title: "Alt", projected_entity: "sensor.projected" });
  assert.match(editor.shadowRoot.innerHTML, /ha-textfield/);
  assert.match(editor.shadowRoot.innerHTML, /ha-entity-picker/);

  editor._valueChanged({ target: { configValue: "title", value: "Neu" } });
  assert.equal(editor.lastEvent.type, "config-changed");
  assert.equal(editor.lastEvent.detail.config.title, "Neu");
});

test("supports JustSmart eyebrow aliases and optional visibility", () => {
  const { registry } = loadCard();
  const Card = registry.get("justsmart-peak-manager-card");
  const visible = new Card();
  visible.setConfig({ eyebrow: "Energiemanagement" });
  assert.match(visible.shadowRoot.innerHTML, /Energiemanagement/);

  const hidden = new Card();
  hidden.setConfig({ show_eyebrow: false, eyebrow: "Nicht sichtbar" });
  assert.doesNotMatch(hidden.shadowRoot.innerHTML, /Nicht sichtbar/);
  assert.doesNotMatch(hidden.shadowRoot.innerHTML, /class="eyebrow"/);

  const alias = new Card();
  alias.setConfig({ show_overline: true, overline: "Netzoptimierung" });
  assert.match(alias.shadowRoot.innerHTML, /Netzoptimierung/);
});


test("supports granular visibility controls without leaving empty sections", () => {
  const { registry } = loadCard();
  const Card = registry.get("justsmart-peak-manager-card");
  const card = new Card();
  card.setConfig({
    title: "Ausgeblendeter Titel",
    show_title: false,
    show_status_badge: false,
    show_remaining: false,
    show_meter: false,
    show_average: false,
    show_target: false,
    show_headroom: false,
    show_monthly_peak: false,
    show_status_metric: false,
    show_action: false,
  });

  const html = card.shadowRoot.innerHTML;
  assert.doesNotMatch(html, /class="title"/);
  assert.doesNotMatch(html, /class="status"/);
  assert.doesNotMatch(html, /class="timer"/);
  assert.doesNotMatch(html, /class="meter"/);
  assert.doesNotMatch(html, /data-value="average"/);
  assert.doesNotMatch(html, /data-value="target"/);
  assert.doesNotMatch(html, /data-value="headroom-box"/);
  assert.doesNotMatch(html, /data-value="monthly"/);
  assert.doesNotMatch(html, /data-value="status-detail"/);
  assert.doesNotMatch(html, /class="action"/);
  assert.match(html, /class="main single"/);
});


test("escapes hostile titles in both card and visual editor", () => {
  const { registry } = loadCard();
  const Card = registry.get("justsmart-peak-manager-card");
  const hostile = '<img src=x onerror="globalThis.pwned=1">';
  const card = new Card();
  card.setConfig({ ...Card.getStubConfig(), title: hostile });
  const editor = new (registry.get("justsmart-peak-manager-card-editor"))();
  editor.setConfig({ title: hostile });

  assert.ok(!card.shadowRoot.innerHTML.includes(hostile));
  assert.ok(!editor.shadowRoot.innerHTML.includes(hostile));
  assert.match(card.shadowRoot.innerHTML, /&lt;img/);
  assert.match(editor.shadowRoot.innerHTML, /&lt;img/);
});
