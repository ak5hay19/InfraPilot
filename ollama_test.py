import requests

OLLAMA_URL = "http://localhost:11434/api/chat"

payload ={

    "model" : "qwen3:8b",
    "messages" : [
        {
            "role" : "user",
            "content" : "Write Terraform for an S3 bucket with versioning enabled.",
        }

    ],
    "stream" : False, #Ollama waits until the whole reply is done and sends one single JSON object.
    "think" : False, #model specific, qwen3:8b will not think for a few seconds before replying if this is set to True.
    "options" : {
        "num_ctx" : 8192,
        "temperature" : 0.2,
    },

}



response = requests.post(OLLAMA_URL, json = payload, timeout = 300)

#makes HTTP errors (like a wrong model name returning 404) fail loudly instead of giving you a confusing KeyError later.
response.raise_for_status()

data = response.json()

print(data["message"]["content"])
print("------------------------------")
print("tokens in :", data["prompt_eval_count"])
print("tokens out :", data["eval_count"])
print("latency_s", round(data["total_duration"]/1e9,2))

