# French Vocabulary LaTeX Builder

## Table of Contents
1. [Introduction](#introduction)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Usage](#usage)
6. [Features](#features)
7. [Troubleshooting](#troubleshooting)
8. [Contributing](#contributing)
9. [License](#license)

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
   git clone https://github.com/yourusername/french-vocab-builder.git
   cd french-vocab-builder
   ```

2. Install the required Python packages:
   ```
   pip install anthropic rich
   ```

## Configuration

1. Set up your Anthropic API key:
   - Create an environment variable named `ANTHROPIC_API_KEY` with your API key:
     ```
     export ANTHROPIC_API_KEY='your-api-key-here'
     ```
   - Alternatively, you can modify the script to use a configuration file or input the API key manually.

2. Specify the path to your LaTeX file:
   - Open the `main()` function in the script.
   - Update the `latex_file` variable with the path to your LaTeX file:
     ```python
     latex_file = "/path/to/your/FrenchVocab.tex"
     ```

## Usage

To run the French Vocabulary LaTeX Builder:

1. Open a terminal and navigate to the project directory.
2. Run the script:
   ```
   python french_vocab_builder.py
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

### 2. Live Search
- Search through existing entries in real-time.
- View word types and definitions for quick reference.

### 3. Automatic Alphabetization
- Entries are automatically sorted alphabetically in the LaTeX file.

### 4. Duplicate Handling
- The system checks for duplicates and offers options to skip, view, or force add the entry.

### 5. AI-Powered Assistance
- Utilizes Claude AI to generate accurate definitions and contextual examples.

## Troubleshooting

- **API Key Issues**: Ensure your Anthropic API key is correctly set as an environment variable.
- **File Not Found Error**: Double-check the path to your LaTeX file in the `main()` function.
- **Unicode Errors**: Make sure your terminal supports UTF-8 encoding for proper display of French characters.

## Contributing

Contributions to the French Vocabulary LaTeX Builder are welcome! Please follow these steps:

1. Fork the repository.
2. Create a new branch for your feature.
3. Commit your changes.
4. Push to your branch.
5. Create a pull request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
