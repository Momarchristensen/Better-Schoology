const REFRESH_INTERVAL_MS = 5 * 60 * 1000

window.initAssignmentsSidebar = function initAssignmentsSidebar(options) {
    const mountId = options.mountId
    const sectionId = options.sectionId
    const waitFor = options.waitFor

    const mount = document.getElementById(mountId)


    mount.classList.add("assignments-panel")
    mount.innerHTML = `
        <div class="assignments-group overdue">
            <h2 class="assignments-group-header">
                <button type="button" class="assignments-group-toggle" aria-expanded="true" aria-controls="assignments-overdue-list">
                    <span class="dot"></span>
                    <span class="assignments-group-title">Overdue</span>
                    <span class="assignments-count" data-role="overdue-count">0</span>
                    <span class="assignments-chevron" aria-hidden="true"></span>
                </button>
            </h2>
            <ul class="assignments-list" id="assignments-overdue-list" data-role="overdue-list"></ul>
        </div>

        <div class="assignments-group upcoming">
            <h2 class="assignments-group-header">
                <button type="button" class="assignments-group-toggle" aria-expanded="true" aria-controls="assignments-upcoming-list">
                    <span class="dot"></span>
                    <span class="assignments-group-title">Upcoming</span>
                    <span class="assignments-count" data-role="upcoming-count">0</span>
                    <span class="assignments-chevron" aria-hidden="true"></span>
                </button>
            </h2>
            <ul class="assignments-list" id="assignments-upcoming-list" data-role="upcoming-list"></ul>
        </div>
    `

    const overdueListElement = mount.querySelector("[data-role=\"overdue-list\"]")
    const upcomingListElement = mount.querySelector("[data-role=\"upcoming-list\"]")
    const overdueCountElement = mount.querySelector("[data-role=\"overdue-count\"]")
    const upcomingCountElement = mount.querySelector("[data-role=\"upcoming-count\"]")

    for (const group of mount.querySelectorAll(".assignments-group")) {
        const toggle = group.querySelector(".assignments-group-toggle")

        toggle.addEventListener("click", () => {
            const collapsed = group.classList.toggle("collapsed")
            toggle.setAttribute("aria-expanded", String(!collapsed))
        })
    }

    let countdownTargets = []

    async function fetchAssignmentGroupData(url, label) {
        try {
            const query = sectionId ? `?section_id=${encodeURIComponent(sectionId)}` : ""
            const response = await fetchWithRetry(`${url}${query}`)
            const data = await response.json()

            if (data.status === "error") {
                console.error(`Failed to load ${label} assignments:`, data.message)
                return []
            }

            return data.materials
        }
        catch (error) {
            console.error(`Error fetching ${label} assignments:`, error)
            return []
        }
    }

    function formatDueDate(dueDateString) {
        if (!dueDateString) {
            return ""
        }

        const dueDate = new Date(dueDateString)
        if (isNaN(dueDate.getTime())) {
            return dueDateString
        }

        return dueDate.toLocaleDateString(undefined, { month: "short", day: "numeric" })
    }

    function renderAssignments(overdue, upcoming) {
        countdownTargets = []
        renderAssignmentGroup(overdueListElement, overdueCountElement, overdue, "overdue")
        renderAssignmentGroup(upcomingListElement, upcomingCountElement, upcoming, "upcoming")
        updateCountdowns()
    }

    function renderAssignmentGroup(listElement, countElement, assignments, kind) {
        listElement.innerHTML = ""
        countElement.textContent = assignments.length

        if (assignments.length === 0) {
            const empty = document.createElement("li")
            empty.className = "assignments-empty"
            empty.textContent = kind === "overdue" ? "Nothing overdue" : "Nothing upcoming"
            listElement.appendChild(empty)
            return
        }

        for (const assignment of assignments) {
            const item = document.createElement("li")
            item.className = "assignment-item"
            item.innerHTML = `
                <a class="assignment-link" href="${assignment.href}">
                    <div class="assignment-info">
                        <div class="assignment-name"></div>
                        <div class="assignment-course"></div>
                    </div>
                    <span class="assignment-due">
                        <span class="assignment-due-date"></span>
                        <span class="assignment-due-countdown"></span>
                    </span>
                </a>
            `

            item.querySelector(".assignment-name").textContent = assignment.name
            item.querySelector(".assignment-course").textContent = assignment.courseTitle
            item.querySelector(".assignment-due-date").textContent = assignment.dueDate

            const countdownElement = item.querySelector(".assignment-due-countdown")
            if (Number.isFinite(assignment.dueDateMs) && assignment.dueDateMs !== 0) {
                countdownElement.dataset.dueMs = assignment.dueDateMs
                countdownElement.dataset.kind = kind
                countdownTargets.push(countdownElement)
            }
            else {
                countdownElement.style.display = "none"
            }

            listElement.appendChild(item)
        }
    }

    function updateCountdowns() {
        const now = Date.now()

        for (const element of countdownTargets) {
            const dueMs = Number(element.dataset.dueMs)
            const diff = dueMs - now

            element.textContent = diff >= 0 ? `${formatMilliseconds(diff)} left` : `${formatMilliseconds(Math.abs(diff))} ago`

            if (diff < 0 && element.dataset.kind === "upcoming") {
                moveToOverdue(element)
            }
        }
    }

    function moveToOverdue(countdownElement) {
        const item = countdownElement.closest(".assignment-item")
        if (!item) {
            return
        }

        const overdueEmpty = overdueListElement.querySelector(".assignments-empty")
        if (overdueEmpty) {
            overdueEmpty.remove()
        }

        overdueListElement.appendChild(item)
        countdownElement.dataset.kind = "overdue"


        const dateElement = item.querySelector(".assignment-due-date")
        dateElement.textContent = new Date(Number(countdownElement.dataset.dueMs))
            .toLocaleDateString(undefined, { month: "short", day: "numeric" })

        overdueCountElement.textContent = Number(overdueCountElement.textContent) + 1
        upcomingCountElement.textContent = Math.max(0, Number(upcomingCountElement.textContent) - 1)

        if (upcomingListElement.children.length === 0) {
            const empty = document.createElement("li")
            empty.className = "assignments-empty"
            empty.textContent = "Nothing upcoming"
            upcomingListElement.appendChild(empty)
        }
    }

    function formatMilliseconds(milliseconds) {
        const totalSeconds = Math.floor(milliseconds / 1000)
        const days = Math.floor(totalSeconds / 86400)
        const hours = Math.floor(totalSeconds % 86400 / 3600)
        const minutes = Math.floor(totalSeconds % 3600 / 60)
        const seconds = totalSeconds % 60

        const durationParts = []

        if (days) {
            durationParts.push(`${days}d`)
            durationParts.push(`${String(hours).padStart(2, "0")}h`)
            durationParts.push(`${String(minutes).padStart(2, "0")}m`)
            durationParts.push(`${String(seconds).padStart(2, "0")}s`)
        }
        else if (hours) {
            durationParts.push(`${hours}h`)
            durationParts.push(`${String(minutes).padStart(2, "0")}m`)
            durationParts.push(`${String(seconds).padStart(2, "0")}s`)
        }
        else if (minutes) {
            durationParts.push(`${minutes}m`)
            durationParts.push(`${String(seconds).padStart(2, "0")}s`)
        }
        else if (seconds) {
            durationParts.push(`${String(seconds).padStart(2, "0")}s`)
        }

        return durationParts.join(" ") || "0s"
    }

    function normalizeAssignments(items, kind) {
        return items
            .map((item) => {
                const dueDateMs = item.dueDate ? new Date(item.dueDate).getTime() : NaN

                return {
                    id: item.id,
                    name: item.title,
                    courseTitle: item.category || "",
                    dueDate: formatDueDate(item.dueDate, kind),
                    dueDateMs,
                    parent: item.parent,
                    href: `/section/${item.parent.section_id}/folder/${item.parent.folder_id || "root"}/material/${item.id}`
                }
            })
    }

    function formatDueDate(dueDateString, kind) {
        if (!dueDateString) {
            return ""
        }

        const dueDate = new Date(dueDateString)
        if (isNaN(dueDate.getTime())) {
            return dueDateString
        }

        const shortDate = dueDate.toLocaleDateString(undefined, { month: "short", day: "numeric" })

        if (kind !== "upcoming") {
            return shortDate
        }

        const dueDateDisplay = getStoredSetting(SETTINGS_KEYS.dueDateDisplay, DEFAULT_SETTINGS.dueDateDisplay)
        if (dueDateDisplay === "date") {
            return shortDate
        }

        const hour = dueDate.getHours()


        const labelDate = new Date(dueDate)
        if (hour < 5) {
            labelDate.setDate(labelDate.getDate() - 1)
        }

        const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate())
        const dayDiff = Math.max(0, Math.round((startOfDay(labelDate) - startOfDay(new Date())) / 86400000))
        const weekday = labelDate.toLocaleDateString(undefined, { weekday: "long" })
        const period = getTimeOfDayLabel(hour)

        if (dayDiff === 0) {
            return getTodayLabel(period)
        }
        if (dayDiff === 1) {
            return `Tomorrow ${period}`
        }
        if (dayDiff >= 2 && dayDiff <= 6) {
            return `${weekday} ${period}`
        }
        if (dayDiff >= 7 && dayDiff <= 13) {
            return `Next ${weekday} ${period}`
        }

        return shortDate
    }

    function getTodayLabel(period) {
        switch (period) {
            case "Night":
                return "Tonight"
            case "Midnight":
                return "Midnight Tonight"
            case "Noon":
                return "Noon Today"
            default:
                return `This ${period}`
        }
    }

    function getTimeOfDayLabel(hour) {
        if (hour === 0) {
            return "Midnight"
        }
        if (hour === 12) {
            return "Noon"
        }
        if (hour >= 5 && hour < 12) {
            return "Morning"
        }
        if (hour >= 13 && hour < 17) {
            return "Afternoon"
        }
        if (hour >= 17 && hour < 21) {
            return "Evening"
        }

        return "Night"
    }

    setInterval(updateCountdowns, 1000)

    async function load() {
        const [_, overdueRaw, upcomingRaw] = await Promise.all([
            waitFor,
            fetchAssignmentGroupData("/api/overdue", "overdue"),
            fetchAssignmentGroupData("/api/upcoming", "upcoming")
        ])

        renderAssignments(
            normalizeAssignments(overdueRaw, "overdue"),
            normalizeAssignments(upcomingRaw, "upcoming")
        )
    }

    const ready = load()

    setInterval(load, REFRESH_INTERVAL_MS)

    return { refresh: load, ready }
}