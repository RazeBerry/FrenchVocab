# French Vocabulary LaTeX and Anki Builder

## Table of Contents
1. [Introduction](#introduction)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Usage](#usage)
6. [Features](#features)
7. [Troubleshooting](#troubleshooting)

## Introduction

The **French Vocabulary LaTeX Builder** is a Python application designed to help users create and maintain a LaTeX document for French vocabulary. It leverages AI-powered assistance to generate definitions and examples for French words, formatting them into LaTeX entries and inserting them into a specified file. Additionally, the tool offers seamless export to Anki decks for efficient learning.

## Prerequisites

Before you begin, ensure you have the following installed:

- Python 3.8 or higher
- pip (Python package installer)
- One of the following API keys (depending on provider):
  - Google Gemini (default)
  - Anthropic Claude

### Providers and API Keys

By default the app uses Google Gemini. You can switch providers with `--provider`.

Supported providers:

- Gemini (default): set `GEMINI_API_KEY`
- Claude: set `ANTHROPIC_API_KEY`

You can provide keys via environment variables or let the app prompt and save them to your system keyring on first run.

### Set API key on macOS/Linux

#### macOS

1. Open the Terminal.
2. Run the following command, replacing `your-api-key-here` with your actual API key:

    ```bash
    # For Gemini (default)
    export GEMINI_API_KEY='your-gemini-key-here'
    # or for Claude
    export ANTHROPIC_API_KEY='your-anthropic-key-here'
    ```

3. To make this change permanent, follow these steps:

   a. Open your shell configuration file using nano. Depending on your shell, run one of these commands:
      - For Bash: `nano ~/.bash_profile` or `nano ~/.bashrc`
      - For Zsh: `nano ~/.zshrc`
   
   b. Add one of the following lines to the end of the file:

      ```bash
      export GEMINI_API_KEY='your-gemini-key-here'
      # or
      export ANTHROPIC_API_KEY='your-anthropic-key-here'
      ```

   c. Save the file and exit nano:
      - Press `Ctrl + X`
      - Press `Y` to confirm saving
      - Press `Enter` to keep the same filename

   d. To apply the changes immediately, run the following command in your terminal:

      ```bash
      source ~/.zshrc  # If using Zsh
      ```
      or
      ```bash
      source ~/.bash_profile  # If using Bash
      ```

   This will make the API key available in all new terminal sessions.

### Windows

1. Open **Command Prompt** or **PowerShell**.
2. Run the following command, replacing `your-api-key-here` with your actual API key:

    ```powershell
    setx GEMINI_API_KEY "your-gemini-key-here"
    # or
    setx ANTHROPIC_API_KEY "your-anthropic-key-here"
    ```

3. Restart your Command Prompt or PowerShell to apply the changes.

## Installation

1. **Clone the repository** or download the source code:

    ```bash
    git clone https://github.com/Razeberry/frenchvocab.git
    cd frenchvocab
    ```

2. **Install the required Python packages**:

    ```bash
    pip install -r requirements.txt
    ```

## Configuration

The app can bootstrap your API key on first run. If `GEMINI_API_KEY` or `ANTHROPIC_API_KEY` is not set, it will prompt you and save to your system keyring.

**Automatic LaTeX File Generation**:
    - If the LaTeX file doesn't exist, the program will automatically create it with the necessary structure.
    - The default filename is `FrenchVocab.tex` in the current working directory.


No manual configuration is required for basic usage. The program will guide you through the setup process on its first run.

## Usage

To run the French Vocabulary LaTeX Builder:

1. Open a terminal and navigate to the project directory.
2. Run the script:

    ```bash
    python FrenchVocab.py [path/to/FrenchVocab.tex] [--provider gemini|claude] [--verbose]
    ```

3. Follow the on-screen prompts to add new words, search existing entries, export to Anki decks, or exit the program.

## Features

### 1. Add a New Word
- Enter a French word or short expression.
- The AI will provide:
  - Word type
  - English definitions
  - Example sentences in French with English translations
- The information is formatted into a LaTeX entry and inserted into your file.

### 2. Automatic Alphabetization
- Entries are automatically sorted alphabetically in the LaTeX file.

### 3. Duplicate Handling
- The system checks for duplicates and offers options to skip, view, or force add the entry.

### 4. AI-Powered Assistance
- Uses Gemini by default; Claude available via `--provider claude`.

### 5. **Export to Anki Decks**
- Export your vocabulary list to Anki decks for efficient learning and review.
- **Steps to Export:**
  1. Select the option to export to Anki from the main menu.
  2. Enter a name for your Anki deck when prompted.
  3. The program will generate an `.apkg` file with your vocabulary entries.
  4. The `.apkg` file can be imported directly into Anki.

## Troubleshooting

- API Key Issues: Ensure the correct environment variable is set for the selected provider (`GEMINI_API_KEY` for Gemini, `ANTHROPIC_API_KEY` for Claude).
- **File Not Found Error**: Double-check the path to your LaTeX file in the `main()` function.
- **Unicode Errors**: Make sure your terminal supports UTF-8 encoding for proper display of French characters.
- **Anki Export Errors**: Ensure that the LaTeX file exists and contains valid entries before attempting to export.

For additional help, refer to the [GitHub Issues](https://github.com/Razeberry/frenchvocab/issues) page.

---
