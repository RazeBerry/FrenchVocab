# French Vocabulary LaTeX Builder

## Table of Contents
1. [Introduction](#introduction)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Usage](#usage)
6. [Features](#features)
7. [Troubleshooting](#troubleshooting)

## Introduction

The French Vocabulary LaTeX Builder is a Python application designed to help users create and maintain a LaTeX document for French vocabulary. It uses AI-powered assistance to generate definitions and examples for French words, which are then formatted into LaTeX entries and inserted into a specified file.

## Prerequisites

Before you begin, ensure you have the following installed:

- Python 3.7 or higher
- pip (Python package installer)
- An Anthropic API key for Claude AI integration

## Installation

1. Clone the repository or download the source code:
   ```
   git clone https://github.com/Razeberry/frenchvocab.git
   cd french-vocab
   ```

2. Install the required Python packages:
   ```
   pip install -r requirements.txt 
   ```

## Configuration

The French Vocabulary LaTeX Builder now includes automatic setup and configuration:

1. First-time Setup:
   - When you run the program for the first time, it will prompt you to enter your Anthropic API key.
   - The API key will be saved in a configuration file for future use.

2. Automatic LaTeX File Generation:
   - If the LaTeX file doesn't exist, the program will automatically create it with the necessary structure.
   - The default filename is "FrenchVocab.tex" in the current working directory.

3. Custom LaTeX File Path (Optional):
   - If you want to use a custom path for your LaTeX file, you can specify it when running the script:
     ```
     python frenchvocab.py /path/to/your/custom_file.tex
     ```

No manual configuration is required for basic usage. The program will guide you through the setup process on its first run.

## Usage

To run the French Vocabulary LaTeX Builder:

1. Open a terminal and navigate to the project directory.
2. Run the script:
   ```
   python FrenchVocab.py
   ```
3. Follow the on-screen prompts to add new words, search existing entries, or exit the program.

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
- Utilizes Claude AI to generate accurate definitions and contextual examples.

## Troubleshooting

- **API Key Issues**: Ensure your Anthropic API key is correctly set as an environment variable.
- **File Not Found Error**: Double-check the path to your LaTeX file in the `main()` function.
- **Unicode Errors**: Make sure your terminal supports UTF-8 encoding for proper display of French characters.

