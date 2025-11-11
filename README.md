# Browser History Search for Ulauncher

Search and open entries from Chrome/Chromium history. The
extension auto-detects available Chrome profiles, highlights where a hit came from, and
respects your preferred browser command when opening links.

## Features

- Searches every detected Chrome/Chromium profile (or a custom History path)
- Smart ranking that combines recency, visit count, typed count, and fuzzy matches
- Shows profile labels/icons so you know which browser profile a result belongs to
- Opens URLs via `xdg-open`, Chrome, or any custom command you define

## Installation

Open Ulauncher preferences window > extensions > add extension and paste the following url:

```
https://github.com/vovanmozg/ulauncher-browser-history
```

## Usage

- Trigger Ulauncher and type the keyword you set for the extension (default: `u`).
- Enter a search string; the list updates live, sorted by relevance/recency.
- Press <kbd>Enter</kbd> to open the selected result using your configured browser command.

Keyword is customizable.

## Development

- Enable Ulauncher verbose logs with `ulauncher -v` to inspect extension output.
- Restart Ulauncher after editing the code to reload changes.
  Feel free to open issues or PRs for additional browsers, ranking tweaks, or bug fixes.
