let searchIndexPromise = null

function getSearchIndex() {
    if (!searchIndexPromise) {
        searchIndexPromise = fetchWithRetry("/api/search_list")
            .then((response) => {
                if (!response.ok) {
                    throw new Error(`Search index request failed: ${response.status}`)
                }
                return response.json()
            })
            .then((data) => Object.values(data.courses || {}))
            .catch((error) => {
                searchIndexPromise = null
                throw error
            })
    }
    return searchIndexPromise
}

window.initAssignmentsSearch = function initAssignmentsSearch({ mountId, sectionId }) {
    const mount = document.getElementById(mountId)

    mount.innerHTML = `
        <div class="search-bar${sectionId ? " search-bar--scoped" : ""}">
            <div class="search-input-wrap">
                <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                    stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="11" cy="11" r="7" />
                    <line x1="21" y1="21" x2="16.65" y2="16.65" />
                </svg>
                ${sectionId ? "<span class=\"search-scope\">This course</span>" : ""}
                <input class="search-input" type="text"
                    placeholder="${sectionId ? "Search assignments in this course only" : "Search all courses and assignments"}"
                    autocomplete="off" />
            </div>
            <div class="search-results"></div>
        </div>
    `

    const searchBar = mount.querySelector(".search-bar")
    const searchInput = mount.querySelector(".search-input")
    const searchResults = mount.querySelector(".search-results")

    let debounceTimer = null
    let latestRequestId = 0
    let activeIndex = -1


    searchInput.addEventListener("focus", () => getSearchIndex().catch(() => { }), { once: true })

    searchInput.addEventListener("input", () => {
        const query = searchInput.value.trim()

        clearTimeout(debounceTimer)

        if (!query) {
            closeResults()
            return
        }

        debounceTimer = setTimeout(() => runSearch(query), 120)
    })

    searchInput.addEventListener("keydown", (event) => {
        const items = Array.from(searchResults.querySelectorAll(".search-result"))

        if (event.key === "Escape") {
            closeResults()
            return
        }

        if (!items.length) {
            return
        }

        if (event.key === "ArrowDown") {
            event.preventDefault()
            setActive(items, Math.min(activeIndex + 1, items.length - 1))
        }
        else if (event.key === "ArrowUp") {
            event.preventDefault()
            setActive(items, Math.max(activeIndex - 1, 0))
        }
        else if (event.key === "Enter" && activeIndex >= 0) {
            event.preventDefault()
            items[activeIndex].click()
        }
    })

    document.addEventListener("click", (event) => {
        if (!searchBar.contains(event.target)) {
            closeResults()
        }
    })

    function setActive(items, index) {
        items.forEach((item) => item.classList.remove("active"))
        activeIndex = index
        items[activeIndex].classList.add("active")
        items[activeIndex].scrollIntoView({ block: "nearest" })
    }

    function closeResults() {
        searchResults.classList.remove("open")
        searchResults.innerHTML = ""
        activeIndex = -1
    }

    async function runSearch(query) {
        const requestId = ++latestRequestId
        searchResults.classList.add("open")
        searchResults.innerHTML = "<div class=\"search-status\">Searching...</div>"

        let courseList
        try {
            courseList = await getSearchIndex()
        }
        catch (error) {
            console.error("Error loading search index:", error)
            if (requestId === latestRequestId) {
                searchResults.innerHTML = "<div class=\"search-status\">Search failed. Try again.</div>"
            }
            return
        }

        if (requestId !== latestRequestId) {
            return
        }

        renderResults(filterCourseList(courseList, query))
    }

    function filterCourseList(courseList, query) {
        const needle = query.toLowerCase()
        const results = []

        for (const course of courseList) {
            if (sectionId) {
                if (String(course.id) !== String(sectionId)) {
                    continue
                }
            }
            else if ((course.name || "").toLowerCase().includes(needle)) {
                results.push({
                    kind: "course",
                    id: course.id,
                    name: course.name,
                    meta: course.section || course.district || "",
                })
            }

            for (const assignment of course.assignments || []) {
                if ((assignment.name || "").toLowerCase().includes(needle)) {
                    results.push({
                        kind: "assignment",
                        id: assignment.id,
                        courseId: course.id,
                        name: assignment.name,
                        meta: course.name || "",
                    })
                }
            }
        }

        return results.slice(0, 40)
    }

    function renderResults(results) {
        activeIndex = -1

        if (!results.length) {
            const emptyMessage = sectionId ? "No assignments found." : "No courses or assignments found."
            searchResults.innerHTML = `<div class="search-empty">${emptyMessage}</div>`
            return
        }

        searchResults.innerHTML = ""

        if (sectionId) {
            const header = document.createElement("div")
            header.className = "search-scope-header"
            header.textContent = "Only showing results from this course"
            searchResults.appendChild(header)
        }

        for (const item of results) {
            const isCourse = item.kind === "course"

            const row = document.createElement("a")
            row.className = `search-result ${isCourse ? "kind-course" : "kind-assignment"}`
            row.href = isCourse ? `/section/${item.id}` : `/section/${item.courseId}/assignment/${item.id}`

            const kind = document.createElement("span")
            kind.className = "search-result-kind"
            kind.textContent = isCourse ? "Course" : "Assignment"

            const text = document.createElement("div")
            text.className = "search-result-text"

            const name = document.createElement("div")
            name.className = "search-result-name"
            name.textContent = item.name || ""

            const meta = document.createElement("div")
            meta.className = "search-result-meta"
            meta.textContent = item.meta || ""

            text.appendChild(name)
            text.appendChild(meta)
            row.appendChild(kind)
            row.appendChild(text)

            searchResults.appendChild(row)
        }
    }
}