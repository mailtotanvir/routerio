from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTML_FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import time
import os

from config import config
import database
from services.routing_service import RoutingService
from services.cache_service import SemanticCacheService

app = FastAPI(title=config.APP_NAME, version=config.VERSION)

# Mount static folder
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

routing_service = RoutingService()
cache_service = SemanticCacheService()

# 1. Pydantic Models for standard inputs
class Message(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    messages: list[Message]
    model: str = "routerio-intelligent-router"
    policy: str = "cost"          # 'cost', 'performance', 'latency'
    compliance: str = "global"     # 'global', 'us-only'
    bypass_cache: bool = False

# 2. Main OpenAI-compatible chat completion route
@app.post("/v1/chat/completions")
async def chat_completions(payload: ChatCompletionRequest):
    # Retrieve user prompt
    if not payload.messages:
        raise HTTPException(status_code=400, detail="Messages list cannot be empty.")
    
    prompt = payload.messages[-1].content
    
    # Check Semantic Cache first
    if not payload.bypass_cache:
        cached_result = cache_service.lookup(prompt)
        if cached_result:
            # Found semantic match! Return instant cache response
            elapsed_ms = 0
            
            # Save cache hit in audit logs
            database.insert_audit_log(
                prompt=prompt,
                response=cached_result["text"],
                policy=payload.policy,
                selected_model="semantic-cache-hit",
                actual_model=cached_result["actual_model"],
                provider=cached_result["provider"],
                latency_ms=0.0,
                prompt_tokens=len(prompt.split()),
                completion_tokens=len(cached_result["text"].split()),
                cost=0.0,
                cost_saved=0.015, # Simulated savings on semantic hit
                reasoning_trace={"cache_hit": True, "similarity_match": cached_result["similarity"]},
                was_cached=1,
                was_fallback=0
            )
            
            return {
                "id": f"chatcmpl-cache-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": cached_result["actual_model"],
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": cached_result["text"]
                    },
                    "finish_reason": "stop"
                }],
                "usage": {
                    "prompt_tokens": len(prompt.split()),
                    "completion_tokens": len(cached_result["text"].split()),
                    "total_tokens": len(prompt.split()) + len(cached_result["text"].split())
                },
                "routerio_meta": {
                    "was_cached": True,
                    "similarity": cached_result["similarity"],
                    "provider": cached_result["provider"]
                }
            }

    # If cache miss, proceed to dynamic router
    try:
        routed_res = await routing_service.route_request(
            prompt=prompt,
            policy=payload.policy,
            compliance=payload.compliance
        )
        
        # Save cache entry if request was not bypassed
        if not payload.bypass_cache:
            cache_service.store(
                prompt=prompt,
                response=routed_res["text"],
                model=routed_res["actual_model"],
                provider=routed_res["provider"]
            )
            
        # Log successful completion
        database.insert_audit_log(
            prompt=prompt,
            response=routed_res["text"],
            policy=payload.policy,
            selected_model=routed_res["selected_model"],
            actual_model=routed_res["actual_model"],
            provider=routed_res["provider"],
            latency_ms=routed_res["latency_ms"],
            prompt_tokens=routed_res["prompt_tokens"],
            completion_tokens=routed_res["completion_tokens"],
            cost=routed_res["cost"],
            cost_saved=max(0.0, 0.018 - routed_res["cost"]), # Estimated baseline savings comparison
            reasoning_trace=routed_res["trace"],
            was_cached=0,
            was_fallback=routed_res["was_fallback"],
            fallback_reason=routed_res["fallback_reason"]
        )
        
        return {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": routed_res["actual_model"],
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": routed_res["text"]
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": routed_res["prompt_tokens"],
                "completion_tokens": routed_res["completion_tokens"],
                "total_tokens": routed_res["prompt_tokens"] + routed_res["completion_tokens"]
            },
            "routerio_meta": {
                "was_cached": False,
                "was_fallback": bool(routed_res["was_fallback"]),
                "provider": routed_res["provider"],
                "trace": routed_res["trace"]
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 3. Admin / Dashboard Analytics Routes
@app.get("/api/logs")
def get_logs():
    return JSONResponse(content=database.get_all_logs())

@app.get("/api/analytics")
def get_analytics():
    return JSONResponse(content=database.get_analytics_summary())

@app.get("/api/circuit-breakers")
def get_circuit_status():
    return JSONResponse(content=database.get_circuit_breakers())

@app.post("/api/cache/clear")
def clear_cache():
    cache_service.clear_cache()
    return {"status": "success", "message": "Cache cleared."}

@app.post("/api/circuit-breakers/reset")
def reset_breakers():
    providers = ["openai", "anthropic", "google", "ollama"]
    for provider in providers:
        database.update_circuit_breaker(provider, "CLOSED", 0)
    return {"status": "success", "message": "All circuit breakers reset."}

# Render main dashboard index
@app.get("/")
def read_root():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return HTML_FileResponse(index_path)
    return {"error": "Dashboard UI under development. Please check back shortly."}
