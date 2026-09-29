/*
 * Shared back button.
 *
 * Usage: add <script src="/back.js"></script> to <head> and put an empty
 *   <a data-back-button class="..." data-back-fallback="/home"></a>
 * wherever the button should appear. This file fills in the label, link and
 * click behavior, so there is no per-page back-button code.
 *
 * Instead of history.back() (which can land on /login or on another site),
 * we keep our own stack of visited same-site pages in sessionStorage. Only
 * same-origin paths that are not /login are ever recorded or navigated to.
 *
 * The login page loads this script too, but has no button. Visiting /login
 * clears the stack, so logging out (or a session expiring) also wipes it.
 */
(function () {
    const STORAGE_KEY = "backStack"
    const MAX_ENTRIES = 50
    const LOGIN_PATH = "/login"

    // Returns "/path?query" if `path` is a same-origin, non-login path; otherwise null.
    function toSafeAppPath(path) {
        if (typeof path !== "string" || !path.startsWith("/") || path.includes("\\")) {
            return null
        }

        let url
        try {
            url = new URL(path, window.location.origin)
        }
        catch (error) {
            return null
        }

        // Rejects things like "//evil.com" and "/\t/evil.com".
        if (url.origin !== window.location.origin || isLoginPath(url.pathname)) {
            return null
        }

        return url.pathname + url.search
    }

    function isLoginPath(pathname) {
        const normalized = pathname.replace(/\/+$/, "").toLowerCase()
        return normalized === LOGIN_PATH || normalized.startsWith(`${LOGIN_PATH}/`)
    }

    window.toSafeAppPath = toSafeAppPath

    function currentPath() {
        return window.location.pathname + window.location.search
    }

    function readStack() {
        try {
            const parsed = JSON.parse(sessionStorage.getItem(STORAGE_KEY))
            return Array.isArray(parsed) ? parsed.map(toSafeAppPath).filter(Boolean) : []
        }
        catch (error) {
            return []
        }
    }

    function writeStack(stack) {
        try {
            sessionStorage.setItem(STORAGE_KEY, JSON.stringify(stack.slice(-MAX_ENTRIES)))
        }
        catch (error) {
            console.error("Unable to save back history:", error)
        }
    }

    // Keep the stack in sync with the page we're on.
    function recordVisit() {
        if (isLoginPath(window.location.pathname)) {
            writeStack([])
            return
        }

        const here = toSafeAppPath(currentPath())
        if (!here) {
            return
        }

        const stack = readStack()
        if (stack[stack.length - 1] === here) {
            return
        }

        if (stack[stack.length - 2] === here) {
            // The user went back with the browser's own button.
            stack.pop()
        }
        else {
            stack.push(here)
        }

        writeStack(stack)
    }

    // Where the button should go: the previous recorded page, else the fallback.
    function resolveTarget(button) {
        const here = toSafeAppPath(currentPath())
        const stack = readStack()

        if (stack[stack.length - 1] === here) {
            stack.pop()
        }

        for (let index = stack.length - 1; index >= 0; index--) {
            if (stack[index] !== here) {
                return { href: stack[index], stack: stack.slice(0, index + 1) }
            }
        }

        const fallback = toSafeAppPath(button.dataset.backFallback)
        if (fallback && fallback !== here) {
            return { href: fallback, stack: [fallback] }
        }

        return null
    }

    let leavingViaBackButton = false

    function setupButton(button) {
        button.textContent = "\u2190 Back"
        button.setAttribute("aria-label", "Go back")

        const target = resolveTarget(button)
        if (target) {
            button.href = target.href
            button.removeAttribute("aria-disabled")
            button.removeAttribute("tabindex")
        }
        else {
            // Nowhere safe to go (e.g. the first page after login).
            button.removeAttribute("href")
            button.setAttribute("aria-disabled", "true")
            button.setAttribute("tabindex", "-1")
        }

        button.addEventListener("click", (event) => {
            event.preventDefault()

            // Recompute at click time: the page may have changed its URL since load.
            const clickTarget = resolveTarget(button)
            if (!clickTarget) {
                return
            }

            leavingViaBackButton = true
            writeStack(clickTarget.stack)
            window.location.href = clickTarget.href
        })
    }

    recordVisit()

    // Pages such as the course view change their URL with replaceState;
    // store the final URL so going back returns to the exact state.
    function saveCurrentPath() {
        if (leavingViaBackButton || isLoginPath(window.location.pathname)) {
            return
        }

        const here = toSafeAppPath(currentPath())
        const stack = readStack()
        if (here && stack.length > 0) {
            stack[stack.length - 1] = here
            writeStack(stack)
        }
    }

    window.addEventListener("pagehide", saveCurrentPath)

    window.addEventListener("pageshow", (event) => {
        if (event.persisted) {
            leavingViaBackButton = false
            recordVisit()
        }
    })

    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll("[data-back-button]").forEach(setupButton)
    })
})()
