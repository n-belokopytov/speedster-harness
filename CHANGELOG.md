# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial release of speedster-harness

### Changed
- N/A

### Fixed
- N/A

### Security
- N/A

## [0.1.0] - 2026-04-09

### Added
- Initial commit with opencode-setup.sh script
- Auto-detection of vLLM models
- Config backup functionality
- URL and model name validation
- Secure file permissions (700 for directory, 600 for files)
- Atomic writes for config file updates
- Optional automatic opencode installation

### Changed
- Simplified JSON escaping function
- Improved error messages

### Fixed
- URL scheme validation (http/https only)
- Model name validation regex

### Security
- No secrets stored in config files
- API keys passed via environment variables only
- Config file permission restrictions
