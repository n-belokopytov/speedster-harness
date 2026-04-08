# speedster-harness
A harness for building using local and self-hosted models

## Setup

To configure OpenCode with your vLLM instance, run:

```bash
./opencode-setup.sh <vllm_base_url>
```

### Example

```bash
# Local vLLM
./opencode-setup.sh http://localhost:8000/v1

# Remote vLLM with API key
export VLLM_API_KEY="your-api-key"
./opencode-setup.sh https://vllm.example.com/v1

# Remote vLLM without scheme (autodetects http://)
./opencode-setup.sh 192.168.178.185:8000/v1
```

### Environment Variables

- `VLLM_API_KEY` - Optional API key for vLLM authentication
- `VLLM_MODEL` - Optional model name (auto-detected from /v1/models if omitted)
- `AUTO_INSTALL_OPENCODE` - Set to `0` to skip automatic opencode installation

### Output

The script will:
1. Validate the vLLM endpoint and detect the available model
2. Create a backup of any existing OpenCode config
3. Generate a new config file with the vLLM connection details
4. Install opencode if not present (unless `AUTO_INSTALL_OPENCODE=0`)
5. Launch OpenCode with the configured model
