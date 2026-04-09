# speedster-harness

A setup harness for connecting [OpenCode](https://opencode.ai) AI to self-hosted [vLLM](https://vllm.ai) instances.

## Quick Start

```bash
# Local vLLM (no API key needed)
./opencode-setup.sh http://localhost:8000/v1

# Remote vLLM with API key
export VLLM_API_KEY="your-api-key"
./opencode-setup.sh https://vllm.example.com/v1

# Remote vLLM without scheme (auto-detects http://)
./opencode-setup.sh 192.168.1.100:8000/v1
```

## What It Does

This script automates the configuration of OpenCode to work with your local or self-hosted vLLM deployment:

1. **Validates** the vLLM endpoint is reachable
2. **Detects** available models from `/v1/models` API
3. **Backs up** existing OpenCode configuration
4. **Generates** new config with vLLM connection details
5. **Installs** OpenCode CLI if not present (optional)
6. **Launches** OpenCode with the configured model

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     opencode-setup.sh                        │
├─────────────────────────────────────────────────────────────┤
│  1. Validate URL & prerequisites (bash, curl, python3)       │
│  2. Test vLLM connectivity at /v1/models                     │
│  3. Auto-detect model from vLLM API response                 │
│  4. Backup existing ~config/opencode.json                    │
│  5. Generate new config with vLLM provider settings          │
│  6. Optionally install opencode-ai npm package               │
│  7. Launch OpenCode with configured vLLM model               │
└─────────────────────────────────────────────────────────────┘
```

## Prerequisites

- **Bash** (bash 3.0+ or bash 4+)
- **curl** (for API validation)
- **python3** (for JSON parsing and validation)
- **npm** (optional, for auto-installing opencode)

## Platform Support

This script is cross-platform and works on:

- **macOS** (Intel and Apple Silicon)
- **Linux** (all distributions)
- **WSL** (Windows Subsystem for Linux)

No platform-specific package managers are used—only POSIX-compatible tools.

## Configuration Options

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `VLLM_API_KEY` | (none) | API key for vLLM authentication. If set, added to Authorization header |
| `MODEL` | auto-detect | Override automatic model detection. Format: exact/model/name |
| `AUTO_INSTALL_OPENCODE` | 1 | Set to `0` to skip automatic opencode installation |
| `XDG_CONFIG_HOME` | ~$HOME/.config | Custom config directory for OpenCode |
| `OPENCODE_CONFIG_DIR` | ~$XDG_CONFIG_HOME/opencode | Override config directory |
| `OPENCODE_CONFIG_PATH` | ~$OPENCODE_CONFIG_DIR/opencode.json | Override config file path |

### Example Configurations

**No authentication (development):**
```bash
./opencode-setup.sh http://localhost:8000/v1
```

**With API key:**
```bash
export VLLM_API_KEY="sk-abc123..."
./opencode-setup.sh https://vllm.company.com/v1
```

**Custom model override:**
```bash
export MODEL="meta-llama/Meta-Llama-3-70B-Instruct"
./opencode-setup.sh http://localhost:8000/v1
```

**Skip auto-install (manual opencode install):**
```bash
export AUTO_INSTALL_OPENCODE=0
./opencode-setup.sh http://localhost:8000/v1
```

## Generated Configuration

The script generates an OpenCode config at `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "vllm": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "vLLM (local)",
      "options": {
        "baseURL": "http://localhost:8000/v1"
      },
      "models": {
        "meta-llama/Meta-Llama-3-70B-Instruct": { "name": "meta-llama/Meta-Llama-3-70B-Instruct" }
      }
    }
  },
  "model": "vllm/meta-llama/Meta-Llama-3-70B-Instruct",
  "permission": {
    "bash": "ask",
    "edit": "allow",
    "webfetch": "allow"
  }
}
```

## Security Features

- **Secure file permissions**: Config directory (700), config files (600)
- **No secrets stored**: API keys must be passed via environment variables
- **Config backup**: Existing config backed up before modification with timestamp
- **Validation**: URL scheme validation (http/https only), model name regex validation
- **Atomic writes**: Temp file + rename ensures config integrity

## Troubleshooting

### "ERROR: could not reach vLLM"

**Cause**: vLLM is not running or URL is incorrect

**Solutions**:
- Ensure vLLM is running: `vllm serve your-model`
- Check base URL includes `/v1`: `http://localhost:8000/v1`
- Verify vLLM is accessible: `curl http://localhost:8000/v1/models`
- Check firewall/port: Is the port open and accessible?

### "ERROR: invalid vLLM base URL"

**Cause**: URL format doesn't match expected pattern

**Expected format**: `<scheme>://host:port` or `<scheme>://host:port/v1`

**Valid examples**:
- `http://localhost:8000/v1`
- `https://vllm.example.com/v1`
- `192.168.1.100:8000` (auto-converts to http://)

### "ERROR: could not determine model name"

**Cause**: vLLM models endpoint returned empty or invalid response

**Solutions**:
- Check vLLM models endpoint directly: `curl http://localhost:8000/v1/models`
- Manually specify model: `export MODEL=your-model-name ./opencode-setup.sh ...`
- Verify vLLM has loaded at least one model

### "ERROR: opencode is not installed"

**Cause**: OpenCode CLI not found on system

**Solutions**:
- Install manually: `npm install -g opencode-ai`
- Or retry with: `export AUTO_INSTALL_OPENCODE=1 ./opencode-setup.sh ...`

### OpenCode doesn't launch after setup

**Cause**: opencode binary not in PATH after installation

**Solutions**:
- Check installation: `which opencode`
- Try manual launch: `opencode` after running setup
- Check npm global installs: `npm list -g opencode-ai`

## vLLM Setup Reference

For setting up your own vLLM instance:

```bash
# Install vLLM
pip install vllm

# Serve a model
vllm serve meta-llama/Meta-Llama-3-70B-Instruct --port 8000

# Or with GPU optimizations
vllm serve your-model --tensor-parallel-size 2 --max-model-len 32768
```

## Development

### Testing

Run shellcheck for code quality:
```bash
shellcheck -S opencode-setup.sh
```

Validate script syntax:
```bash
bash -n opencode-setup.sh
```

### Pre-commit Hooks

Initialize pre-commit hooks for local development:
```bash
pip install pre-commit
pre-commit install
```

## License

Apache License 2.0. See LICENSE file for details.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.

## Support

File issues and feature requests on GitHub: https://github.com/n-belokopytov/speedster-harness/issues

## Versioning

This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

See [CHANGELOG.md](CHANGELOG.md) for release history.
