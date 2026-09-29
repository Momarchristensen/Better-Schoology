# Better Schoology

Better Schoology is a lightweight, local Schoology-style course dashboard built with a FastAPI backend and a static HTML frontend.

It provides course browsing, assignment tracking, material viewing, document conversion, and assignment submissions through a local web app.

> **Disclaimer:** Better Schoology is an independent project and is not affiliated with, endorsed by, or sponsored by Schoology or PowerSchool.

## Features

* Schoology account login through the app's authentication flow
* Course and section browsing
* Assignment search
* Upcoming and overdue assignment views
* Material viewing through a local file proxy
* DOCX to HTML conversion
* PPT/PPTX to PDF conversion through the bundled LibreOffice runtime
* Written assignment submissions
* File-based assignment submissions
* Draft saving for written submissions
* Local caching of downloaded files
* Packaged Windows executable

## Preview

<!-- Add a screenshot here, for example: -->

<!-- ![Better Schoology dashboard](docs/preview.png) -->

## Quick Start

### Windows Executable

The packaged Windows version does **not** require Python or Node.js.

1. Open the project's GitHub repository.
2. Select **Releases**.
3. Open the newest release.
4. Download `Better-Schoology.exe` from the **Assets** section.
5. Place the executable in a folder where you want to keep the application.
6. Run `Better-Schoology.exe`.
7. Open `http://localhost:3498` if the browser does not open automatically.
8. Sign in with your Schoology account.

Keep the executable running while using Better Schoology. Closing its console window stops the local server.

> **Important:** Download the executable from the project's **Releases** page rather than from the repository's **Code** menu.

### Windows Security Warning

Windows may display a security warning when running the executable, particularly if the executable is not signed or is not yet recognized by Windows.

If this happens, verify that you obtained the executable from the expected project release before choosing to continue.

## Requirements

### Windows Executable

No additional software is required to run the packaged executable.

### Running from Source

* Windows
* Python 3.10 or newer
* Node.js and npm
* A Schoology account supported by the configured login flow

PowerPoint conversion also requires the bundled LibreOffice runtime.

The project expects LibreOffice to be available at:

```text
libreoffice/program/soffice.exe
```

Keep the `libreoffice/` directory available when using PowerPoint conversion.

## Configuration

Better Schoology creates a `config.json` file automatically the first time it starts.

The location depends on how the application is being run:

| Installation        | Configuration file                      |
| ------------------- | --------------------------------------- |
| Running from Python | Beside `server.py`                      |
| Windows executable  | `%APPDATA%\Better-Schoology\config.json` |

### Schoology Server

The default Schoology server is:

```text
https://ca-net.schoology.com
```

To use a different Schoology server, edit `config.json`:

```json
{
  "schoology_base_url": "https://your-schoology-server.example.com"
}
```

You can copy `config.example.json` as a starting point.

The configured URL must:

* Use HTTPS
* Not contain a query string
* Not contain a URL fragment
* Point to a Schoology server compatible with the application's API and login flow

Restart Better Schoology after changing the configuration.

### Example Configuration

```json
{
  "schoology_base_url": "https://your-schoology-server.example.com"
}
```

## Running from Source

### 1. Create a Virtual Environment

Open PowerShell in the project directory:

```powershell
py -m venv .venv
```

Activate the virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 2. Install Python Dependencies

```powershell
python -m pip install -r requirements.txt
```

### 3. Install Frontend Dependencies

Node.js and npm are required for frontend linting.

```powershell
npm install
```

### 4. Start the Server

```powershell
python server.py
```

Then open:

```text
http://localhost:3498
```

The application runs locally on your computer.

## Data & Storage

Better Schoology runs its web server locally.

### Authentication

The server uses an HTTP-only session cookie for the authenticated session.

### Downloaded Files

Downloaded materials and generated file data are cached locally.

When running from Python, the cache is stored beside `server.py`:

```text
cached_files/
```

When running the packaged Windows executable, the cache is stored separately from the executable:

```text
%TEMP%\Better-Schoology\cached_files\
```

The packaged application's cache persists between normal runs, but Windows may remove files from its temporary directory during system cleanup.

The `cached_files/` directory is ignored by Git.

## Linting

Install the frontend dependencies first:

```powershell
npm install
```

Run the JavaScript/HTML linting:

```powershell
npm run lint
```

Run the CSS linting:

```powershell
npm run lint:css
```

## Project Structure

```text
Better-Schoology/
├── web/                        # Frontend pages and static assets
│   ├── static/                 # CSS, JS, and browser assets
│   └── *.html                  # App pages
├── libreoffice/                # Bundled LibreOffice runtime
├── cached_files/               # Generated local file cache
├── api_utils.py                # Schoology API requests and data helpers
├── get_token.py                # Authentication/session-token handling
├── server.py                   # FastAPI application and route handlers
├── config.example.json         # Example application configuration
├── requirements.txt            # Python dependencies
├── package.json                # Node.js/linting dependencies
└── README.md                   # Project documentation
```

## Architecture

Better Schoology uses a local FastAPI server to connect the frontend with Schoology and provide additional functionality.

```text
                    ┌──────────────────┐
                    │      Browser     │
                    │ HTML / CSS / JS  │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │   FastAPI Server │
                    │    server.py     │
                    └────────┬─────────┘
                             │
            ┌────────────────┼────────────────┐
            │                │                │
            ▼                ▼                ▼
     ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
     │  Schoology  │  │ File Cache  │  │ LibreOffice │
     │     API     │  │             │  │ Conversion  │
     └─────────────┘  └─────────────┘  └─────────────┘
```

The frontend is served as static HTML and assets by the FastAPI application.

The backend handles authentication, Schoology API requests, file proxying, document conversion, caching, and assignment submissions.

## Document Conversion

Better Schoology supports several document-related workflows.

### DOCX

DOCX documents can be converted to HTML for viewing within the application.

### PPT/PPTX

PowerPoint presentations can be converted to PDF using the bundled LibreOffice runtime.

The expected LibreOffice executable is:

```text
libreoffice/program/soffice.exe
```

Do not remove or move the `libreoffice/` directory while using presentation conversion.

## Assignment Submissions

Better Schoology supports:

* Written assignment submissions
* File-based submissions
* Saving drafts for written submissions

Drafts can be saved before the final submission is made.

## Troubleshooting

### The browser does not open automatically

Start Better Schoology and manually open:

```text
http://localhost:3498
```

Make sure the Better Schoology executable or Python server is still running.

### The local website does not load

Check that the server is running and that port `3498` is not already being used by another application.

When running from source, start the server with:

```powershell
python server.py
```

### PowerPoint conversion does not work

Verify that this file exists:

```text
libreoffice/program/soffice.exe
```

The complete `libreoffice/` directory must remain available to the application.

### The Schoology login does not work

Check that:

1. Your Schoology account is supported by the configured login flow.
2. The configured Schoology server is correct.
3. `schoology_base_url` uses HTTPS.
4. The application has been restarted after changing `config.json`.

### I changed the Schoology server but the old server is still being used

Make sure you edited the correct configuration file.

For the Python version:

```text
<project directory>\config.json
```

For the packaged executable:

```text
%APPDATA%\Better-Schoology\config.json
```

Restart Better Schoology after making the change.

### Windows deleted cached files

The packaged version stores cached files under:

```text
%TEMP%\Better-Schoology\cached_files\
```

Because this is a Windows temporary directory, Windows may periodically remove its contents.

## Development

The project contains both Python backend code and frontend assets.

### Backend

The backend is built with FastAPI and handles:

* Schoology API communication
* Authentication
* Session handling
* File proxying
* File caching
* Document conversion
* Assignment submissions

### Frontend

The frontend is made from static HTML, CSS, and JavaScript.

Node.js and npm are used for linting and frontend development tooling.

## Contributing

Contributions, bug reports, and suggestions are welcome.

Before submitting changes, make sure the relevant linting commands pass:

```powershell
npm run lint
npm run lint:css
```

For bugs, include enough information to reproduce the problem, such as:

* What you were trying to do
* What happened
* What you expected to happen
* Relevant error messages
* Whether you were using the Python version or Windows executable

Do not include passwords, session tokens, authentication cookies, or other private account information in bug reports.

## Disclaimer

Better Schoology is an independent project.

It is not affiliated with, endorsed by, or sponsored by Schoology or PowerSchool.

Users are responsible for complying with the policies and terms applicable to their Schoology account and institution.

## License

This project is licensed under the terms specified in the repository's `LICENSE` file.
