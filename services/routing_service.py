import time
from datetime import datetime, timedelta
from database import get_circuit_breakers, update_circuit_breaker
from services.provider_service import LLMProviderService

class RoutingService:
    def __init__(self):
        self.provider_service = LLMProviderService()

    def classify_complexity(self, prompt: str) -> tuple[str, list[str]]:
        """
        Classifies prompt complexity (Low, Medium, High) based on heuristics.
        Returns a tuple of (complexity_level, reasoning_triggers).
        """
        prompt_lower = prompt.lower()
        triggers = []
        
        # High reasoning triggers
        high_keywords = ["analyze", "explain the difference", "architect", "optimize", "debug", "refactor", "design pattern", "concurrency", "race condition"]
        high_matches = [kw for kw in high_keywords if kw in prompt_lower]
        
        # Medium reasoning triggers
        medium_keywords = ["write a function", "query", "select", "how do i", "create a table", "parse", "regex", "convert", "translate"]
        medium_matches = [kw for kw in medium_keywords if kw in prompt_lower]

        # Structure checks
        code_symbols = ["{", "}", "def ", "class ", "import ", "const ", "function "]
        has_code = any(sym in prompt for sym in code_symbols)
        
        # Scoring
        score = 0
        if len(prompt) > 250:
            score += 2
            triggers.append("Prompt length > 250 characters (+2)")
        if len(prompt) > 600:
            score += 2
            triggers.append("Prompt length > 600 characters (+2)")
        if high_matches:
            score += 3
            if len(high_matches) > 1:
                score += 2  # Bonus for multiple advanced topics
            triggers.append(f"High-complexity keywords matched: {high_matches} (+3)")
        if medium_matches:
            score += 2.0
            triggers.append(f"Medium-complexity keywords matched: {medium_matches} (+2)")
        if has_code:
            score += 2
            triggers.append("Code structure / syntax symbols detected (+2)")

        if score >= 5:
            return "High", triggers
        elif score >= 2:
            return "Medium", triggers
        else:
            return "Low", ["Short conversational structure (<2)"]

    def select_model(self, complexity: str, policy: str, compliance: str = "global") -> tuple[str, list[str]]:
        """
        Determines the optimal model based on prompt complexity, user-selected policy
        (cost, performance, latency), and compliance restrictions.
        """
        trace = []
        trace.append(f"Analyzing with strategy policy: '{policy}', compliance level: '{compliance}'")
        
        breakers = get_circuit_breakers()
        
        # Primary candidate matrix
        candidates = []
        if complexity == "High":
            if policy == "performance":
                candidates = ["anthropic/claude-3-5-sonnet", "openai/gpt-4o", "google/gemini-2.5-flash"]
            elif policy == "latency":
                candidates = ["openai/gpt-4o", "google/gemini-2.5-flash", "anthropic/claude-3-5-sonnet"]
            else: # cost
                candidates = ["google/gemini-2.5-flash", "openai/gpt-4o-mini", "anthropic/claude-3-5-sonnet"]
        elif complexity == "Medium":
            if policy == "performance":
                candidates = ["openai/gpt-4o", "anthropic/claude-3-5-sonnet", "google/gemini-2.5-flash"]
            elif policy == "latency":
                candidates = ["openai/gpt-4o-mini", "google/gemini-2.5-flash", "openai/gpt-4o"]
            else: # cost
                candidates = ["google/gemini-2.5-flash", "openai/gpt-4o-mini", "ollama/llama3"]
        else: # Low complexity
            if policy == "latency":
                candidates = ["openai/gpt-4o-mini", "google/gemini-2.5-flash", "ollama/llama3"]
            elif policy == "performance":
                candidates = ["openai/gpt-4o-mini", "google/gemini-2.5-flash", "openai/gpt-4o"]
            else: # cost
                candidates = ["google/gemini-2.5-flash", "ollama/llama3", "openai/gpt-4o-mini"]

        # Apply compliance filters
        if compliance == "us-only":
            # Filter out Ollama or other models if compliance dictates
            trace.append("Compliance filter 'us-only' active. Filtering models...")
            # (Just an illustrative rule: keeping OpenAI/Anthropic/Google, removing local ollama)
            candidates = [c for c in candidates if not c.startswith("ollama")]

        # Filter by circuit breaker
        selected_model = None
        fallback_models = []
        
        for candidate in candidates:
            provider = candidate.split('/')[0]
            breaker = breakers.get(provider, {"status": "CLOSED", "last_failure_time": None})
            
            # Check if tripped
            if breaker["status"] == "OPEN":
                # Check if cooling off period is over (e.g. 60 seconds)
                last_fail_str = breaker["last_failure_time"]
                is_cooldown = True
                if last_fail_str:
                    last_fail = datetime.fromisoformat(last_fail_str)
                    if datetime.utcnow() - last_fail > timedelta(seconds=60):
                        is_cooldown = False
                        # Try to probe (HALF-OPEN)
                        update_circuit_breaker(provider, "HALF-OPEN", consecutive_failures=1)
                        trace.append(f"Circuit breaker for provider '{provider}' cooling period ended. Promoting to HALF-OPEN.")
                
                if is_cooldown:
                    trace.append(f"Model candidate '{candidate}' SKIPPED: Circuit breaker for provider '{provider}' is TRIPPED.")
                    continue
            
            if not selected_model:
                selected_model = candidate
                trace.append(f"Primary choice: '{candidate}'")
            else:
                fallback_models.append(candidate)
                
        if not selected_model:
            # Fallback to absolute default if everything was skipped
            selected_model = "google/gemini-2.5-flash"
            trace.append("CRITICAL: All routing choices are blocked by active circuit breakers! Falling back to emergency default 'google/gemini-2.5-flash'.")
            
        return selected_model, fallback_models, trace

    async def route_request(self, prompt: str, policy: str = "cost", compliance: str = "global") -> dict:
        """
        Coordinates full request lifecycle: classifies complexity, selects optimal model,
        executes requests with automated retry/fallback mechanisms.
        """
        complexity, complexity_triggers = self.classify_complexity(prompt)
        selected_model, fallback_models, routing_trace = self.select_model(complexity, policy, compliance)
        
        trace = {
            "complexity": complexity,
            "complexity_triggers": complexity_triggers,
            "routing_path": routing_trace,
            "fallbacks_attempted": []
        }
        
        model_to_try = selected_model
        fallback_queue = list(fallback_models)
        
        while True:
            provider = model_to_try.split('/')[0]
            try:
                # Trigger provider call
                response = await self.provider_service.execute_request(model_to_try, prompt)
                
                # If successful and was HALF-OPEN, close the circuit breaker
                breakers = get_circuit_breakers()
                if breakers.get(provider, {}).get("status") == "HALF-OPEN":
                    update_circuit_breaker(provider, "CLOSED", consecutive_failures=0)
                    trace["routing_path"].append(f"Success! Re-closed circuit breaker for provider '{provider}'.")
                
                # Build complete result package
                return {
                    "text": response["text"],
                    "selected_model": selected_model,
                    "actual_model": model_to_try,
                    "provider": response["provider"],
                    "latency_ms": response["latency_ms"],
                    "prompt_tokens": response["prompt_tokens"],
                    "completion_tokens": response["completion_tokens"],
                    "cost": response["cost"],
                    "was_fallback": int(model_to_try != selected_model),
                    "fallback_reason": ", ".join(trace["fallbacks_attempted"]) if trace["fallbacks_attempted"] else None,
                    "trace": trace
                }
            except Exception as e:
                error_msg = str(e)
                trace["fallbacks_attempted"].append(f"Failed '{model_to_try}': {error_msg}")
                
                # Trip or escalate circuit breaker for failed provider
                breakers = get_circuit_breakers()
                current_consecutive = breakers.get(provider, {}).get("consecutive_failures", 0) + 1
                new_status = "OPEN" if current_consecutive >= 3 else "CLOSED"
                update_circuit_breaker(provider, new_status, consecutive_failures=current_consecutive, last_error_message=error_msg)
                
                trace["routing_path"].append(f"Error on '{model_to_try}' (consecutive={current_consecutive}). Circuit status set to {new_status}.")
                
                # Fetch next fallback
                if fallback_queue:
                    model_to_try = fallback_queue.pop(0)
                    trace["routing_path"].append(f"Executing recovery. Falling back to alternative model: '{model_to_try}'")
                else:
                    raise RuntimeError(f"All routed LLM providers failed. Last error: {error_msg}")
