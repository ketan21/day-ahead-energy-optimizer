(() => {
    "use strict";

    const TOKEN_KEY = "daeo_api_token";
    const STEPS = ["Home", "Prices", "Solar", "Battery", "EV & boiler", "Review"];
    const tokenInput = document.getElementById("token");
    const stepHost = document.getElementById("step");
    const stepsHost = document.getElementById("steps");
    const statusHost = document.getElementById("status");
    const nextButton = document.getElementById("next");
    const finishButton = document.getElementById("finish");
    const backButton = document.getElementById("back");

    let config = null;
    let stepIndex = 0;

    tokenInput.value = localStorage.getItem(TOKEN_KEY) || "";

    function el(tag, attrs = {}, ...children) {
        const node = document.createElement(tag);
        for (const [key, value] of Object.entries(attrs)) {
            if (value === undefined || value === null) continue;
            if (key === "class") node.className = value;
            else if (key === "text") node.textContent = value;
            else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
            else node.setAttribute(key, value);
        }
        for (const child of children.flat()) {
            if (child === undefined || child === null) continue;
            node.append(child instanceof Node ? child : document.createTextNode(String(child)));
        }
        return node;
    }

    function get(path) {
        return path.split(".").reduce((value, part) => value?.[part], config);
    }

    function set(path, value) {
        const parts = path.split(".");
        let current = config;
        for (let index = 0; index < parts.length - 1; index += 1) {
            const part = parts[index];
            if (current[part] === null || current[part] === undefined) current[part] = {};
            current = current[part];
        }
        current[parts[parts.length - 1]] = value;
    }

    function setStatus(message, kind = "info") {
        statusHost.className = `alert ${kind}`;
        statusHost.textContent = message;
        statusHost.classList.remove("hidden");
    }

    function field(label, control, help = "") {
        return el("div", { class: "field" },
            el("label", { text: label }),
            control,
            help ? el("div", { class: "hint", text: help }) : null
        );
    }

    function textField(path, label, help = "") {
        const input = el("input", { type: "text" });
        input.value = get(path) ?? "";
        input.addEventListener("input", () => set(path, input.value));
        return field(label, input, help);
    }

    function numberField(path, label, help = "", step = "any") {
        const input = el("input", { type: "number", step });
        input.value = get(path) ?? "";
        input.addEventListener("input", () => {
            set(path, input.value === "" ? null : Number(input.value));
        });
        return field(label, input, help);
    }

    function timeField(path, label, help = "") {
        const input = el("input", { type: "time" });
        const value = get(path);
        input.value = typeof value === "string" ? value.slice(0, 5) : "";
        input.addEventListener("change", () => {
            set(path, input.value ? `${input.value}:00` : null);
        });
        return field(label, input, help);
    }

    function selectField(path, label, options, help = "") {
        const select = el("select", {});
        for (const [value, text] of options) {
            const option = el("option", { value, text });
            if (String(get(path)) === String(value)) option.selected = true;
            select.append(option);
        }
        select.addEventListener("change", () => set(path, select.value));
        return field(label, select, help);
    }

    function checkField(label, checked, onChange, help = "") {
        const input = el("input", { type: "checkbox" });
        input.checked = checked;
        input.addEventListener("change", () => {
            onChange(input.checked);
            renderStep();
        });
        return el("div", { class: "field check" },
            input,
            el("label", { text: label }),
            help ? el("div", { class: "hint", text: help }) : null
        );
    }

    function ensureArray(key, defaults) {
        if (!Array.isArray(config[key])) config[key] = [];
        if (!config[key].length) config[key].push(structuredClone(defaults));
        return config[key][0];
    }

    function renderSteps() {
        stepsHost.replaceChildren();
        STEPS.forEach((label, index) => {
            const className =
                index === stepIndex ? "step active" : index < stepIndex ? "step done" : "step";
            stepsHost.append(el("span", { class: className, text: `${index + 1}. ${label}` }));
        });
    }

    function header(title, help) {
        return el("section", { class: "card" },
            el("h2", { text: title }),
            help ? el("p", { class: "card-help", text: help }) : null
        );
    }

    function renderHome() {
        const card = header("Home and market", "Location is used for the solar forecast and the plan timezone.");
        const grid = el("div", { class: "grid" });
        grid.append(
            textField("home.name", "Name"),
            textField("home.timezone", "Timezone", "For example Europe/Amsterdam."),
            numberField("home.latitude", "Latitude"),
            numberField("home.longitude", "Longitude"),
            selectField("home.country", "Country", [["NL", "Netherlands"], ["BE", "Belgium"]])
        );
        card.append(grid);
        stepHost.append(card);
    }

    function renderPrices() {
        const source = get("prices.source") || "energyzero";
        const card = header("Energy prices", "EnergyZero returns all-in consumer prices for the Netherlands.");
        const grid = el("div", { class: "grid" });
        grid.append(
            selectField("prices.source", "Price source", [
                ["energyzero", "EnergyZero (NL, all-in)"],
                ["fixed", "Fixed tariff"],
                ["entsoe", "ENTSO-E (API key needed)"],
            ]),
            textField("prices.area", "Price area", "NL or BE."),
            numberField("prices.fixed_export_price_eur_kwh", "Export / feed-in price", "EUR/kWh.")
        );
        if (source === "fixed") {
            grid.append(
                numberField("prices.fixed_import_price_eur_kwh", "Fixed import price", "EUR/kWh all-in."),
                numberField("prices.supplier_markup_import_eur_kwh", "Supplier markup", "EUR/kWh."),
                numberField("prices.energy_tax_import_eur_kwh", "Energy tax", "EUR/kWh."),
                numberField("prices.vat_pct", "VAT", "%.")
            );
        }
        card.append(grid);
        card.append(el("p", { class: "hint",
            text: source === "energyzero"
                ? "EnergyZero's all-in price already includes tax and VAT. The export price is not provided by the API; set it above or leave it at 0."
                : "The API key for ENTSO-E can be added later in Settings → Secrets." }));
        stepHost.append(card);
    }

    function renderSolar() {
        const enabled = Array.isArray(config.solar) && config.solar.length > 0;
        const card = header("Solar", "Forecast.Solar uses your location, tilt, azimuth, and peak power.");
        card.append(checkField("I have solar panels", enabled, (checked) => {
            if (checked) {
                ensureArray("solar", {
                    name: "Solar",
                    enabled: true,
                    peak_power_wp: 4000,
                    dc_coupled: false,
                    tilt_deg: 35,
                    azimuth_deg: 180,
                });
            } else {
                config.solar = [];
            }
        }));
        if (enabled) {
            const array = config.solar[0];
            const grid = el("div", { class: "grid" });
            grid.append(
                textField("solar.0.name", "Name"),
                numberField("solar.0.peak_power_wp", "Peak power", "Wp, total array."),
                numberField("solar.0.tilt_deg", "Tilt", "Degrees."),
                numberField("solar.0.azimuth_deg", "Azimuth", "180 = south."),
                selectField("forecast.solar_source", "PV forecast", [
                    ["forecast_solar", "Forecast.Solar (live)"],
                    ["synthetic", "Synthetic demo curve"],
                ])
            );
            card.append(grid);
            card.append(el("p", { class: "hint",
                text: "Forecast.Solar has a limit of 12 requests per hour per IP. The plan is still a demo: household load is synthetic." }));
        }
        stepHost.append(card);
    }

    function renderBattery() {
        const enabled = Array.isArray(config.batteries) && config.batteries.length > 0;
        const card = header("Battery", "Only the first battery is edited here.");
        card.append(checkField("I have a home battery", enabled, (checked) => {
            if (checked) {
                ensureArray("batteries", {
                    name: "Battery",
                    enabled: true,
                    capacity_kwh: 10,
                    max_charge_kw: 5,
                    max_discharge_kw: 5,
                    efficiency: 0.95,
                    min_soc_pct: 20,
                    max_soc_pct: 100,
                });
            } else {
                config.batteries = [];
            }
        }));
        if (enabled) {
            const grid = el("div", { class: "grid" });
            grid.append(
                textField("batteries.0.name", "Name"),
                numberField("batteries.0.capacity_kwh", "Usable capacity", "kWh."),
                numberField("batteries.0.max_charge_kw", "Max charge power", "kW."),
                numberField("batteries.0.max_discharge_kw", "Max discharge power", "kW."),
                numberField("batteries.0.efficiency", "One-way efficiency", "0.95 is about 90% round trip."),
                numberField("batteries.0.min_soc_pct", "Minimum SOC", "%."),
                numberField("batteries.0.max_soc_pct", "Maximum SOC", "%.")
            );
            card.append(grid);
        }
        stepHost.append(card);
    }

    function renderFlexible() {
        const evEnabled = Array.isArray(config.electric_vehicles) && config.electric_vehicles.length > 0;
        const boilerEnabled = Boolean(config.boiler);
        const card = header("EV and boiler", "Both are optional. You can add more devices later.");
        card.append(checkField("I have an electric vehicle", evEnabled, (checked) => {
            if (checked) {
                ensureArray("electric_vehicles", {
                    name: "EV",
                    enabled: true,
                    capacity_kwh: 60,
                    max_charge_kw: 11,
                    phases: 3,
                    target_soc_pct: 80,
                    ready_by: "07:00:00",
                });
            } else {
                config.electric_vehicles = [];
            }
        }));
        if (evEnabled) {
            const grid = el("div", { class: "grid" });
            grid.append(
                textField("electric_vehicles.0.name", "EV name"),
                numberField("electric_vehicles.0.capacity_kwh", "Battery capacity", "kWh."),
                numberField("electric_vehicles.0.max_charge_kw", "Max charge power", "kW."),
                numberField("electric_vehicles.0.target_soc_pct", "Target SOC", "%."),
                timeField("electric_vehicles.0.ready_by", "Ready by", "Departure time.")
            );
            card.append(grid);
        }
        card.append(checkField("I have a hot water boiler", boilerEnabled, (checked) => {
            config.boiler = checked
                ? {
                    enabled: true,
                    volume_l: 180,
                    power_kw: 1.5,
                    cop: 1,
                    target_temp_c: 60,
                    hysteresis_c: 5,
                }
                : null;
        }));
        if (boilerEnabled) {
            const grid = el("div", { class: "grid" });
            grid.append(
                numberField("boiler.volume_l", "Volume", "Litres."),
                numberField("boiler.power_kw", "Electric power", "kW."),
                numberField("boiler.cop", "COP"),
                numberField("boiler.target_temp_c", "Target temperature", "°C.")
            );
            card.append(grid);
        }
        stepHost.append(card);
    }

    function summaryLine(label, value) {
        return el("div", { class: "row" },
            el("span", { class: "pill", text: label }),
            el("span", { text: value })
        );
    }

    function renderReview() {
        const card = header("Strategy and review", "These settings decide what the optimizer tries to achieve.");
        const grid = el("div", { class: "grid" });
        grid.append(
            selectField("strategy.objective", "Objective", [
                ["minimize_cost", "Minimize cost"],
                ["minimize_import", "Minimize grid import"],
            ]),
            selectField("strategy.interval", "Interval", [
                ["quarter_hour", "15 minutes"],
                ["hour", "60 minutes"],
            ]),
            numberField("strategy.reserve_soc_pct", "Battery reserve", "%."),
            numberField("strategy.cycle_cost_eur_kwh", "Cycle cost", "EUR/kWh.")
        );
        card.append(grid);

        const solar = config.solar?.[0];
        const battery = config.batteries?.[0];
        const ev = config.electric_vehicles?.[0];
        const lines = [
            summaryLine("Home", `${config.home.name} · ${config.home.country} · ${config.home.timezone}`),
            summaryLine("Prices", config.prices.source),
            summaryLine(
                "Solar",
                solar ? `${solar.peak_power_wp} Wp · ${config.forecast?.solar_source || "synthetic"}` : "none"
            ),
            summaryLine("Battery", battery ? `${battery.capacity_kwh} kWh` : "none"),
            summaryLine("EV", ev ? `${ev.capacity_kwh} kWh · ready ${String(ev.ready_by).slice(0, 5)}` : "none"),
            summaryLine("Boiler", config.boiler ? `${config.boiler.volume_l} L` : "none"),
        ];
        card.append(el("div", { class: "section" }, el("h3", { text: "Summary" })));
        const summary = el("div", { class: "card", style: "box-shadow:none;background:var(--surface-2)" });
        lines.forEach((line) => summary.append(line));
        card.append(summary);
        card.append(el("p", { class: "hint",
            text: "Saving recomputes the plan. Household load is still synthetic in this milestone; prices and PV can be real." }));
        stepHost.append(card);
    }

    function renderStep() {
        if (!config) return;
        renderSteps();
        stepHost.replaceChildren();
        [renderHome, renderPrices, renderSolar, renderBattery, renderFlexible, renderReview][stepIndex]();
        backButton.disabled = stepIndex === 0;
        nextButton.classList.toggle("hidden", stepIndex === STEPS.length - 1);
        finishButton.classList.toggle("hidden", stepIndex !== STEPS.length - 1);
        window.scrollTo({ top: 0, behavior: "smooth" });
    }

    function validateStep() {
        if (stepIndex === 0) {
            if (!config.home?.name || !config.home?.timezone) {
                setStatus("Give your home a name and timezone.", "error");
                return false;
            }
        }
        if (stepIndex === 1 && config.prices.source === "fixed") {
            if (config.prices.fixed_import_price_eur_kwh === null) {
                setStatus("Enter the fixed import price.", "error");
                return false;
            }
        }
        if (stepIndex === 2 && config.solar.length) {
            if (!config.solar[0].peak_power_wp) {
                setStatus("Enter the solar peak power.", "error");
                return false;
            }
        }
        if (stepIndex === 3 && config.batteries.length) {
            if (!config.batteries[0].capacity_kwh) {
                setStatus("Enter the battery capacity.", "error");
                return false;
            }
        }
        return true;
    }

    async function api(path, options = {}) {
        const headers = { Accept: "application/json", ...(options.headers || {}) };
        if (options.body) headers["Content-Type"] = "application/json";
        const token = tokenInput.value.trim();
        if (token) headers.Authorization = `Bearer ${token}`;
        const response = await fetch(path, { ...options, headers });
        const text = await response.text();
        let body = null;
        try { body = text ? JSON.parse(text) : null; } catch { body = { raw: text }; }
        if (!response.ok) {
            throw new Error(body?.error?.message || body?.detail || `HTTP ${response.status}`);
        }
        return body;
    }

    async function load() {
        try {
            config = await api("/api/v1/config");
            config.forecast ||= { solar_source: "synthetic" };
            stepIndex = 0;
            renderStep();
        } catch (error) {
            setStatus(`Could not load configuration: ${error.message}`, "error");
        }
    }

    async function finish() {
        if (!validateStep()) return;
        finishButton.disabled = true;
        setStatus("Saving and computing the plan…", "info");
        try {
            await api("/api/v1/config", {
                method: "PUT",
                body: JSON.stringify(config),
            });
            setStatus("Saved. Opening the plan…", "success");
            window.setTimeout(() => window.location.assign("/"), 700);
        } catch (error) {
            setStatus(`Could not save: ${error.message}`, "error");
            finishButton.disabled = false;
        }
    }

    nextButton.addEventListener("click", () => {
        if (!validateStep()) return;
        stepIndex = Math.min(STEPS.length - 1, stepIndex + 1);
        renderStep();
    });
    backButton.addEventListener("click", () => {
        stepIndex = Math.max(0, stepIndex - 1);
        renderStep();
    });
    finishButton.addEventListener("click", finish);
    document.getElementById("save-token").addEventListener("click", async () => {
        localStorage.setItem(TOKEN_KEY, tokenInput.value.trim());
        await load();
    });

    load();
})();
