(function () {
    const READY_EVENT = "DOMContentLoaded";
    const FOCUSABLE_SELECTOR = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

    let settingsModal = null;
    let settingsButton = null;
    let lastFocusedElement = null;
    let loadingOverlay = null;
    let recentToasts = new Set();

    function getToastContainer() {
        return document.getElementById("toast-container");
    }

    function showToast(message) {
        const container = getToastContainer();
        if (!container) {
            console.warn("Toast container missing");
            return;
        }
        
        // Prevent duplicate toasts within 5 seconds
        if (recentToasts.has(message)) {
            return;
        }
        recentToasts.add(message);
        setTimeout(() => recentToasts.delete(message), 5000);
        
        const toast = document.createElement("div");
        toast.className = "toast";
        toast.textContent = message;
        container.appendChild(toast);
        requestAnimationFrame(() => {
            toast.classList.add("show");
        });
        setTimeout(() => {
            toast.classList.remove("show");
            setTimeout(() => toast.remove(), 250);
        }, 5000);
    }

    function normalizeToastMessage(value) {
        if (value === null || value === undefined) {
            return null;
        }
        if (typeof value === "string") {
            return value;
        }
        if (typeof value === "number" || typeof value === "boolean") {
            return String(value);
        }
        if (Array.isArray(value)) {
            const combined = value
                .map((entry) => normalizeToastMessage(entry))
                .filter((entry) => typeof entry === "string" && entry.trim().length > 0)
                .join(" \u2022 ");
            return combined.length > 0 ? combined : null;
        }
        if (typeof value === "object") {
            if (Object.prototype.hasOwnProperty.call(value, "value")) {
                const nested = normalizeToastMessage(value.value);
                if (typeof nested === "string" && nested.trim().length > 0) {
                    return nested;
                }
            }
            const candidateKeys = ["heading", "title", "message", "detail", "description"];
            for (const key of candidateKeys) {
                const candidate = value[key];
                if (typeof candidate === "string" && candidate.trim().length > 0) {
                    return candidate;
                }
            }
            try {
                const serialized = JSON.stringify(value);
                return serialized && serialized !== "{}" ? serialized : null;
            } catch (err) {
                return null;
            }
        }
        return String(value);
    }

    function emitToastMessages(payload) {
        if (!payload) {
            return;
        }
        const messages = Array.isArray(payload) ? payload : [payload];
        messages
            .map((msg) => normalizeToastMessage(msg))
            .filter((msg) => typeof msg === "string" && msg.trim().length > 0)
            .map((msg) => msg.trim())
            .forEach((msg) => showToast(msg));
    }

    function consumeToastPayloads(root) {
        const scope = root || document;
        const payloads = scope.querySelectorAll?.(".toast-payload");
        if (!payloads || payloads.length === 0) {
            return;
        }
        payloads.forEach((el) => {
            try {
                const data = el.dataset?.messages;
                if (!data) {
                    return;
                }
                const parsed = JSON.parse(data);
                emitToastMessages(parsed);
            } catch (err) {
                console.warn("Failed to parse toast payload", err);
            } finally {
                el.remove();
            }
        });
    }

    function parseHxTriggerHeader(headerValue) {
        if (!headerValue) {
            return null;
        }
        try {
            return JSON.parse(headerValue);
        } catch (err) {
            console.warn("Unable to parse HX-Trigger header", err);
            return null;
        }
    }

    function shouldShowLoading(path) {
        return path === "/analysis" || path === "/generate" || path === "/upload";
    }

    function showLoadingOverlay() {
        if (!loadingOverlay) {
            return;
        }
        loadingOverlay.classList.add("is-active");
        loadingOverlay.setAttribute("aria-hidden", "false");
    }

    function hideLoadingOverlay() {
        if (!loadingOverlay) {
            return;
        }
        loadingOverlay.classList.remove("is-active");
        loadingOverlay.setAttribute("aria-hidden", "true");
    }

    function handleThemeChange(theme) {
        const body = document.body;
        if (!body) {
            return;
        }
        body.classList.remove("theme-dark", "theme-light");
        body.classList.add(`theme-${theme}`);
        const slot = document.getElementById("theme-toggle-slot");
        if (slot) {
            slot.dataset.currentTheme = theme;
        }
    }

    function syncInitialTheme() {
        const body = document.body;
        if (!body) {
            return;
        }
        if (!body.classList.contains("theme-dark") && !body.classList.contains("theme-light")) {
            body.classList.add("theme-dark");
        }
        const slot = document.getElementById("theme-toggle-slot");
        const initial = slot?.dataset?.currentTheme;
        if (initial === "light" || initial === "dark") {
            handleThemeChange(initial);
        } else if (body.classList.contains("theme-light")) {
            handleThemeChange("light");
        } else {
            handleThemeChange("dark");
        }
    }

    function setUploadButtonsState(form, enabled) {
        const buttons = typeof form.querySelectorAll === "function" ? form.querySelectorAll(".requires-upload") : null;
        if (!buttons) {
            return;
        }
        buttons.forEach((button) => {
            button.disabled = !enabled;
        });
    }

    function setupUploadForm(scope) {
        const root = scope && typeof scope.querySelector === "function" ? scope : document;
        const form = (typeof root.querySelector === "function" ? root.querySelector("#solution-form") : null) || document.getElementById("solution-form");
        if (!form || form.dataset.uploadInit === "true") {
            return;
        }
        form.dataset.uploadInit = "true";

        const fileInput = form.querySelector('input[type="file"]');

        const evaluateState = () => {
            const hasStored = form.dataset.hasUpload === "true";
            const hasFile = !!(fileInput && fileInput.files && fileInput.files.length > 0);
            form.dataset.hasUpload = hasStored || hasFile ? "true" : "false";
            setUploadButtonsState(form, hasStored || hasFile);
        };

        evaluateState();

        if (fileInput) {
            fileInput.addEventListener("change", () => {
                evaluateState();
            });
        }

        form.addEventListener("submit", (evt) => {
            const hasStored = form.dataset.hasUpload === "true";
            const hasFile = !!(fileInput && fileInput.files && fileInput.files.length > 0);
            if (!hasStored && !hasFile) {
                evt.preventDefault();
                showToast("Upload a solution description before running analysis or generation.");
                return;
            }
        });
    }

    function focusFirstInteractive(container) {
        if (!container || typeof container.querySelectorAll !== "function") {
            return;
        }
        const candidates = Array.from(container.querySelectorAll(FOCUSABLE_SELECTOR));
        if (candidates.length > 0 && typeof candidates[0].focus === "function") {
            candidates[0].focus();
        }
    }

    function openSettingsModal() {
        if (!settingsModal) {
            return;
        }
        lastFocusedElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        document.body?.classList.add("modal-open");
        settingsModal.classList.add("is-open");
        settingsModal.setAttribute("aria-hidden", "false");
        const closeButton = settingsModal.querySelector(".modal-close");
        if (closeButton instanceof HTMLElement && typeof closeButton.focus === "function") {
            closeButton.focus();
        }
        const body = settingsModal.querySelector("#settings-modal-body");
        if (body) {
            body.innerHTML = '<div class="modal-loading">Loading settings…</div>';
            if (window.htmx) {
                window.htmx.ajax("GET", "/settings/modal", {
                    target: "#settings-modal-body",
                    swap: "outerHTML",
                });
            }
        }
    }

    function closeSettingsModal() {
        if (!settingsModal) {
            return;
        }
        settingsModal.classList.remove("is-open");
        settingsModal.setAttribute("aria-hidden", "true");
        document.body?.classList.remove("modal-open");
        if (lastFocusedElement && typeof lastFocusedElement.focus === "function") {
            lastFocusedElement.focus();
        }
    }

    function trapFocus(event) {
        if (!settingsModal || !settingsModal.classList.contains("is-open")) {
            return;
        }
        if (event.key !== "Tab") {
            return;
        }
        const focusable = Array.from(settingsModal.querySelectorAll(FOCUSABLE_SELECTOR)).filter(
            (el) => !el.hasAttribute("disabled") && el.getAttribute("tabindex") !== "-1"
        );
        if (focusable.length === 0) {
            return;
        }
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        const active = document.activeElement;
        if (event.shiftKey) {
            if (active === first || !focusable.includes(active)) {
                event.preventDefault();
                last.focus();
            }
        } else if (active === last) {
            event.preventDefault();
            first.focus();
        }
    }

    function setupEventHandlers() {
        syncInitialTheme();
        setupUploadForm(document);
        const handleToastEvent = (event) => {
            const detail = event?.detail;
            const payload = detail && Object.prototype.hasOwnProperty.call(detail, "value") ? detail.value : detail;
            emitToastMessages(payload);
        };

        document.addEventListener("show-toasts", handleToastEvent);

        document.body?.addEventListener("htmx:beforeRequest", (evt) => {
            const path = evt.detail?.requestConfig?.path || evt.detail?.pathInfo?.path;
            if (path === "/analysis") {
                showToast("Analyzing solution description…");
            } else if (path === "/generate") {
                showToast("Generating draft RAI assessment…");
            }
            if (shouldShowLoading(path)) {
                showLoadingOverlay();
            }
        });

        document.body?.addEventListener("htmx:afterRequest", () => {
            hideLoadingOverlay();
        });

        document.body?.addEventListener("htmx:responseError", () => {
            hideLoadingOverlay();
        });

        document.body?.addEventListener("htmx:sendError", () => {
            hideLoadingOverlay();
        });

        document.body?.addEventListener("htmx:afterSwap", (evt) => {
            const target = evt.detail?.target || null;
            if (target) {
                consumeToastPayloads(target);
            }
            const syncToastPayloads = () => consumeToastPayloads(document);
            if (typeof queueMicrotask === "function") {
                queueMicrotask(syncToastPayloads);
            } else {
                setTimeout(syncToastPayloads, 0);
            }
            setupUploadForm(target || document);
            const xhr = evt.detail?.xhr;
            if (xhr) {
                const triggerHeader = xhr.getResponseHeader("HX-Trigger");
                const payload = parseHxTriggerHeader(triggerHeader);
                if (payload) {
                    if (payload["theme-changed"]) {
                        const theme = payload["theme-changed"].theme;
                        if (theme === "light" || theme === "dark") {
                            handleThemeChange(theme);
                        }
                    }
                    if (payload["show-toasts"]) {
                        emitToastMessages(payload["show-toasts"]);
                    }
                }
            }
            if (target?.id === "settings-modal-body") {
                focusFirstInteractive(target);
            }
        });

        settingsModal = document.getElementById("settings-modal");
        settingsButton = document.getElementById("settings-button");
        loadingOverlay = document.getElementById("loading-overlay");

        settingsButton?.addEventListener("click", () => {
            openSettingsModal();
        });

        settingsModal?.addEventListener("click", (event) => {
            const target = event.target;
            if (!(target instanceof HTMLElement)) {
                return;
            }
            if (target.dataset.modalClose !== undefined) {
                closeSettingsModal();
            }
        });

        settingsModal?.addEventListener("keydown", trapFocus);

        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && settingsModal?.classList.contains("is-open")) {
                event.preventDefault();
                closeSettingsModal();
            }
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener(READY_EVENT, () => {
            setupEventHandlers();
            consumeToastPayloads(document);
        });
    } else {
        setupEventHandlers();
        consumeToastPayloads(document);
    }
})();
