(() => {
  "use strict";

  const TAG = "justsmart-peak-manager-card";
  const EDITOR_TAG = "justsmart-peak-manager-card-editor";
  const DEFAULTS = Object.freeze({
    title: "Peak Manager",
    projected_entity: "sensor.justsmart_peak_manager_projected_power",
    average_entity: "sensor.justsmart_peak_manager_interval_average_power",
    target_entity: "number.justsmart_peak_manager_peak_limit",
    headroom_entity: "sensor.justsmart_peak_manager_headroom",
    monthly_peak_entity: "sensor.justsmart_peak_manager_monthly_peak",
    remaining_entity: "sensor.justsmart_peak_manager_interval_remaining",
    status_entity: "sensor.justsmart_peak_manager_status",
    action_entity: "sensor.justsmart_peak_manager_active_action",
  });

  const STATUS = Object.freeze({
    normal: { label: "Im grünen Bereich", detail: "Ihre Leistung bleibt sicher unter dem Zielwert." },
    warning: { label: "Zielwert im Blick", detail: "Die verfügbare Leistungsreserve wird kleiner." },
    limiting: { label: "Last wird optimiert", detail: "JustSmart reduziert geeignete Verbraucher automatisch." },
    unavailable: { label: "Daten werden geladen", detail: "Sobald Messwerte verfügbar sind, sehen Sie hier den aktuellen Status." },
  });

  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const EDITOR_FIELDS = Object.freeze([
    ["projected_entity", "Viertelstunden-Prognose"],
    ["average_entity", "Aktueller Viertelstunden-Durchschnitt"],
    ["target_entity", "Zielspitze"],
    ["headroom_entity", "Leistungsspielraum"],
    ["monthly_peak_entity", "Monatsspitze"],
    ["remaining_entity", "Verbleibende Intervallzeit"],
    ["status_entity", "Status"],
    ["action_entity", "Aktive Maßnahme"],
  ]);

  class JustSmartPeakManagerCardEditor extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._config = {};
      this._hass = null;
    }

    set hass(hass) {
      this._hass = hass;
      this.shadowRoot?.querySelectorAll("ha-entity-picker").forEach((picker) => {
        picker.hass = hass;
      });
    }

    setConfig(config) {
      this._config = { ...config };
      this._render();
    }

    _render() {
      const title = escapeHtml(this._config.title ?? DEFAULTS.title);
      const fields = EDITOR_FIELDS.map(([key, label]) => `
        <ha-entity-picker
          data-config-value="${key}"
          label="${escapeHtml(label)}"
          value="${escapeHtml(this._config[key] ?? DEFAULTS[key])}"
          allow-custom-entity
        ></ha-entity-picker>`).join("");
      this.shadowRoot.innerHTML = `
        <style>
          :host{display:grid;gap:16px;padding:8px 0}
          ha-textfield,ha-entity-picker{display:block;width:100%}
          .entities{display:grid;gap:12px}
        </style>
        <ha-textfield data-config-value="title" label="Titel" value="${title}"></ha-textfield>
        <div class="entities">${fields}</div>`;

      this.shadowRoot.querySelectorAll("[data-config-value]").forEach((field) => {
        field.configValue = field.dataset.configValue;
        if (field.localName === "ha-entity-picker") field.hass = this._hass;
        field.addEventListener("value-changed", (event) => this._valueChanged(event));
        field.addEventListener("input", (event) => this._valueChanged(event));
      });
    }

    _valueChanged(event) {
      const key = event.target.configValue || event.target.dataset?.configValue;
      if (!key) return;
      const value = event.detail?.value ?? event.target.value;
      this._config = { ...this._config, [key]: value };
      this.dispatchEvent(new CustomEvent("config-changed", {
        bubbles: true,
        composed: true,
        detail: { config: this._config },
      }));
    }
  }

  class JustSmartPeakManagerCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._config = null;
      this._hass = null;
      this._hasLiveRender = false;
      this._eventsBound = false;
    }

    static getStubConfig() {
      return {
        type: "custom:justsmart-peak-manager-card",
        ...DEFAULTS,
      };
    }

    static getConfigElement() {
      return document.createElement(EDITOR_TAG);
    }

    setConfig(config) {
      if (!config || typeof config !== "object") {
        throw new Error("Die Konfiguration für die JustSmart Peak Manager Card fehlt.");
      }
      this._config = { ...DEFAULTS, ...config };
      this._hasLiveRender = Boolean(this._hass);
      this._render();
    }

    set hass(hass) {
      this._hass = hass;
      if (!this._config) return;

      if (!this._hasLiveRender) {
        this._hasLiveRender = true;
        this._render();
        return;
      }
      this._updateValues();
    }

    get hass() {
      return this._hass;
    }

    getGridOptions() {
      return { columns: 12, rows: 5, min_columns: 6, min_rows: 4 };
    }

    getCardSize() {
      return 5;
    }

    connectedCallback() {
      this._bindEvents();
    }

    _entity(key) {
      const entityId = this._config?.[key];
      return entityId ? this._hass?.states?.[entityId] : undefined;
    }

    _raw(key) {
      const state = this._entity(key)?.state;
      return state == null || state === "unknown" || state === "unavailable" ? null : state;
    }

    _number(key) {
      const raw = this._raw(key);
      if (raw == null || raw === "") return null;
      const number = Number(raw);
      return Number.isFinite(number) ? number : null;
    }

    _unit(key, fallback = "kW") {
      return this._entity(key)?.attributes?.unit_of_measurement || fallback;
    }

    _formatNumber(key, digits = 1, fallbackUnit = "kW") {
      const value = this._number(key);
      if (value == null) return "—";
      const formatted = new Intl.NumberFormat("de-DE", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      }).format(value);
      const unit = this._unit(key, fallbackUnit);
      return unit ? `${formatted} ${unit}` : formatted;
    }

    _formatRemaining() {
      const value = this._number("remaining_entity");
      if (value == null) return "—:—";
      const unit = this._unit("remaining_entity", "s").toLowerCase();
      const totalSeconds = Math.max(0, Math.round(unit.startsWith("min") ? value * 60 : value));
      const minutes = Math.floor(totalSeconds / 60);
      const seconds = totalSeconds % 60;
      return `${minutes}:${String(seconds).padStart(2, "0")}`;
    }

    _statusKey() {
      const raw = String(this._raw("status_entity") || "unavailable").toLowerCase();
      if (["limiting", "limit", "active", "critical"].includes(raw)) return "limiting";
      if (["warning", "warn", "near_limit"].includes(raw)) return "warning";
      if (["normal", "ok", "idle"].includes(raw)) return "normal";
      return "unavailable";
    }

    _statusMetricText() {
      return {
        normal: "Bereit",
        warning: "Nah am Ziel",
        limiting: "Aktiv",
        unavailable: "Keine Daten",
      }[this._statusKey()];
    }

    _actionText() {
      const action = this._raw("action_entity");
      if (action) return String(action);
      const status = this._statusKey();
      if (status === "limiting") return "Verbraucher werden intelligent angepasst";
      if (status === "warning") return "Leistungsreserve wird laufend geprüft";
      if (status === "normal") return "Aktuell ist kein Eingriff nötig";
      return "Noch keine aktive Maßnahme";
    }

    _headroomTone() {
      const value = this._number("headroom_entity");
      if (value == null) return "neutral";
      return value < 0 ? "danger" : value < 0.5 ? "warning" : "good";
    }

    _meterPercent() {
      const projected = this._number("projected_entity");
      const target = this._number("target_entity");
      if (projected == null || target == null || target <= 0) return 0;
      return Math.min(100, Math.max(0, (projected / target) * 100));
    }

    _render() {
      if (!this.shadowRoot || !this._config) return;
      const statusKey = this._statusKey();
      const status = STATUS[statusKey];
      const title = escapeHtml(this._config.title || DEFAULTS.title);
      const projected = escapeHtml(this._formatNumber("projected_entity"));
      const average = escapeHtml(this._formatNumber("average_entity"));
      const target = escapeHtml(this._formatNumber("target_entity"));
      const headroom = escapeHtml(this._formatNumber("headroom_entity"));
      const monthly = escapeHtml(this._formatNumber("monthly_peak_entity"));
      const remaining = escapeHtml(this._formatRemaining());
      const action = escapeHtml(this._actionText());
      const meter = this._meterPercent().toFixed(1);

      this.shadowRoot.innerHTML = `
        <style>
          :host{display:block;container-type:inline-size;font-family:var(--paper-font-body1_-_font-family,var(--primary-font-family,Inter,system-ui,sans-serif));color:var(--primary-text-color,#f4f7fb)}
          *{box-sizing:border-box}
          ha-card{display:block;position:relative;overflow:hidden;min-height:250px;padding:22px;border:1px solid color-mix(in srgb,var(--primary-text-color,#fff) 10%,transparent);border-radius:24px;background:radial-gradient(circle at 92% 0%,rgba(29,190,184,.17),transparent 34%),linear-gradient(145deg,var(--ha-card-background,var(--card-background-color,#101a24)),color-mix(in srgb,var(--ha-card-background,var(--card-background-color,#101a24)) 88%,#071019));box-shadow:0 18px 45px rgba(0,0,0,.18)}
          .header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:20px}.eyebrow{margin-bottom:5px;color:#54d7cf;font-size:11px;font-weight:800;letter-spacing:.14em;text-transform:uppercase}.title{margin:0;font-size:clamp(20px,5cqi,28px);line-height:1.15;letter-spacing:-.025em}.status{display:flex;align-items:center;gap:8px;max-width:48%;padding:8px 11px;border:1px solid rgba(255,255,255,.1);border-radius:999px;background:rgba(255,255,255,.055);font-size:12px;font-weight:750;text-align:right}.dot{width:8px;height:8px;flex:0 0 auto;border-radius:50%;background:#8d9aa5;box-shadow:0 0 0 4px rgba(141,154,165,.12)}.status[data-status="normal"] .dot{background:#47d18c;box-shadow:0 0 0 4px rgba(71,209,140,.13)}.status[data-status="warning"] .dot{background:#ffc857;box-shadow:0 0 0 4px rgba(255,200,87,.13)}.status[data-status="limiting"] .dot{background:#ff6b72;box-shadow:0 0 0 4px rgba(255,107,114,.13)}
          .main{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(180px,.75fr);gap:16px}.forecast,.side{border:1px solid rgba(255,255,255,.09);border-radius:18px;background:rgba(255,255,255,.045)}.forecast{padding:17px}.label{color:var(--secondary-text-color,#a7b2bc);font-size:12px;font-weight:700}.forecast-row{display:flex;align-items:flex-end;justify-content:space-between;gap:12px}.forecast-value{margin:4px 0 12px;font-size:clamp(34px,9cqi,50px);font-weight:820;line-height:1;letter-spacing:-.045em}.timer{text-align:right}.timer strong{display:block;margin-top:4px;font-size:20px;font-variant-numeric:tabular-nums}.meter{position:relative;height:8px;overflow:hidden;border-radius:999px;background:rgba(255,255,255,.1)}.meter-fill{height:100%;width:var(--meter,0%);border-radius:inherit;background:linear-gradient(90deg,#3bc4ba,#ffc857 74%,#ff6b72);transition:width .25s ease}.meter-target{position:absolute;right:0;top:-2px;width:2px;height:12px;background:rgba(255,255,255,.82)}.forecast-meta{display:flex;justify-content:space-between;gap:12px;margin-top:10px;color:var(--secondary-text-color,#a7b2bc);font-size:12px}.forecast-meta strong{color:var(--primary-text-color,#fff)}
          .side{display:grid;grid-template-columns:1fr 1fr;overflow:hidden}.metric{min-width:0;padding:15px}.metric:nth-child(odd){border-right:1px solid rgba(255,255,255,.08)}.metric:nth-child(-n+2){border-bottom:1px solid rgba(255,255,255,.08)}.metric strong{display:block;margin-top:6px;overflow:hidden;color:var(--primary-text-color,#fff);font-size:17px;text-overflow:ellipsis;white-space:nowrap}.metric[data-tone="good"] strong{color:#66dda2}.metric[data-tone="warning"] strong{color:#ffd06c}.metric[data-tone="danger"] strong{color:#ff858a}
          .action{display:flex;align-items:center;gap:12px;margin-top:16px;padding:13px 15px;border:1px solid rgba(84,215,207,.18);border-radius:16px;background:rgba(32,167,160,.09)}.action-icon{display:grid;width:34px;height:34px;flex:0 0 auto;place-items:center;border-radius:11px;background:rgba(84,215,207,.14);color:#65ded6}.action svg{width:19px;height:19px;fill:none;stroke:currentColor;stroke-linecap:round;stroke-linejoin:round;stroke-width:1.8}.action-text{min-width:0}.action-text strong{display:block;margin-top:2px;overflow:hidden;font-size:13px;text-overflow:ellipsis;white-space:nowrap}.sr-only{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}
          @container (max-width:580px){ha-card{min-height:220px;padding:17px;border-radius:20px}.header{margin-bottom:14px}.main{grid-template-columns:1fr}.forecast{padding:14px}.side{grid-template-columns:repeat(4,1fr)}.metric{padding:12px 9px}.metric:nth-child(n){border:0;border-right:1px solid rgba(255,255,255,.08)}.metric:last-child{border-right:0}.metric strong{font-size:14px}.action{margin-top:12px}.status{max-width:50%;padding:7px 9px}.forecast-value{font-size:36px}}
          @container (max-width:390px){.side{grid-template-columns:1fr 1fr}.metric:nth-child(n){border:0}.metric:nth-child(odd){border-right:1px solid rgba(255,255,255,.08)}.metric:nth-child(-n+2){border-bottom:1px solid rgba(255,255,255,.08)}.status{font-size:0}.status .dot{margin:2px}.action-text strong{white-space:normal}}
          @media (prefers-reduced-motion:reduce){.meter-fill{transition:none}}
        </style>
        <ha-card role="button" tabindex="0" aria-label="${title}: ${escapeHtml(status.label)}">
          <div class="header">
            <div><div class="eyebrow">JustSmart Lastmanagement</div><h2 class="title">${title}</h2></div>
            <div class="status" data-value="status" data-status="${statusKey}" aria-live="polite"><span class="dot" aria-hidden="true"></span><span data-value="status-label">${escapeHtml(status.label)}</span></div>
          </div>
          <div class="main">
            <section class="forecast" aria-label="Intervallprognose">
              <div class="forecast-row"><div><span class="label">Prognose Intervall</span><div class="forecast-value" data-value="projected">${projected}</div></div><div class="timer"><span class="label">Verbleibend</span><strong data-value="remaining">${remaining}</strong></div></div>
              <div class="meter" role="meter" aria-label="Prognose im Verhältnis zum Ziel" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${meter}"><div class="meter-fill" data-value="meter" style="--meter:${meter}%"></div><span class="meter-target" aria-hidden="true"></span></div>
              <div class="forecast-meta"><span>Ø aktuell <strong data-value="average">${average}</strong></span><span>Ziel <strong data-value="target">${target}</strong></span></div>
            </section>
            <section class="side" aria-label="Leistungskennzahlen">
              <div class="metric" data-value="headroom-box" data-tone="${this._headroomTone()}"><span class="label">Reserve</span><strong data-value="headroom">${headroom}</strong></div>
              <div class="metric"><span class="label">Monatsspitze</span><strong data-value="monthly">${monthly}</strong></div>
              <div class="metric"><span class="label">Ziel</span><strong data-value="target-secondary">${target}</strong></div>
              <div class="metric"><span class="label">Status</span><strong data-value="status-detail">${escapeHtml(this._statusMetricText())}</strong></div>
            </section>
          </div>
          <div class="action" aria-live="polite"><span class="action-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M13 2 5 14h6l-1 8 8-12h-6l1-8Z"/></svg></span><div class="action-text"><span class="label">Aktive Maßnahme</span><strong data-value="action">${action}</strong></div></div>
        </ha-card>`;
      this._bindEvents();
    }

    _setText(selector, value) {
      const node = this.shadowRoot?.querySelector(selector);
      if (node && node.textContent !== value) node.textContent = value;
    }

    _updateValues() {
      if (!this.shadowRoot || !this._config) return;
      this._setText('[data-value="projected"]', this._formatNumber("projected_entity"));
      this._setText('[data-value="average"]', this._formatNumber("average_entity"));
      this._setText('[data-value="target"]', this._formatNumber("target_entity"));
      this._setText('[data-value="target-secondary"]', this._formatNumber("target_entity"));
      this._setText('[data-value="headroom"]', this._formatNumber("headroom_entity"));
      this._setText('[data-value="monthly"]', this._formatNumber("monthly_peak_entity"));
      this._setText('[data-value="remaining"]', this._formatRemaining());
      this._setText('[data-value="action"]', this._actionText());

      const statusKey = this._statusKey();
      const status = STATUS[statusKey];
      this._setText('[data-value="status-label"]', status.label);
      this._setText('[data-value="status-detail"]', this._statusMetricText());
      const statusNode = this.shadowRoot.querySelector('[data-value="status"]');
      if (statusNode) statusNode.dataset.status = statusKey;
      const headroomNode = this.shadowRoot.querySelector('[data-value="headroom-box"]');
      if (headroomNode) headroomNode.dataset.tone = this._headroomTone();
      const meter = this._meterPercent();
      const meterNode = this.shadowRoot.querySelector('[data-value="meter"]');
      if (meterNode) meterNode.style.setProperty("--meter", `${meter}%`);
      const meterRoot = meterNode?.parentElement;
      if (meterRoot) meterRoot.setAttribute("aria-valuenow", meter.toFixed(1));
      const card = this.shadowRoot.querySelector("ha-card");
      if (card) card.setAttribute("aria-label", `${this._config.title || DEFAULTS.title}: ${status.label}`);
    }

    _bindEvents() {
      if (this._eventsBound || typeof this.addEventListener !== "function") return;
      this._eventsBound = true;
      this.addEventListener("click", (event) => {
        if (!event.defaultPrevented) this._showMoreInfo();
      });
      this.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        this._showMoreInfo();
      });
    }

    _showMoreInfo() {
      const entityId = this._config?.projected_entity;
      if (!entityId) return;
      this.dispatchEvent(new CustomEvent("hass-more-info", {
        bubbles: true,
        composed: true,
        detail: { entityId },
      }));
    }
  }

  if (!customElements.get(EDITOR_TAG)) customElements.define(EDITOR_TAG, JustSmartPeakManagerCardEditor);
  if (!customElements.get(TAG)) customElements.define(TAG, JustSmartPeakManagerCard);
  window.customCards = window.customCards || [];
  if (!window.customCards.some((card) => card.type === TAG)) {
    window.customCards.push({
      type: TAG,
      name: "JustSmart Peak Manager",
      description: "Behält Leistungsspitzen im Blick und zeigt die aktive Lastoptimierung.",
      preview: true,
    });
  }
})();
