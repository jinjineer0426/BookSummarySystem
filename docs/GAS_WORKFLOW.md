# GAS Integration Workflow

This document explains how to sync your local code with Google Apps Script (GAS) and enable automatic deployment via GitHub Actions.

## Prerequisites

1.  **Enable Apps Script API**: Go to [script.google.com/home/usersettings](https://script.google.com/home/usersettings) and switch the "Google Apps Script API" to **ON**.
2.  **Node.js**: Ensure you have Node.js installed.

## Local Setup

1.  **Install Dependencies**:
    ```bash
    npm install
    ```

2.  **Login to Google**:
    ```bash
    npx clasp login
    ```
    This will open a browser window for authentication.

3.  **Link your Script ID**:
    Open `.clasp.json` in the root and replace `YOUR_SCRIPT_ID_HERE` with your GAS Script ID.
    *   *Where to find Script ID*: GAS Editor -> Project Settings (gear icon) -> Script ID.

4.  **Initial Push**:
    ```bash
    npm run push
    ```
    This syncs your local `gas/` folder to Google Apps Script.

## Automatic Deployment (CI/CD)

To automatically deploy when pushing to GitHub:

1.  **Get `.clasprc.json` content**:
    After logging in locally, find the file at `~/.clasprc.json` (Mac/Linux).
    ```bash
    cat ~/.clasprc.json
    ```

2.  **Add GitHub Secret**:
    Go to your GitHub Repository -> **Settings** -> **Secrets and variables** -> **Actions** -> **New repository secret**.
    *   Name: `CLASPRC_JSON`
    *   Secret: (Paste the entire content of `~/.clasprc.json`)

## Usage

*   **Pull changes** (if you edited code in the browser): `npm run pull`
*   **Push changes**: `npm run push`
*   **Watch for changes**: `npm run watch` (Automatically pushes every time you save a file)
