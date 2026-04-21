# n8n Workflow Automation Integration

This directory contains n8n workflow templates and credentials for the vLLM stack.

## Accessing n8n

Once the stack is running, access n8n at:
- **Main UI**: `http://localhost/n8n/`
- **Webhooks**: `http://localhost/n8n-webhook/`

Both endpoints are protected by the same nginx authentication as the rest of the stack.

## Local vLLM Integration

n8n is pre-configured to connect to the local vLLM instance at:
- **vLLM API URL**: `http://vllm:8000/v1`

### Setting Up HTTP Request Node in n8n

To use the local vLLM endpoint in your workflows:

1. Add an **HTTP Request** node to your workflow
2. Configure with these settings:
   - **Method**: POST
   - **URL**: `http://vllm:8000/v1/completions` (or `/v1/chat/completions` for chat models)
   - **Headers**:
     ```
     Content-Type: application/json
     ```
   - **Body** (JSON):
     ```json
     {
       "model": "/models/Qwen_Qwen2.5-7B-Instruct",
       "prompt": "Your prompt here",
       "max_tokens": 512,
       "temperature": 0.7
     }
     ```

### Example: Chat Completion Request

For chat-based models:

```json
{
  "model": "/models/Qwen_Qwen2.5-7B-Instruct",
  "messages": [
    {
      "role": "system",
      "content": "You are a helpful assistant."
    },
    {
      "role": "user",
      "content": "Explain quantum computing in simple terms."
    }
  ],
  "max_tokens": 512,
  "temperature": 0.7,
  "stream": false
}
```

## Environment Variables

The following environment variables are available for n8n configuration:

| Variable | Description | Default |
|----------|-------------|---------|
| `N8N_HOST` | Hostname for n8n | `localhost` |
| `N8N_BASE_URL` | Base URL for n8n | `http://localhost/n8n` |
| `WEBHOOK_URL` | Webhook endpoint URL | `http://localhost/n8n-webhook/` |
| `TIMEZONE` | Timezone for scheduling | `UTC` |
| `N8N_ENCRYPTION_KEY` | Encryption key for credentials | *(set in .env)* |
| `VLLM_API_URL` | Internal vLLM API URL | `http://vllm:8000/v1` |

## First-Time Setup

1. Start the stack: `docker compose --env-file .env.active up -d`
2. Wait for n8n to be healthy (~60 seconds)
3. Visit `http://localhost/n8n/` and authenticate via nginx
4. Create your first admin user in n8n
5. Create workflows using the local vLLM endpoint

## Persistent Data

n8n data (workflows, credentials, executions) is stored in the `n8n_data` Docker volume.

## Security Notes

- Change `N8N_ENCRYPTION_KEY` in `.env` before production use
- All n8n endpoints are protected by nginx basic auth
- The vLLM endpoint is only accessible within the Docker network (no external exposure)
