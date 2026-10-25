(() => {
    "use strict";

    const TOKEN_KEY = "daeo_api_token";
    const TOP_LEVEL = [
        ["home", "Home"],
        ["prices", "Prices & tariff"],
        ["forecast", "Forecast"],
        ["solar", "Solar arrays"],
        ["batteries", "Batteries"],
        ["electric_vehicles", "Electric vehicles"],
        ["machines", "Machines"],
        ["boiler", "Boiler"],
        ["heat_pump", "Heat pump"],
        ["strategy", "Strategy"],
        ["grid", "Grid"],
        ["scheduler", "Scheduler"],
        ["storage", "Storage"],
    ];
    const DEFAULTS = {
        solar: {
            name: "Solar",
            enabled: true,
            peak_power_wp: 4000,
            dc_coupled: false,
            tilt_deg: 35,
            azimuth_deg: 180,
        },
        batteries: {
            name: "Battery",
            enabled: true,
            capacity_kwh: 10,
            max_charge_kw: 5,
            max_discharge_kw: 5,
            efficiency: 0.95,
            min_soc_pct: 20,
            max_soc_pct: 100,
        },
        electric_vehicles: {
            name: "EV",
            enabled: true,
            capacity_kwh: 60,
            max_charge_kw: 11,
            phases: 3,
            target_soc_pct: 80,
            ready_by: "07:00:00",
        },
        machines: {
            name: "Machine",
            enabled: true,
            power_kw: 1,
            duration_minutes: 60,
            earliest_start: "00:00:00",
            deadline: "23:59:00",
        },
        entries: { at: "12:00", action: "optimize" },
        stages: { max_power_kw: 2, cop: 4 },
        boiler: {
            enabled: true,
            volume_l: 180,
            power_kw: 1.5,
            cop: 1,
            target_temp_c: 60,
            hysteresis_c: 5,
        },
        heat_pump: {
            enabled: true,
            stages: [{ max_power_kw: 2, cop: 4 }],
            adjustment_factor: 0.04,
            degree_days_factor: 3.6,
        },
    };
    const SECRETS = [
        ["entsoe_api_key", "ENTSO-E API key"],
        ["tibber_token", "Tibber token"],
        ["meteoserver_key", "Meteoserver key"],
    ];

    const tokenInput = document.getElementById("token");
    const formHost = document.getElementById("form");
    const statusHost = document.getElementById("status");
    const secretsHost = document.getElementById("secrets");
    const secretsStatus = document.getElementById("secrets-status");
    const sourceSummary = document.getElementById("source-summary");

    let rootSchema = null;
    let config = null;
    let dirty = false;

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

    function humanize(value) {
        const acronyms = {
            pct: "%",
            eur: "EUR",
            kwh: "kWh",
            kw: "kW",
            wp: "Wp",
            soc: "SOC",
            cop: "COP",
            vat: "VAT",
            dc: "DC",
            ac: "AC",
            ev: "EV",
            pv: "PV",
            id: "ID",
            dir: "Directory",
        };
        return String(value)
            .split("_")
            .map((word) => acronyms[word.toLowerCase()] || word.charAt(0).toUpperCase() + word.slice(1))
            .join(" ")
            .replace("EUR kWh", "EUR/kWh");
    }

    function setStatus(message, kind = "info") {
        statusHost.className = `alert ${kind}`;
        statusHost.textContent = message;
        statusHost.classList.remove("hidden");
    }

    function hideStatus() {
        statusHost.classList.add("hidden");
    }

    async function api(path, options = {}) {
        const headers = { Accept: "application/json", ...(options.headers || {}) };
        if (options.body && !headers["Content-Type"]) {
            headers["Content-Type"] = "application/json";
        }
        const token = tokenInput.value.trim();
        if (token) headers.Authorization = `Bearer ${token}`;
        const response = await fetch(path, { ...options, headers });
        const text = await response.text();
        let body = null;
        try {
            body = text ? JSON.parse(text) : null;
        } catch {
            body = { raw: text };
        }
        if (!response.ok) {
            const error = new Error(
                body?.error?.message || body?.detail || body?.raw || `HTTP ${response.status}`
            );
            error.status = response.status;
            error.body = body;
            throw error;
        }
        return body;
    }

    function deref(node) {
        if (!node) return {};
        if (node.$ref) {
            const name = node.$ref.split("/").pop();
            const base = rootSchema?.$defs?.[name] || {};
            return { ...deref(base), ...node, $ref: undefined };
        }
        return node;
    }

    function coreSchema(node) {
        const direct = deref(node);
        if (direct.anyOf) {
            const options = direct.anyOf
                .map(deref)
                .filter((option) => option.type !== "null");
            if (options.length) {
                return { ...options[0], ...direct, anyOf: undefined };
            }
        }
        return direct;
    }

    function isNullable(node) {
        const direct = deref(node);
        return Boolean(
            direct.anyOf?.some((option) => deref(option).type === "null")
        );
    }

    function kindOf(schema) {
        if (Array.isArray(schema.enum)) return "enum";
        if (schema.type === "array" || schema.items) return "array";
        if (schema.type === "object" || schema.properties) return "object";
        return schema.type || "string";
    }

    function getAt(object, path) {
        let current = object;
        for (const part of path) {
            if (current === null || current === undefined) return undefined;
            current = current[part];
        }
        return current;
    }

    function setAt(object, path, value) {
        let current = object;
        for (let index = 0; index < path.length - 1; index += 1) {
            const part = path[index];
            if (current[part] === null || current[part] === undefined) {
                current[part] = typeof path[index + 1] === "number" ? [] : {};
            }
            current = current[part];
        }
        current[path[path.length - 1]] = value;
    }

    function markDirty() {
        dirty = true;
        renderSourceSummary();
    }

    function renderSourceSummary() {
        if (!config) return;
        const priceSource = config.prices?.source || "?";
        const pvSource = config.forecast?.solar_source || "?";
        const loadSource = config.load?.source || "?";
        sourceSummary.textContent = `prices: ${priceSource} · PV: ${pvSource} · load: ${loadSource}`;
    }

    function fieldMeta(prop) {
        const direct = deref(prop);
        return { ...coreSchema(prop), ...direct };
    }

    function labelHasUnit(label, unit) {
        if (!unit) return false;
        const escaped = unit.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        return new RegExp(`(^|\\s|\\()${escaped}(\\)|$)`, "i").test(label);
    }

    function addDefault(key) {
        return structuredClone(DEFAULTS[key] || {});
    }

    function renderField(host, key, prop, value, path, meta = fieldMeta(prop)) {
        const schema = coreSchema(prop);
        const kind = kindOf(schema);
        const nullable = isNullable(prop);
        const labelText = meta["x-ui-label"] || humanize(key);
        const help = meta["x-help"] || meta.description || "";
        const unit = meta["x-unit"] || "";
        const errorPath = path.join(".");

        if (kind === "object") {
            if (nullable && value === null) {
                const add = () => {
                    setAt(config, path, addDefault(path[path.length - 1]));
                    renderAll();
                };
                host.append(
                    el("div", { class: "field" },
                        el("label", { text: labelText }),
                        el("div", { class: "optional" },
                            el("span", { text: "Not configured" }),
                            el("button", {
                                class: "secondary small",
                                type: "button",
                                text: "Configure",
                                onclick: add,
                            })
                        ),
                        help ? el("div", { class: "hint", text: help }) : null
                    )
                );
                return;
            }
            const box = el("div", { class: "field" });
            const head = el("div", { class: "array-head" },
                el("strong", { text: labelText }),
                nullable
                    ? el("button", {
                        class: "danger small",
                        type: "button",
                        text: "Remove",
                        onclick: () => {
                            setAt(config, path, null);
                            renderAll();
                        },
                    })
                    : null
            );
            box.append(head);
            if (help) box.append(el("div", { class: "hint", text: help }));
            const nested = el("div", {});
            renderObject(nested, prop, value ?? {}, path);
            box.append(nested);
            host.append(box);
            return;
        }

        if (kind === "array") {
            renderArray(host, key, prop, Array.isArray(value) ? value : [], path, meta);
            return;
        }

        if (kind === "boolean") {
            const input = el("input", { type: "checkbox" });
            input.checked = Boolean(value);
            input.addEventListener("change", () => {
                setAt(config, path, input.checked);
                markDirty();
            });
            const wrapper = el("div", { class: "field check" },
                input,
                el("label", { text: labelText })
            );
            if (help) wrapper.append(el("div", { class: "hint", text: help }));
            wrapper.append(
                el("div", { class: "error hidden", "data-error-for": errorPath })
            );
            host.append(wrapper);
            return;
        }

        let control;
        if (kind === "enum") {
            control = el("select", { "data-path": errorPath });
            if (nullable) control.append(el("option", { value: "", text: "Not set" }));
            for (const option of schema.enum) {
                const element = el("option", { value: String(option), text: String(option) });
                if (String(value) === String(option)) element.selected = true;
                control.append(element);
            }
            control.addEventListener("change", () => {
                setAt(config, path, control.value === "" ? null : control.value);
                markDirty();
            });
        } else {
            const type =
                kind === "integer" || kind === "number"
                    ? "number"
                    : schema.format === "date"
                    ? "date"
                    : schema.format === "time"
                    ? "time"
                    : "text";
            control = el("input", {
                type,
                "data-path": errorPath,
                placeholder: meta["x-ui-widget-filter"]?.includes("sensor")
                    ? "sensor.example"
                    : "",
                pattern: meta.pattern || undefined,
            });
            if (type === "number") {
                control.step = kind === "integer" ? "1" : "any";
                if (schema.minimum !== undefined) control.min = schema.minimum;
                if (schema.maximum !== undefined) control.max = schema.maximum;
            }
            if (type === "time" && typeof value === "string") {
                control.value = value.slice(0, 5);
            } else {
                control.value = value ?? "";
            }
            control.addEventListener("change", () => {
                let parsed;
                if (type === "number") {
                    if (control.value === "") parsed = nullable ? null : 0;
                    else parsed = kind === "integer" ? parseInt(control.value, 10) : Number(control.value);
                } else if (control.value === "") {
                    parsed = nullable ? null : "";
                } else {
                    parsed = control.value;
                    if (type === "time" && parsed.length === 5) parsed += ":00";
                }
                setAt(config, path, parsed);
                markDirty();
            });
        }

        const showUnit = unit && !labelHasUnit(labelText, unit);
        const wrapper = el("div", { class: "field" },
            el("label", {}, labelText, showUnit ? el("span", { class: "unit", text: `(${unit})` }) : null),
            control
        );
        if (help) wrapper.append(el("div", { class: "hint", text: help }));
        if (meta["x-validation-hint"]) {
            wrapper.append(el("div", { class: "hint", text: meta["x-validation-hint"] }));
        }
        wrapper.append(el("div", { class: "error hidden", "data-error-for": errorPath }));
        host.append(wrapper);
    }

    function renderObject(host, node, value, path, options = {}) {
        const schema = coreSchema(node);
        if (!schema.properties) return;
        const showSections = options.showSections !== false;
        const fields = Object.entries(schema.properties)
            .filter(([key]) => key !== "schema_version")
            .map(([key, prop], index) => {
                const meta = fieldMeta(prop);
                return {
                    key,
                    prop,
                    meta,
                    order: meta["x-order"] ?? 1000 + index,
                    section: meta["x-ui-section"] || "General",
                };
            })
            .sort((a, b) => a.order - b.order || a.key.localeCompare(b.key));

        const sections = new Map();
        for (const field of fields) {
            if (!sections.has(field.section)) sections.set(field.section, []);
            sections.get(field.section).push(field);
        }
        if (sections.has("General") && sections.size === 2) {
            const [named] = [...sections.keys()].filter((name) => name !== "General");
            sections.set(named, [...sections.get("General"), ...sections.get(named)]);
            sections.delete("General");
        }

        for (const [section, items] of sections) {
            if (showSections && (sections.size > 1 || section !== "General")) {
                host.append(el("div", { class: "section" }, el("h3", { text: section })));
            }
            const grid = el("div", { class: "grid" });
            for (const field of items) {
                renderField(
                    grid,
                    field.key,
                    field.prop,
                    getAt(value, [field.key]),
                    [...path, field.key],
                    field.meta
                );
            }
            host.append(grid);
        }
    }

    function renderArray(host, key, prop, value, path, meta, options = {}) {
        const schema = coreSchema(prop);
        const itemSchema = schema.items || {};
        const itemKind = kindOf(coreSchema(itemSchema));
        const box = el("div", { class: "field" });
        const help = meta["x-help"] || meta.description || "";
        const showHeading = options.showHeading !== false;
        box.append(el("div", { class: "array-head" },
            showHeading ? el("strong", { text: meta.title || humanize(key) }) : el("span", {}),
            el("button", {
                class: "secondary small",
                type: "button",
                text: "Add",
                onclick: () => {
                    value.push(addDefault(key));
                    setAt(config, path, value);
                    renderAll();
                },
            })
        ));
        if (help) box.append(el("div", { class: "hint", text: help }));

        value.forEach((item, index) => {
            const itemBox = el("div", { class: "array-item" });
            const title =
                item && typeof item === "object" && item.name
                    ? item.name
                    : `Item ${index + 1}`;
            itemBox.append(el("div", { class: "array-head" },
                el("strong", { text: title }),
                el("button", {
                    class: "danger small",
                    type: "button",
                    text: "Remove",
                    onclick: () => {
                        value.splice(index, 1);
                        setAt(config, path, value);
                        renderAll();
                    },
                })
            ));
            if (itemKind === "object") {
                renderObject(itemBox, itemSchema, item, [...path, index], { showSections: false });
            } else {
                const input = el("input", { value: item ?? "" });
                input.addEventListener("change", () => {
                    setAt(config, [...path, index], input.value);
                    markDirty();
                });
                itemBox.append(input);
            }
            box.append(itemBox);
        });
        host.append(box);
    }

    function renderOptionalTop(card, key, prop, value, path) {
        if (value === null || value === undefined) {
            card.append(
                el("div", { class: "optional" },
                    el("span", { text: "Not configured" }),
                    el("button", {
                        class: "secondary small",
                        type: "button",
                        text: "Configure",
                        onclick: () => {
                            setAt(config, path, addDefault(key));
                            renderAll();
                        },
                    })
                )
            );
            return;
        }
        card.append(
            el("div", { class: "array-head" },
                el("strong", { text: "Configured" }),
                el("button", {
                    class: "danger small",
                    type: "button",
                    text: "Remove",
                    onclick: () => {
                        setAt(config, path, null);
                        renderAll();
                    },
                })
            )
        );
        renderObject(card, prop, value, path);
    }

    function renderTop() {
        formHost.replaceChildren();
        for (const [key, label] of TOP_LEVEL) {
            const prop = rootSchema.properties[key];
            if (!prop) continue;
            const schema = coreSchema(prop);
            const value = config[key];
            const card = el("section", { class: "card" }, el("h2", { text: label }));
            if (schema.description) {
                card.append(el("p", { class: "card-help", text: schema.description }));
            }
            if (kindOf(schema) === "array") {
                renderArray(
                    card,
                    key,
                    prop,
                    Array.isArray(value) ? value : [],
                    [key],
                    fieldMeta(prop),
                    { showHeading: false }
                );
            } else if (isNullable(prop)) {
                renderOptionalTop(card, key, prop, value, [key]);
            } else {
                renderObject(card, prop, value ?? {}, [key]);
            }
            formHost.append(card);
        }
    }

    function renderAll() {
        renderTop();
        renderSourceSummary();
        clearErrors();
    }

    function clearErrors() {
        document.querySelectorAll("[data-error-for]").forEach((node) => {
            node.textContent = "";
            node.classList.add("hidden");
        });
        document.querySelectorAll(".invalid").forEach((node) => node.classList.remove("invalid"));
    }

    function showApiError(error) {
        setStatus(error.message, "error");
        const details = error.body?.error?.details;
        if (!Array.isArray(details)) return;
        for (const detail of details) {
            const loc = Array.isArray(detail.loc) ? detail.loc : [];
            const path = loc[0] === "body" ? loc.slice(1) : loc;
            const key = path.join(".");
            if (!key) continue;
            const input = document.querySelector(`[data-path="${key}"]`);
            if (input) input.classList.add("invalid");
            const errorNode = document.querySelector(`[data-error-for="${key}"]`);
            if (errorNode) {
                errorNode.textContent = detail.msg || "Invalid value";
                errorNode.classList.remove("hidden");
            }
        }
    }

    async function load() {
        hideStatus();
        try {
            rootSchema = await api("/api/v1/config/schema");
            config = await api("/api/v1/config");
            dirty = false;
            renderAll();
            setStatus("Settings loaded.", "info");
        } catch (error) {
            setStatus(`Could not load settings: ${error.message}`, "error");
        }
    }

    async function save() {
        clearErrors();
        setStatus("Saving…", "info");
        try {
            const result = await api("/api/v1/config", {
                method: "PUT",
                body: JSON.stringify(config),
            });
            config = result.config;
            dirty = false;
            renderAll();
            setStatus(
                `Saved. Plan ${result.plan_id || "recomputed"} is ready.`,
                "success"
            );
            await loadSecrets();
        } catch (error) {
            showApiError(error);
        }
    }

    async function validate() {
        clearErrors();
        setStatus("Validating…", "info");
        try {
            await api("/api/v1/config/validate", {
                method: "POST",
                body: JSON.stringify(config),
            });
            setStatus("Configuration is valid.", "success");
        } catch (error) {
            showApiError(error);
        }
    }

    async function exportConfig() {
        try {
            const body = await api("/api/v1/config/export");
            const blob = new Blob([JSON.stringify(body, null, 2)], {
                type: "application/json",
            });
            const url = URL.createObjectURL(blob);
            const anchor = el("a", { href: url, download: "daeo-config.json" });
            document.body.append(anchor);
            anchor.click();
            anchor.remove();
            URL.revokeObjectURL(url);
        } catch (error) {
            setStatus(`Export failed: ${error.message}`, "error");
        }
    }

    async function importConfig(file) {
        try {
            const text = await file.text();
            config = JSON.parse(text);
            renderAll();
            setStatus("Configuration imported. Review it and press Save.", "info");
        } catch (error) {
            setStatus(`Import failed: ${error.message}`, "error");
        }
    }

    async function resetConfig() {
        if (!window.confirm("Replace the current configuration with the demo configuration?")) {
            return;
        }
        try {
            const demo = await api("/api/v1/config/demo");
            const result = await api("/api/v1/config", {
                method: "PUT",
                body: JSON.stringify(demo),
            });
            config = result.config;
            renderAll();
            setStatus("Demo configuration restored.", "success");
        } catch (error) {
            showApiError(error);
        }
    }

    async function loadSecrets() {
        if (!tokenInput.value.trim()) {
            secretsHost.replaceChildren();
            secretsStatus.textContent = "Set an API token above to manage secrets.";
            return;
        }
        try {
            const presence = await api("/api/v1/secrets");
            renderSecrets(presence);
        } catch (error) {
            secretsHost.replaceChildren();
            secretsStatus.textContent =
                error.status === 401
                    ? "The API token is missing or invalid."
                    : `Could not load secrets: ${error.message}`;
        }
    }

    function renderSecrets(presence) {
        secretsStatus.textContent = "Secrets are write-only and never returned by the API.";
        secretsHost.replaceChildren();
        for (const [key, label] of SECRETS) {
            const input = el("input", {
                type: "password",
                autocomplete: "new-password",
                placeholder: "unchanged",
            });
            input.dataset.secret = key;
            const set = Boolean(presence[key]);
            const row = el("div", { class: "field" },
                el("label", {}, label, el("span", { class: `pill ${set ? "good" : ""}`, text: set ? "Set" : "Not set" })),
                input,
                el("div", { class: "row", style: "margin-top:6px" },
                    el("button", {
                        class: "ghost small",
                        type: "button",
                        text: "Clear",
                        onclick: () => clearSecret(key),
                    })
                )
            );
            secretsHost.append(row);
        }
    }

    async function saveSecrets() {
        const payload = {};
        secretsHost.querySelectorAll("input[data-secret]").forEach((input) => {
            if (input.value.trim()) payload[input.dataset.secret] = input.value.trim();
        });
        if (!Object.keys(payload).length) {
            setStatus("No secret values entered.", "info");
            return;
        }
        try {
            await api("/api/v1/secrets", {
                method: "PUT",
                body: JSON.stringify(payload),
            });
            secretsHost.querySelectorAll("input[data-secret]").forEach((input) => {
                input.value = "";
            });
            setStatus("Secrets saved.", "success");
            await loadSecrets();
        } catch (error) {
            setStatus(`Could not save secrets: ${error.message}`, "error");
        }
    }

    async function clearSecret(key) {
        try {
            await api("/api/v1/secrets", {
                method: "PUT",
                body: JSON.stringify({ [key]: "" }),
            });
            setStatus("Secret cleared.", "success");
            await loadSecrets();
        } catch (error) {
            setStatus(`Could not clear secret: ${error.message}`, "error");
        }
    }

    document.getElementById("save").addEventListener("click", save);
    document.getElementById("validate").addEventListener("click", validate);
    document.getElementById("reload").addEventListener("click", load);
    document.getElementById("export").addEventListener("click", exportConfig);
    document.getElementById("reset").addEventListener("click", resetConfig);
    document.getElementById("save-secrets").addEventListener("click", saveSecrets);
    document.getElementById("recalculate-load").addEventListener("click", async () => {
        setStatus("Reading HA recorder statistics…", "info");
        try {
            const result = await api("/api/v1/load-profile/calculate", {
                method: "POST",
                body: "{}",
            });
            const warnings = result.profile?.warnings || [];
            setStatus(
                `Load profile calculated for 12 months.` +
                (warnings.length ? ` ${warnings.slice(0, 3).join(" | ")}` : ""),
                warnings.length ? "info" : "success"
            );
        } catch (error) {
            setStatus(`Load profile failed: ${error.message}`, "error");
        }
    });
    document.getElementById("import-button").addEventListener("click", () => {
        document.getElementById("import").click();
    });
    document.getElementById("import").addEventListener("change", (event) => {
        const [file] = event.target.files;
        if (file) importConfig(file);
        event.target.value = "";
    });
    document.getElementById("save-token").addEventListener("click", async () => {
        localStorage.setItem(TOKEN_KEY, tokenInput.value.trim());
        await load();
        await loadSecrets();
    });
    window.addEventListener("beforeunload", (event) => {
        if (!dirty) return;
        event.preventDefault();
        event.returnValue = "";
    });

    load().then(loadSecrets);
})();
