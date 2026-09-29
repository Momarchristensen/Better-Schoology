const SETTINGS_KEYS = {
    reducedMotion: "reducedMotion",
    showAssignments: "showAssignments",
    viewMode: "viewMode",
    sortMode: "sortMode",
    folderColorMode: "folderColorMode",
    rememberExpandedFolders: "rememberExpanded",
    expandedFolders: "expandedFolders",
    dueDateDisplay: "dueDateDisplay",
}

const DEFAULT_SETTINGS = {
    reducedMotion: false,
    showAssignments: true,
    viewMode: "explorer",
    sortMode: "default",
    folderColorMode: "random",
    rememberExpandedFolders: false,
    dueDateDisplay: "relative"
}

window.DEFAULT_SETTINGS = DEFAULT_SETTINGS
window.SETTINGS_KEYS = SETTINGS_KEYS

const RETRY_DELAY_MS = 1000
const MAX_RETRY_DELAY_MS = 10000

function shouldRetryResponse(response) {
    return response.status === 408 || response.status === 429 || response.status >= 500
}

function wait(milliseconds) {
    return new Promise((resolve) => setTimeout(resolve, milliseconds))
}

async function fetchWithRetry(...argumentsList) {
    let delay = RETRY_DELAY_MS

    while (true) {
        try {
            const response = await fetch(...argumentsList)
            if (!shouldRetryResponse(response)) {
                return response
            }

            throw new Error(`Server returned ${response.status}`)
        }
        catch (error) {
            console.error("Request failed; retrying:", error)
            await wait(delay)
            delay = Math.min(delay * 2, MAX_RETRY_DELAY_MS)
        }
    }
}

window.fetchWithRetry = fetchWithRetry

function getStoredSetting(key, fallback) {
    try {
        const value = localStorage.getItem(key)
        return value === null ? fallback : value
    }
    catch (error) {
        console.error("Unable to read setting:", error)
        return fallback
    }
}

function initializeSettings() {
    try {
        Object.entries(DEFAULT_SETTINGS).forEach(([name, value]) => {
            const key = SETTINGS_KEYS[name]
            if (localStorage.getItem(key) === null) {
                localStorage.setItem(key, String(value))
            }
        })
    }
    catch (error) {
        console.error("Unable to initialize settings:", error)
    }
}

function applyStoredSettings() {
    const root = document.documentElement
    const body = document.body

    root.dataset.reducedMotion = getStoredSetting(SETTINGS_KEYS.reducedMotion, String(DEFAULT_SETTINGS.reducedMotion))
    body.dataset.showAssignments = getStoredSetting(SETTINGS_KEYS.showAssignments, String(DEFAULT_SETTINGS.showAssignments))
}

initializeSettings()

function updateSettingsLinks() {
    document.querySelectorAll("[data-settings-link]").forEach((link) => {
        const returnPath = `${window.location.pathname}${window.location.search}`
        link.href = `/settings?return=${encodeURIComponent(returnPath)}`
    })
}

document.addEventListener("DOMContentLoaded", () => {
    applyStoredSettings()
    updateSettingsLinks()
})