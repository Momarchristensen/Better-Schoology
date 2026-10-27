/*
 * Shared back button.
 *
 * Usage: add <script src="/back.js"></script> to <head> and put an empty
 *   <a data-back-button class="..."></a>
 * wherever the button should appear. This file fills in the label, link and
 * click behavior, so there is no per-page back-button code.
 *
 * Back goes to the page's parent, not to the previous page in history:
 *
 *   Material -> Course -> Home
 *   Calendar -> Home
 *   Settings -> the page the user opened it from (?return=...)
 *   Home     -> nowhere (the button is disabled)
 *
 * Only same-origin paths that are not /login are ever navigated to.
 */
(function () {
    const LOGIN_PATH = "/login"
    const HOME_PATH = "/home"

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

    // The page one level above the current one, or null if there is none.
    function resolveParent() {
        const pathname = window.location.pathname.replace(/\/+$/, "") || "/"
        const segments = pathname.split("/").filter(Boolean).map(decodeURIComponent)

        if (pathname === HOME_PATH) {
            return null
        }

        if (pathname === "/calendar") {
            return HOME_PATH
        }

        if (pathname === "/settings") {
            const returnPath = new URLSearchParams(window.location.search).get("return")
            const safeReturn = toSafeAppPath(returnPath)
            return safeReturn && !safeReturn.startsWith("/settings") ? safeReturn : HOME_PATH
        }

        if (segments[0] === "section" && segments[1]) {
            const sectionPath = `/section/${encodeURIComponent(segments[1])}`

            // /section/:id -> Home
            if (segments.length === 2) {
                return HOME_PATH
            }

            // /section/:id/folder/:folderId/material/:materialId -> Course (in that folder)
            const folderId = segments[2] === "folder" ? segments[3] : null
            if (folderId && folderId !== "root") {
                return `${sectionPath}?folder=${encodeURIComponent(folderId)}`
            }

            // Any other page inside a course (e.g. /section/:id/assignment/:id) -> Course
            return sectionPath
        }

        return HOME_PATH
    }

    function setupButton(button) {
        button.textContent = "\u2190 Back"
        button.setAttribute("aria-label", "Go back")

        const target = toSafeAppPath(resolveParent())
        if (target) {
            button.href = target
            button.removeAttribute("aria-disabled")
            button.removeAttribute("tabindex")
        }
        else {
            // Top-level page: nowhere to go back to.
            button.removeAttribute("href")
            button.setAttribute("aria-disabled", "true")
            button.setAttribute("tabindex", "-1")
        }

        button.addEventListener("click", (event) => {
            event.preventDefault()

            // Recompute at click time: the page may have changed its URL since load.
            const clickTarget = toSafeAppPath(resolveParent())
            if (clickTarget) {
                window.location.href = clickTarget
            }
        })
    }

    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll("[data-back-button]").forEach(setupButton)
    })
})()
