(function () {
    const READY_EVENT = "DOMContentLoaded";
    const FOCUSABLE_SELECTOR = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

    let settingsModal = null;
    let settingsButton = null;
    let lastFocusedElement = null;
    let loadingOverlay = null;

    function getToastContainer() {
        return document.getElementById("toast-container");
    }

    function showToast(message) {
        const container = getToastContainer();
        if (!container) {
            console.warn("Toast container missing");
            return;
        }
        const toast = document.createElement("div");
        toast.className = "toast";
        toast.innerHTML = message;
        container.appendChild(toast);
        requestAnimationFrame(() => {
            toast.classList.add("show");
        });
        setTimeout(() => {
            toast.classList.remove("show");
            setTimeout(() => toast.remove(), 250);
        }, 5000);
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
                if (Array.isArray(parsed)) {
                    parsed.forEach((msg) => showToast(msg));
                }
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
        window.addEventListener("show-toasts", (event) => {
            const messages = event.detail;
            if (!messages || !Array.isArray(messages)) {
                return;
            }
            messages.forEach((msg) => showToast(msg));
        });

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
            if (evt.detail?.target) {
                consumeToastPayloads(evt.detail.target);
            }
            setupUploadForm(evt.detail?.target || document);
            const xhr = evt.detail?.xhr;
            if (!xhr) {
                return;
            }
            const triggerHeader = xhr.getResponseHeader("HX-Trigger");
            const payload = parseHxTriggerHeader(triggerHeader);
            if (!payload) {
                return;
            }
            if (payload["theme-changed"]) {
                const theme = payload["theme-changed"].theme;
                if (theme === "light" || theme === "dark") {
                    handleThemeChange(theme);
                }
            }
            if (evt.detail?.target?.id === "settings-modal-body") {
                focusFirstInteractive(evt.detail.target);
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
