import json
import os
from urllib.parse import parse_qs, unquote, urlparse, urljoin
import re
from bs4 import BeautifulSoup, Comment
import httpx
import asyncio
from pathlib import Path
import time
from config import base_url

script_dir = Path(__file__).resolve().parent

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)

async_client = httpx.AsyncClient(
    http2=True,
    verify=False,
    follow_redirects=True,
    headers=headers,
    limits=limits,
    timeout=10.0,
    trust_env=False,
)


async def request_single(session_token, url):
    print("Requesting:", url)
    async_client.cookies.update(session_token)
    while True:
        try:
            response = await async_client.get(url)
            if response.status_code == 429:
                await asyncio.sleep(0.5)
                continue
            return response

        except (httpx.TimeoutException, httpx.RemoteProtocolError, httpx.ProxyError):
            await asyncio.sleep(0.25)


async def request_data(session_token, url_list):
    print("Requesting:", url_list)
    async_client.cookies.update(session_token)

    async def fetch(url):
        try:
            response = await async_client.get(url)
            if response.status_code == 429:
                await asyncio.sleep(0.5)
                return await fetch(url)

            response.raise_for_status()
            return response.json()

        except (httpx.TimeoutException, httpx.RemoteProtocolError, httpx.ProxyError):
            await asyncio.sleep(0.25)
            return await fetch(url)

    tasks = [fetch(url) for url in url_list]
    return await asyncio.gather(*tasks, return_exceptions=True)


async def get_file(session_token, url):
    resp = await request_single(session_token, url)
    return resp.content


async def get_json(session_token, url):
    resp = await request_single(session_token, url)
    return resp.json()


async def get_course(session_token, section):
    return await get_json(session_token, section["@links"]["course"]["@id"])


def get_section_materials_url(section_id, folder_id=None):
    url = f"{base_url}/v2/sections/{section_id}"

    if folder_id:
        url += f"/folders/{folder_id}"

    url += "/materials"

    return url

async def get_section_materials(session_token, section_id, folder_id=None):
    url = get_section_materials_url(section_id, folder_id)

    materials_resp = await get_json(
        session_token, url
    )
    materials_list = materials_resp["@items"]

    urls = [material["@id"] for material in materials_list]


    if "@extra" in materials_resp:
        materials = []
        extras = materials_resp["@extra"]

        for extra in extras:
            if extra["@id"] in urls:
                materials.append(extra)
    else:
        materials = await request_data(session_token, urls)


    return await resolve_materials_list(session_token, materials)

async def get_parent_structure(session_token, section_id, folder_id):
    structure = []
    current_folder_id = folder_id

    while True:
        folder_url = f"{base_url}/v2/sections/{section_id}/folders/{current_folder_id}"
        folder = await get_json(session_token, folder_url)

        parent_id = folder.get("@links", {}).get("parent", {}).get("@id")
        parent_id = parent_id.split("/")[-1] if parent_id else None

        if not parent_id:
            break

        structure.append(folder)


        current_folder_id = parent_id

    structure.reverse()
    return structure


async def get_assignment_location(session_token, section_id,assignment_id):
    url = f"{base_url}/v2/sections/{section_id}/assignments/{assignment_id}"
    material = await get_json(session_token, url)

    parent_id = material["@links"]["parent"]["@id"]

    if "folders" in parent_id:
        folder_id = parent_id.split("/")[-1]
    else:
        folder_id = "root"    
        


    return section_id, folder_id, assignment_id

async def get_material(session_token, section_id, folder_id, material_id):
    url = get_section_materials_url(section_id, folder_id)
    materials_resp = await get_json(session_token, url)
    materials_list = materials_resp["@items"]

    target_id = None
    for material_obj in materials_list:
        if material_obj["@id"].split("/")[-1] == material_id:
            target_id = material_obj["@id"]
            break

    if target_id is None:
        return None

    material = None
    if "@extra" in materials_resp:
        for extra in materials_resp["@extra"]:
            if extra["@id"] == target_id:
                material = extra
                break

    if material is None:
        material = await get_json(session_token, target_id)

    return await resolve_full_material(session_token, material)


async def resolve_material(session_token, material):
    material_url = material["@id"]
    full_material = await get_json(session_token, material_url)
    return await resolve_full_material(session_token, full_material)


async def resolve_full_material(session_token, material):
    material_types = material["@type"]
    if "sgy:Document" in material_types:
        material_object = await resolve_full_document(session_token, material)
    elif "sgy:Page" in material_types:
        material_object = await resolve_full_page(session_token, material)
    elif "sgy:Assignment" in material_types:
        material_object = await resolve_full_assignment(session_token, material)
    elif "sgy:Discussion" in material_types:
        material_object = await resolve_full_discussion(session_token, material)
    else:
        print(material)
        raise Exception(f"Unhandled type: {material_types}")

    material_object["type"] = get_material_type(material)

    material_object["id"] = material["@id"].split("/")[-1]
    material_object["parent"] = get_material_parent(material)

    return material_object

def get_material_parent(material):
    links = material.get("@links", {})
    if "parent" in links:
        parent_url = links["parent"]["@id"]
        #Example: {base_url}/v2/sections/8467781195, {base_url}/v2/sections/8467779869/folders/1018170923
        parsed = urlparse(parent_url)
        path_segments = parsed.path.strip("/").split("/")

        return {
            "section_id": path_segments[2] if len(path_segments) > 2 else None,
            "folder_id": path_segments[4] if len(path_segments) > 4 else None
        }
    else:
        return None


async def resolve_discussion(session_token, material_url):
    material = await get_json(session_token, material_url)
    return await resolve_full_discussion(session_token, material)


async def resolve_full_discussion(session_token, material):
    material_object = resolve_graded_material(material)
    material_object["assignmentType"] = "discussion"
    dump_json(material)
    return material_object


def parse_html(text):
    return BeautifulSoup(text, "lxml")


async def get_course_completion(course_id):
    url = f"https://ca-net.schoology.com/course/{course_id}/materials"
    html = await get_html(url)

    completion_element = html.find("a", id="folder-completion-status")
    if not completion_element:
        return None

    completion_url = base_url + completion_element.get("href")
    completion_html = await get_html(completion_url)

    folders = []
    for li in completion_html.select("li.folder-item"):
        header = li.find("div", class_="item-content", recursive=False)
        if not header:
            continue

        title_element = header.find("div", class_="folder-title")
        percent_element = header.find("div", class_="status")
        if not title_element or not percent_element:
            continue

        folders.append({
            "id": li["id"].removeprefix("folder-"),
            "name": title_element.get_text(strip=True),
            "percent": int(percent_element.get_text(strip=True).rstrip("%")),
        })

    return folders


def resolve_graded_material(material):
    material_object = {}
    if "description" in material:
        soup = parse_html(material["description"])

        for tag in soup(["script", "style", "iframe", "object", "embed", "base"]):
            tag.decompose()


        print(soup)
        material_object["description"] = str(soup)


    
    material_object["category"] = material["category"]
    material_object["submitted"] = material["submitted"]
    if "dueDateInUTCISO" in material:
        material_object["dueDate"] = material["dueDateInUTCISO"]
    else:
        material_object["dueDate"] = None
    material_object["title"] = material["title"]
    material_object["canBeTurnedIn"] = material["memberCanEngage"]

    if "studentGrade" in material:
        if "exception" in material["studentGrade"]:
            grade_exception = material["studentGrade"]["exception"]
            exception_dict = {
                1: "exempt",
                2: "incomplete",
                3: "missing",
                4: "collected",
                6: "late",
            }
            if grade_exception not in exception_dict:
                print(material)
                raise Exception(f"Unhandled assignment exception: {grade_exception}")
            material_object["gradeException"] = exception_dict[grade_exception]

        if "grade" in material["studentGrade"]:
            material_object["grade"] = material["studentGrade"]["grade"]

        if "gradeComment" in material["studentGrade"]:
            material_object["comment"] = material["studentGrade"]["gradeComment"]

    if "maxPoints" in material:
        material_object["maxPoints"] = material["maxPoints"]

    return material_object





async def resolve_assignment(session_token, material_url):
    material = await get_json(session_token, material_url)
    return await resolve_full_assignment(session_token, material)


async def resolve_full_assignment(session_token, material):
    material_types = material["@type"]

    material_object = resolve_graded_material(material)

    if "submissions" in material:
        submissions = []
        material_object["submissions"] = submissions

        revisions = material["submissions"]["revisions"]
        for revision in revisions:
            is_draft = revision["isDraft"]

            is_late = revision["isLate"]
            id = revision["revisionId"]

            if is_draft:
                if "sgy:AnnotationAssignment" in material_types:
                    view_url = material["submissions"]["viewUrl"]
                    assignment_id = view_url.split("/assignment/")[1].split("/dropbox")[
                        0
                    ]
                    annotation_assignment = await get_json(
                        session_token,
                        material["@links"]["annotationAssignmentActions"]["@id"],
                    )
                    actions = annotation_assignment["@actions"]
                    for action in actions:
                        if "assignment:getAnnotations" in action["@type"]:
                            annotations_url = action["@href"]
                            draft_url = re.sub(
                                r"/\d+/(?=\d+\.xml)",
                                f"/{assignment_id}/",
                                annotations_url,
                            )
                            submissions.append(
                                {
                                    "type": "annotation_draft",
                                    "fileUrl": annotations_url,
                                    "late": is_late,
                                    "id": id,
                                    "draft": is_draft,
                                }
                            )
                else:
                    view_url = material["submissions"]["viewUrl"]
                    draft_url = re.sub(r"view/.*", "submit", view_url)
                    assignment_id = view_url.split("/assignment/")[1].split("/dropbox")[
                        0
                    ]

                    html = await get_html(session_token, draft_url)
                    textarea = html.find("textarea", id="edit-submission")

                    text = textarea.get_text()

                    submissions.append(
                        {
                            "type": "draft",
                            "draft_html": text,
                            "late": is_late,
                            "id": id,
                            "draft": is_draft,
                        }
                    )
                continue

            attachments = revision["attachments"]

            for attachment in attachments:
                type = attachment["type"]
                if type == "file":
                    if "sgy:AnnotationAssignment" in material_types:
                        view_url = material["submissions"]["viewUrl"]
                        viewer_html = await get_html(
                            session_token,
                            f"{view_url}?revision={revision["revisionId"]}",
                        )
                        docviewer_id = viewer_html.find(
                            "select", id="dropbox-viewer-item-select"
                        ).find("option", selected=True)["value"]
                        docviewer_url = f"{base_url}/submission/{docviewer_id}/docviewer"
                        docviewer_html = await get_html(session_token, docviewer_url)
                        wrapper = docviewer_html.find("div", id="content-wrapper")

                        script_tag = wrapper.find("script")

                        js_code = script_tag.string or script_tag.get_text()

                        pdf_path = re.search(r'"pdfPath":\s*"([^"]+)"', js_code).group(
                            1
                        )
                        annotations_url = pdf_path.replace("\\/", "/")
                        submissions.append(
                            {
                                "type": "annotation",
                                "fileUrl": annotations_url,
                                "late": is_late,
                                "id": id,
                            }
                        )
                    else:
                        file_url = f"{base_url}{attachment["downloadUrl"]}".replace(
                            "/attachment/", "/submission/"
                        )
                        submissions.append(
                            {
                                "type": "attachment",
                                "fileUrl": file_url,
                                "late": is_late,
                                "id": id,
                            }
                        )
                else:
                    raise Exception("Unhandled submission")

    if len(material_types) == 2:
        # normal assignment
        material_object["assignmentType"] = "default"
    elif "sgy:AnnotationAssignment" in material_types:
        material_object["assignmentType"] = "annotation"
    elif "sgy:LtiAssignment" in material_types:
        material_object["assignmentType"] = "document"
        html = await get_html(session_token, material["url"] + "/mydocument")
        scripts = html.find_all("script")

        target_script = None
        for script in scripts:
            if script.string and "jQuery.extend(Drupal.settings, {" in script.string:
                target_script = script
                break

        script_lines = target_script.string.split("\n")
        json_str = script_lines[2][31:-2]

        data = json.loads(json_str)
        print(data)
        html = await get_html(
            session_token, base_url + list(data["s_app"]["launcher"].values())[0]["url"]
        )
        print(html)

        form = html.find("form")
        action_url = form["action"]

        data = {}
        for inp in form.find_all("input"):
            title = inp.get("name")
            value = inp.get("value", "")
            if title:
                data[title] = value

        response = await async_client.post(action_url, data=data)

        html = parse_html(response)
        iframe = html.find("iframe")
        src = iframe.get("src")

        material_object["documentUrl"] = src
    else:
        print(material)
        raise Exception(f"Unhandled assignment: {material_types}")

    if "attachments" in material:
        attachments = []
        material_object["attachments"] = attachments
        for attachment in material["attachments"]:
            if attachment["type"] == "link":
                title = attachment["title"]
                url = attachment["viewUrl"]
                attachments.append({"type": "link", "title": title, "url": url})
            elif attachment["type"] == "file":
                title = attachment["title"]
                url = f"{base_url}{attachment['downloadUrl']}"
                extension = os.path.splitext(urlparse(url).path)[1].lstrip(".")
                attachments.append(
                    {"type": "file", "title": title, "url": url, "extension": extension}
                )
            elif attachment["type"] == "annotation_file":
                pass
            else:
                raise Exception(f"Unhandled attachment type: {attachment}")

    return material_object



async def resolve_document(session_token, material_url):
    material = await get_json(session_token, material_url)
    return await resolve_full_document(session_token, material)


async def resolve_full_document(session_token, material):
    material_types = material["@type"]

    material_object = {}
    if "title" not in material:
        print(material)
    material_object["title"] = material["title"]
    material_object["submitted"] = material["submitted"]

    if "sgy:Link" in material_types:
        soup = await get_html(session_token, material["url"])
        page_title = soup.find(["h1", "h2"], class_="page-title")
        link = page_title.find("a", href=True)

        if not link:
            attachments = soup.find("div", class_="attachments")
            link = attachments.find("a", href=True)

        parsed = urlparse(link["href"])
        query_params = parse_qs(parsed.query)
        linked_url = unquote(query_params["path"][0])
        material_object["url"] = linked_url
        material_object["documentType"] = "link"
    elif "sgy:ExternalTool" in material_types:
        linked_url = f"{material["url"]}/iframe"
        material_object["url"] = linked_url
        material_object["documentType"] = "link"
    elif "sgy:File" in material_types:
        soup = await get_html(session_token, material["url"])
        material_object["documentType"] = "file"
        image_extensions = ["png", "jpeg", "jpg"]
        attachment_extensions = ["pdf", "docx", "heic", "pptx", "ppt"]
        video_extensions = ["mp4"]

        if material["fileExtension"] in image_extensions:
            wrapper = soup.find("div", id="content-wrapper")
            image = wrapper.find("img")
            file_url = f"{base_url}{image["src"]}"
            material_object["fileUrl"] = file_url
            material_object["extension"] = material["fileExtension"]
        elif material["fileExtension"] in attachment_extensions:
            attachments = soup.find("span", class_="attachments-file-name")
            view_file = attachments.find(
                "a",
                attrs={
                    "class": lambda courses: courses is None
                    or "view-file-popup" not in courses
                },
            )

            file_url = f"{base_url}{view_file["href"]}"
            material_object["fileUrl"] = file_url
            material_object["extension"] = material["fileExtension"]
        elif material["fileExtension"] in video_extensions:
            iframe = soup.find("iframe", class_="s-media-iframe")
            player_url = f"{base_url}{iframe['src']}"

            player_soup = await get_html(session_token, player_url)

            video = player_soup.find("video", class_="media__video-player")
            video_url = f"{base_url}{video.find('source')['src']}"
            material_object["fileUrl"] = video_url
            material_object["extension"] = material["fileExtension"]
        else:
            print(material)
            raise Exception("Unhandled file")
    elif "sgy:Video" in material_types:
        linked_url = material["url"]
        material_object["url"] = linked_url
        material_object["documentType"] = "video"
    elif "sgy:Embed" in material_types:
        soup = await get_html(session_token, material["url"])
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            if "<iframe" in comment:
                iframe_soup = parse_html(comment)
                iframe = iframe_soup.find("iframe")
                if iframe and iframe.has_attr("src"):
                    linked_url = iframe["src"]
                    material_object["url"] = linked_url
                    material_object["documentType"] = "link"
    else:
        print(material)
        raise f"Unhandled document: {material_types}"

    return material_object



async def get_draft_text(session_token, assignment_id):
    """Fetch the current draft's raw text from the dropbox submit page, if one exists."""
    async_client.cookies.update(session_token)
    form_page_url = f"{base_url}/assignment/{assignment_id}/dropbox/submit"
    extra_headers = {
        "Referer": f"{base_url}/assignment/{assignment_id}/info",
        "Origin": base_url,
    }
    r = await async_client.get(form_page_url, headers=extra_headers)
    r.raise_for_status()
    soup = parse_html(r.text)

    textarea = soup.find("textarea", id="edit-submission")
    if textarea is None:
        # fallback any textarea named "submission" inside the create form
        textarea = soup.find("textarea", {"name": "submission"})

    if textarea is None:
        return None

    return textarea.get_text()






def _to_bool(value) -> bool:
    """The API represents booleans as the strings '0' / '1'."""
    return str(value).strip() == "1"

"""
Fetches the raw "smart search" payload and reformats it into a compact,
readable structure: a dict of courses keyed by course id, each holding
its own list of assignments (instead of one flat list where every
assignment row repeats the course name/period as strings).
"""
def reformat_search_list(raw_items: list[dict]) -> dict:
    """
    Turn the flat raw_items list (courses + assignments + trailing
    group markers) into:

    {
        "courses": {
            "<course_id>": {
                "id": int,
                "name": str,
                "section": str,
                "district": str,
                "assignments": [
                    {
                        "id": int,
                        "name": str,
                        "due": str | None,
                        "posted": bool,
                        "has_attachment": bool,
                    },
                    ...
                ],
            },
            ...
        }
    }

    Runs in a single O(n) pass using a dict keyed by course id so
    assignments attach to their course without any nested lookups.
    """
    courses: dict[str, dict] = {}

    for item in raw_items:
        item_type = item.get("t")

        if item_type == "c":
            course_id = str(item["i"])
            courses[course_id] = {
                "id": int(course_id),
                "name": item.get("n1", ""),
                "section": item.get("n2", ""),
                "district": item.get("n3", ""),
                "assignments": [],
            }

        elif item_type == "a":
            course_id = str(item.get("c"))
            course = courses.setdefault(
                course_id,
                {
                    "id": int(course_id) if course_id.isdigit() else course_id,
                    "name": item.get("n3", ""),
                    "section": item.get("n4", ""),
                    "district": "",
                    "assignments": [],
                },
            )
            course["assignments"].append(
                {
                    "id": int(item["i"]),
                    "name": item.get("n1", ""),
                    "due": item.get("d"),
                    "posted": _to_bool(item.get("p")),
                    "has_attachment": _to_bool(item.get("ha")),
                }
            )

        # item_type in {"gp", "gc", "gg"} are trailing group markers
        # with no useful data here, so they're skipped.

    return {"courses": courses}


async def get_search_list(session_token: str) -> dict:
    search_list = await get_json(session_token, f"{base_url}/ajaxsearch/smart")
    return reformat_search_list(search_list)


async def resolve_page(session_token, material_url):
    material = await get_json(session_token, material_url)
    return await resolve_full_page(session_token, material)


async def resolve_full_page(session_token, material):
    material_object = {}
    description_soup = parse_html(material["description"])

    # Remove <base> tags so they don't hijack relative URL resolution
    # for the rest of the page once this description is embedded.
    for base_tag in description_soup.find_all("base"):
        base_tag.decompose()

    links = []
    for link in description_soup.find_all("a", href=True):
        links.append(link["href"])

    iframes = []
    for iframe in description_soup.find_all("iframe", src=True):
        iframes.append(iframe["src"])

    for image in description_soup.find_all("img", src=True):
        links.append(image["src"])

    material_object["description"] = str(description_soup)

    material_object["links"] = links
    material_object["iframes"] = iframes
    material_object["title"] = material["title"]
    soup = await get_html(session_token, material["url"])
    attachments = soup.find_all("span", class_="attachments-file-name")
    for attachment in attachments:
        view_file = attachment.find(
            "a",
            attrs={
                "class": lambda courses: courses is None
                or "view-file-popup" not in courses
            },
        )

        file_url = f"{base_url}{view_file['href']}"
        material_object["fileUrl"] = file_url

    return material_object


async def get_html(session_token, url):
    resp = await request_single(session_token, url)
    return parse_html(resp.text)


async def get_section(session_token, section_id):
    url = f"{base_url}/v2/sections/{section_id}"

    section = await get_json(session_token, url)
    if not section.get("data", "no-data"):
        return None

    course = await get_course(session_token, section)

    title = course["title"] + " - " + section["title"]
    user_course = {
            "title": title,
            "subject": section["subjectArea"],
            "logo": section["logoImageUrl"],
            "hasMaterials": section["hasMaterials"],
        }

    return user_course

PARENT_LINK_TTL_SECONDS = 15 * 60 


class TTLCache:
    """Minimal in-memory TTL cache (single event loop, so no locking needed)."""

    def __init__(self, ttl_seconds, max_size=10_000):
        self.ttl = ttl_seconds
        self.max_size = max_size
        self._data = {} 

    def get(self, key):
        entry = self._data.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= time.monotonic():
            del self._data[key]
            return None
        return value

    def set(self, key, value):
        if len(self._data) >= self.max_size:
            self._evict()
        self._data[key] = (time.monotonic() + self.ttl, value)

    def invalidate(self, key=None):
        if key is None:
            self._data.clear()
        else:
            self._data.pop(key, None)

    def _evict(self):
        now = time.monotonic()
        self._data = {k: v for k, v in self._data.items() if v[0] > now}
        if len(self._data) >= self.max_size:
            for k, _ in sorted(self._data.items(), key=lambda kv: kv[1][0])[: self.max_size // 10 or 1]:
                del self._data[k]


_parent_link_cache = TTLCache(PARENT_LINK_TTL_SECONDS)


async def _get_events_materials(session_token, kind, section_id=None):
    url = f"{base_url}/v2/events/{kind}"
    if section_id:
        url += f"?section={section_id}"

    resp = await get_json(session_token, url)

    items = resp["@items"]
    extras_by_id = {extra["@id"]: extra for extra in resp.get("@extra", {})}
    ids = [item["@id"] for item in items if item["@id"] in extras_by_id]

    missing_ids = []
    for material_id in ids:
        parent = _parent_link_cache.get(material_id)
        if parent is not None:
            extras_by_id[material_id].setdefault("@links", {})["parent"] = parent
        else:
            missing_ids.append(material_id)

    # Only fetch full material JSON for cache misses (the @extra payload
    # has a buggy "parent" link, so we need the real one).
    if missing_ids:
        fetched = await request_data(session_token, missing_ids)

        for material_id, full_material in zip(missing_ids, fetched):
            if isinstance(full_material, Exception):
                raise full_material
            parent = full_material.get("@links", {}).get("parent")
            if parent is not None:
                extras_by_id[material_id].setdefault("@links", {})["parent"] = parent
                _parent_link_cache.set(material_id, parent)

    return await asyncio.gather(
        *(resolve_full_material(session_token, extras_by_id[mid]) for mid in ids)
    )


async def get_overdue_materials(session_token, section_id=None):
    return await _get_events_materials(session_token, "overdue", section_id)


async def get_upcoming_materials(session_token, section_id=None):
    return await _get_events_materials(session_token, "upcoming", section_id)
async def resolve_materials_list(session_token, materials):
    resolved_materials = []
    for material in materials:
        if isinstance(material, Exception):
            raise material

        is_folder = "sgy:Folder" in material["@type"]
        
        if is_folder:
            material_object = await resolve_full_folder(session_token, material)
        else:
            material_object = {}

            material_object["parent"] = get_material_parent(material)

            material_object["title"] = material["title"]

        material_object["type"] = get_material_type(material)

        material_object["id"] = material["@id"].split("/")[-1]

        resolved_materials.append(material_object)

    return resolved_materials


async def resolve_full_folder(session_token, material):
    material_object = {}
    material_object["title"] = material["title"]
    material_object["description"] = material.get("description", "")
    material_object["id"] = material["@id"].split("/")[-1]
    if "color" in material:
        material_object["folderColor"] = material["color"]

    return material_object

def get_material_type(material):
    type_list = material["@type"]
    if "sgy:Folder" in type_list:
        return "folder"
    elif "sgy:Assignment" in type_list:
        return "assignment"
    elif "sgy:Discussion" in type_list:
        return "discussion"
    elif "sgy:Page" in type_list:
        return "page"
    elif "sgy:Document" in type_list:
        return "document"
    else:
        print(material)
        raise Exception(f"Unhandled material type: {type_list}")


def get_id(url):
    return url.split("/")[-1]


async def get_sections(session_token):
    section_resp = await get_json(session_token, f"{base_url}/v2/sections")
    section_url_list = section_resp.get("@items", [])
    extra_list = section_resp.get("@extra", {})
    user_course_list = []
    for section_obj in section_url_list:
        section = None
        course = None

        for extra in extra_list:
            if extra["@id"] == section_obj["@id"]:
                section = extra

        if section is None:
            section = await get_json(session_token, section_obj["@id"])

        for extra in extra_list:
            if extra["@id"] == section["@links"]["course"]["@id"]:
                course = extra

        if course is None:
            course = await get_course(session_token, section)

        title = course["title"] + " - " + section["title"]
        user_course = {
            "title": title,
            "subject": section["subjectArea"],
            "logo": section["logoImageUrl"],
            "hasMaterials": section["hasMaterials"],
            "id": get_id(section_obj["@id"]),
        }
        user_course_list.append(user_course)

    return user_course_list


async def save_draft(session_token, assignment_id, submission):
    async_client.cookies.update(session_token)

    form_page_url = f"{base_url}/assignment/{assignment_id}/dropbox/submit"
    extra_headers = {
        "Referer": f"{base_url}/assignment/{assignment_id}/info",
        "Origin": base_url,
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }

    r_get = await async_client.get(form_page_url, headers=extra_headers)
    r_get.raise_for_status()
    soup = parse_html(r_get.text)
    form = soup.find("form", id="s-drop-item-submit-create-form")
    if form is None:
        raise RuntimeError(
            "Could not find the submission form on the page. Are you logged in?"
        )

    form_action = form.get("action") or form_page_url
    form_data = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        form_data[name] = inp.get("value", "")

    form_data["submission"] = submission
    form_data["op"] = "Save Draft"
    form_data.setdefault("form_origin_popups", "1")

    post_url = urljoin(form_page_url, form_action)
    resp = await async_client.post(post_url, data=form_data, headers=extra_headers)

    return resp


async def submit_assignment(session_token, assignment_id, submission):
    """
    Submit (final submit) an assignment on Schoology.
    - Expects a `session_token` cookie dict, applied to the shared async_client.
    - Performs: GET the form page -> extract hidden tokens -> POST with op="Submit".
    - Returns the httpx.Response from the POST (inspect .status_code / .text / .json()).
    """
    async_client.cookies.update(session_token)

    form_page_url = f"{base_url}/assignment/{assignment_id}/dropbox/submit"
    extra_headers = {
        "Referer": f"{base_url}/assignment/{assignment_id}/info",
        "Origin": base_url,
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }

    r_get = await async_client.get(form_page_url, headers=extra_headers)
    r_get.raise_for_status()
    soup = parse_html(r_get.text)
    form = soup.find("form", id="s-drop-item-submit-create-form")
    if form is None:
        raise RuntimeError(
            "Could not find the submission form on the page. Are you logged in?"
        )

    form_action = form.get("action") or form_page_url
    form_data = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        form_data[name] = inp.get("value", "")

    ta = form.find("textarea", {"name": "submission"})
    if ta is not None:
        form_data["submission"] = ta.text
    form_data["submission"] = submission

    form_data["op"] = "Submit"
    form_data.setdefault("form_origin_popups", "1")

    post_url = urljoin(form_page_url, form_action)
    resp = await async_client.post(post_url, data=form_data, headers=extra_headers)

    return resp


async def delete_draft(session_token, assignment_id, revision_id):
    # matches the URL pattern: .../revision_delete/{revision_id}?destination=assignment%2F{assignment_id}%2Finfo
    async_client.cookies.update(session_token)

    page_url = (
        f"{base_url}/assignment/{assignment_id}/dropbox/revision_delete/{revision_id}"
        f"?destination=assignment%2F{assignment_id}%2Finfo"
    )
    extra_headers = {
        "Referer": f"{base_url}/assignment/{assignment_id}/info",
        "Origin": base_url,
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }

    r_get = await async_client.get(page_url, headers=extra_headers)
    r_get.raise_for_status()

    content = None
    ct = r_get.headers.get("Content-Type", "")
    if "application/json" in ct:
        j = r_get.json()
        content = j.get("content") or j.get("html") or r_get.text
    else:
        content = r_get.text

    soup = parse_html(content)
    form = soup.find("form", id="s-drop-item-revision-delete-form")

    # fallback find a form containing the delete form_id hidden input
    if form is None:
        for f in soup.find_all("form"):
            inp = f.find("input", {"name": "form_id"})
            if inp and inp.get("value") == "s_drop_item_revision_delete_form":
                form = f
                break

    if form is None:
        raise RuntimeError(
            "Could not find the revision-delete form on the page. Are you logged in?"
        )

    form_action = form.get("action") or page_url
    form_data = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        form_data[name] = inp.get("value", "")

    form_data["op"] = "Submit"
    form_data.setdefault("form_origin_popups", "1")

    post_url = urljoin(page_url, form_action)
    resp = await async_client.post(post_url, data=form_data, headers=extra_headers)

    return resp


async def get_upload_token(session_token):
    async_client.cookies.update(session_token)
    r = await async_client.get(f"{base_url}/uploads/token")
    r.raise_for_status()
    return r.json()["data"]["token"]


def dump_html(html: str, filename: str = "debug.html"):
    path = script_dir / filename
    path.write_text(html, encoding="utf-8")
    print(f"Dumped HTML to {path}")

def dump_json(obj, filename: str = "debug.json"):
    path = script_dir / filename
    path.write_text(json.dumps(obj, indent=4), encoding="utf-8")
    print(f"Dumped JSON to {path}")

async def submit_assignment_files(session_token, assignment_id, files, comment=""):
    async_client.cookies.update(session_token)

    upload_url = f"{base_url}/file/upload-service"
    form_page = f"{base_url}/assignment/{assignment_id}/dropbox/submit"
    extra_headers = {
        "Referer": f"{base_url}/assignment/{assignment_id}/info",
        "Origin": base_url,
    }


    uploaded = {}

    for f in files:
        name = f["file_name"]
        title = f.get("title", name)
        content = f["file_content"]

        token = await get_upload_token(session_token)
        upload_headers = {**extra_headers, "Authorization": f"Bearer {token}"}
        multipart = {
            "name": (None, name),
            "use_plain": (None, "1"),
            "file": (name, content, "application/octet-stream"),
        }

        r = await async_client.post(upload_url, files=multipart, headers=upload_headers)
        r.raise_for_status()

        file_id = r.json()["fileMetadataId"]

        uploaded[file_id] = {
            "title": title,
            "encode": True,
        }


    r = await async_client.get(form_page, headers=extra_headers)
    r.raise_for_status()


    soup = parse_html(r.text)
    form = soup.find("form", id="s-drop-item-submit-upload-form")

    if not form:
        raise RuntimeError("Upload form not found")

    tokens = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if name:
            tokens[name] = inp.get("value", "")


    fields = {
        "target_DOM_id": tokens.get("target_DOM_id", ""),
        "sid": tokens.get("sid", ""),
        "file[files]": json.dumps(uploaded),
        "file[recording]": "",
        "annotation_files": "",
        "drop_item_comment": comment,
        "op": "Submit",
        "form_build_id": tokens["form_build_id"],
        "form_token": tokens["form_token"],
        "form_id": "s_drop_item_submit_upload_form",
        "form_origin_popups": "1",
    }

    multipart = [(k, (None, str(v))) for k, v in fields.items()]

    action = form.get("action") or form_page
    submit_url = urljoin(form_page, action)

    resp = await async_client.post(submit_url, files=multipart, headers=extra_headers)

    return resp